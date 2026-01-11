import os
import copy
import sys
import json
import time
import argparse
import logging
import concurrent.futures
import subprocess
from pathlib import Path

import stitch
import utils
import resolve_deps

log = logging.getLogger(__name__)

DEBUG = 1

def setup_logging(args):
    levels = {
        "critical": logging.CRITICAL,
        "error": logging.ERROR,
        "warn": logging.WARNING,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG,
    }
    level = levels.get(args.log.lower())
    if level is None:
        raise ValueError(
            f"log level given: {args.log}"
            f" -- must be one of: {' | '.join(levels.keys())}"
        )

    fmt = "%(asctime)s "
    fmt += "%(module)s:%(lineno)s [%(levelname)s] "
    fmt += "%(message)s"
    datefmt='%Y-%m-%dT%H:%M:%S'

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)

def parse_args():
    p = argparse.ArgumentParser(description='Produce Unified Stitch for a CSV containing user/repo pairs (from GitHub).')
    p.add_argument(
        "-l",
        "--log",
        default="info",
        help=("Provide logging level. Example --log debug"),
    )
    p.add_argument(
        "-i",
        "--input",
        default=None,
        help=("Provide path to the CSV containing the user/repo pairs"),
    )
    return p.parse_args()


def count_py_files(directory):
    count = 0
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                count += 1
    return count

class PartialCallgraphGenerator():
    def __init__(self, package, always, is_app, only_fix=False):
        self.package = package
        self.always = always
        self.is_app = is_app
        self.only_fix=only_fix
        if ':' not in self.package:
            err = (f'Unrecognized package format: {package}')
            raise ValueError(err)
        self.product = self.package.split(':')[0]
        self.version = self.package.split(':')[1]
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")

        self.tmp_install_solo_root = os.path.join(self.git_root, 'data/install_solo')
        self.tmp_install_solo_dir = os.path.join(self.tmp_install_solo_root, self.product[0], self.product, self.version)

        self.partial_cg_root = os.path.join(self.git_root, 'data/partial_callgraphs')
        self.partial_cg_dir = os.path.join(self.partial_cg_root, self.product[0], self.product, self.version)
        self.partial_cg_path = os.path.join(self.partial_cg_dir, 'cg.json')

    def install_solo(self):
        log.info(f'Installing package {self.package} {self.tmp_install_solo_dir}')

        if not os.path.exists(self.tmp_install_solo_dir) or self.always:
            cmd = [
                'pip3',
                'install',
                '-t', self.tmp_install_solo_dir,
                '--no-deps',
                "{}=={}".format(self.product, self.version)
            ]
            try:
                ret, out, err = utils.run_cmd(cmd)
                if ret != 0:
                    return ret
            except Exception as e:
                log.error(e)
                return -1
        else:
            log.info(f'Tmp install dir already exists... Skipping install')
        return 0

    def find_toplevel_dir(self):
        solo_dir_Path = Path(self.tmp_install_solo_dir)
        items = list(solo_dir_Path.iterdir())
        items_filtered = []
        for i in items:
            lename = i.name.lower()
            if (not lename.endswith("dist-info")
                and not lename.endswith("egg-info")
                and not lename.endswith("__pycache__")
                and not lename.endswith("bin")):
                items_filtered.append(i)

        lower2orig = {}
        items_dirs = []
        items_singles_lower = []
        for it in items_filtered:
            if it.is_dir():
                items_dirs.append(it)
            else:
                lower = it.name.lower()
                items_singles_lower.append(lower)
                lower2orig[lower] = it.name

        product_lower = self.product.lower()
        closest = None
        if len(items_dirs) == 1:
            return os.path.join(self.tmp_install_solo_dir, items_dirs[0])
        elif len(items_dirs) > 1:
            log.warning(f'Many top-level dirs to choose from: {items_dirs}')
            py_counts = [[count_py_files(os.path.join(self.tmp_install_solo_dir,it)), it] for it in items_dirs]
            py_counts.sort(key=lambda x: x[0], reverse=True)
            dir_max_py_files = py_counts[0][1]
            return os.path.join(self.tmp_install_solo_dir, dir_max_py_files)
        elif len(items_singles_lower) > 0:
            closest = utils.find_closest_match(product_lower, items_singles_lower)
            log.warning(f'Many singles to choose from: {items_singles_lower}')
            return os.path.join(self.tmp_install_solo_dir, lower2orig[closest])

        return None

    def generate_callgraph(self):
        log.info(f'Generating partial callgraph for package {self.package}')

        utils.create_dir(self.partial_cg_dir)
        package_path = Path(self.top_level_dir)
        files_list = []
        if not package_path.name.endswith(".py"):
            files_list = self._get_python_files(package_path)
        else:
            files_list = [package_path.as_posix()]

        if (package_path/"__init__.py").exists():
            package_path = package_path.parent

        if self.is_app:
            max_iter = '-1'
        else:
            max_iter = '1'

        BLACKLIST_FILES = []

        files_list = [f for f in files_list if f not in BLACKLIST_FILES]

        cmd1 = [
            'python3',
            '-u',
            '-m',
            'pycg',
            '--fasten',
            '--package', package_path.as_posix(),
            '--product', self.product,
            '--version', self.version,
            '--forge', 'PyPI',
            '--max-iter', max_iter,
            '--timestamp', '0',
            '--output', self.partial_cg_path
            ]
        cmd = cmd1 + files_list
        done = False
        retried = False
        if not DEBUG:
            while not done:
                try:
                    log.info(f'CMD1 = {cmd1}, retried = {retried}')
                    ret, out, err = utils.run_cmd(cmd)
                    if ret != 0:
                        if ret == 1 and 'TIMEOUT' in out and not retried:
                            cmd1 = [
                                'python3',
                                '-m',
                                'pycg',
                                '--fasten',
                                '--package', package_path.as_posix(),
                                '--product', self.product,
                                '--version', self.version,
                                '--forge', 'PyPI',
                                '--max-iter', '1',
                                '--timestamp', '0',
                                '--output', self.partial_cg_path,
                                '--no-analyze-external'
                                ]
                            cmd = cmd1 + files_list
                            log.info('Timed out. Retrying without external analysis...')
                            retried = True
                        else:
                            log.info(f'RET: {ret}')
                            log.info(f'OUT: {out}')
                            log.info(f'ERR: {err}')
                            return ret
                    else:
                        done = True

                except Exception as e:
                    log.error(e)
                    return -1
        else:
            log.info(cmd)
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            for line in process.stdout:
                log.info(line)

            out, err = process.communicate(timeout=None)
            ret = process.returncode

            log.info(f'OUT: {out}')
            log.info(f'ERR: {err}')
            log.info(f'RET: {ret}')

        if not os.path.exists(self.partial_cg_path):
            return -1

        log.info(f'Wrote partial callgraph to {self.partial_cg_path}')

        return 0

    def _should_include(self, file_path, excluded_dirs):
        return not any(excluded_dir in file_path.parts[:-1] for excluded_dir in excluded_dirs)

    def _get_python_files(self, package):
        # excluded_dirs = ["tests", "test", "docs", "examples", "_vendor", "_distutils"]
        excluded_dirs = []
        return [x.resolve().as_posix().strip() for x in package.glob("**/*.py") if self._should_include(x, excluded_dirs)]


    def fix_externals(self):
        tl = Path(self.top_level_dir)
        tl_name = os.path.basename(self.top_level_dir)
        if not tl.is_dir():
            return 0

        files = [str(x) for x in tl.rglob('*')]

        with open(self.partial_cg_path, 'r') as infile:
            cg_orig = json.loads(infile.read())

        cg = copy.deepcopy(cg_orig)

        external_modules = cg['modules']['external']

        must_convert_idxs = []
        new_ns = []
        for km, vm in cg_orig['modules']['external'].items():
            for kn, vn in vm['namespaces'].items():
                ns = vn['namespace']
                extname = ns.split("//")[-1]
                parts = extname.split('.')
                possible_names = [parts[0]]
                pn = parts[0]
                possible_namesnips = ['/' + pn + '.']
                for p in parts[1:]:
                    pn += '/' + p
                    possible_namesnips.append(pn + '.')

                found = False
                for n in possible_namesnips:
                    for f in files:
                        if n in f and f.endswith('.so'):
                            found = True
                            break
                    if found:
                        break

                if found:
                    mod_path = f
                    root_dir = self.top_level_dir
                    mod_fqn = stitch.mod_path_to_fqn(mod_path, root_dir)

                    log.info(f'External ns {ns}, namesnip {n} matches file {f}')
                    newname = '/' + tl_name + '/' + mod_fqn + '.' + ".".join(extname.split('.')[1:])
                    new_ns = {"namespace": newname, "metadata": vn['metadata']}
                    log.info(f'Adding {new_ns} to internals')
                    if 'FFI' in cg['modules']['internal'].keys():
                        cg['modules']['internal']['FFI']['namespaces'][kn] = new_ns
                    else:
                        cg['modules']['internal']['FFI'] = {'namespaces': {kn: new_ns}}

                    must_convert_idxs.append(kn)
                    log.info(f'Deleting ns {vn}')
                    del cg['modules']['external'][km]['namespaces'][kn]

        new_internal_calls = cg['graph']['internalCalls']
        orig_external_calls = cg['graph']['externalCalls']
        new_ext_calls = []

        for call in orig_external_calls:
            dst = call[1]
            if dst in must_convert_idxs:
                new_internal_calls.append(call)
            else:
                new_ext_calls.append(call)


        cg['graph']['internalCalls'] = new_internal_calls
        cg['graph']['externalCalls'] = new_ext_calls

        with open(self.partial_cg_path, 'w') as outfile:
            outfile.write(json.dumps(cg, indent=2))

        return 0


    def process(self):
        if os.path.exists(self.partial_cg_path) and not self.always:
            log.info(f'Callgraph for {self.package} already exists at {self.partial_cg_path}')
            return 0
        ret = self.install_solo()
        if ret != 0:
            return ret

        self.top_level_dir = self.find_toplevel_dir()

        log.info(f'Top-level dir: {self.top_level_dir}')

        if self.top_level_dir is None:
            log.error(f'No top-level dir/file found. Aborting!')
            return -1

        if not self.only_fix:
            ret = self.generate_callgraph()
            if ret != 0:
                log.error(f'Failed to generate partial callgraph for package: {self.package}')
                return ret

        ret = self.fix_externals()
        if ret != 0:
            log.error(f'Failed to fix externals to internals for package: {self.package}')
            return ret


def do_single(package, always=True, only_fix=False):
    pcg_producer = PartialCallgraphGenerator(package, always, False, only_fix)
    pcg_producer.process()

def main():
    args = parse_args()
    setup_logging(args)

    if args.input is None:
        log.error("Must provide input CSV file")
        sys.exit(1)

    packages = utils.load_csv(args.input)
    log.info(f"packages = {packages}")


    for pkg in packages:
        do_single(pkg)

if __name__ == "__main__":
    main()


