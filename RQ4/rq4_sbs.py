import os
import sys
import json
import logging
import argparse
from collections import defaultdict

import concurrent.futures
from pathlib import Path

import utils
log = logging.getLogger(__name__)

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
    # Use ISO 8601 format
    datefmt='%Y-%m-%dT%H:%M:%S'

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)

def parse_args():
    p = argparse.ArgumentParser(description='Produce Binary Stats for all PyPI packages in data/')
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
        help=("Provide path to the CSV containing package:version pairs"),
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help=("Provide path to output JSON"),
    )
    p.add_argument(
        "-A",
        "--always",
        default=False,
        action='store_true',
        help=("Always process callgraphs."),
    )
    return p.parse_args()

def get_py_files_size(directory):
    total_size = 0

    # Walk through the directory recursively
    for dirpath, dirnames, filenames in os.walk(directory):
        for filename in filenames:
            if filename.endswith('.py'):
                # Get the full file path
                file_path = os.path.join(dirpath, filename)

                # Add the size of the file to the total size
                total_size += os.path.getsize(file_path)

    return total_size

class BloatCalculator():
    def __init__(self, input_file, output_file):
        self.input_file = input_file
        self.output_file = output_file
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")

        self.deps_dir_root = os.path.join(self.git_root, 'data/dependencies')
        # self.deps_dir = os.path.join(self.deps_dir_root, self.name[0], self.name, self.version)
        # self.deps_all_path = os.path.join(self.deps_dir, 'deps.json')
        # self.deps_direct_path = os.path.join(self.deps_dir, 'direct.json')
        self.binary_sizes_path = os.path.join(self.git_root, 'RQ4/binary_sizes.json')
        if os.path.exists(self.binary_sizes_path):
            with open(self.binary_sizes_path, 'r') as infile:
                self.binary_sizes = json.loads(infile.read())
            self.must_compute_binary_sizes = False
        else:
            self.binary_sizes = {}
            self.must_compute_binary_sizes = True

        self.sbs_root = os.path.join(self.git_root, 'data/sbs')
        self.bcg_root = os.path.join(self.git_root, 'data/binary_callgraphs')
        self.bcgs_per_package = defaultdict(list)
        self.stats = defaultdict(dict)
        self.reached_cg_root = os.path.join(self.git_root, 'data/reached_cg/pypi')
        self.tmp_install_dir_root = os.path.join(self.git_root, 'data/install')

        self.tmp_install_dir_toplevel_root = os.path.join(self.git_root, 'data/install_toplevel')

        self.apps = None
        self.app2reachedcg = {}
        self.app2installdir = {}
        self.app2alldeps = {}
        self.app2directdeps = {}
        self.lib_missing_sbs_sym = set()

        self.python_sizes_path = os.path.join(self.git_root, 'RQ4/python_sizes.json')
        if os.path.exists(self.python_sizes_path):
            with open(self.python_sizes_path, 'r') as infile:
                self.python_sizes = json.loads(infile.read())
            self.must_compute_python_sizes = False
        else:
            self.python_sizes = {}
            self.must_compute_python_sizes = True

        self.num_direct = 0
        self.num_transitive = 0

        self.total_names = 0
        self.total_no_sbs_sym = 0

        self.total_stats = {'num_success': 0, 'num_no_xlcg': 0, 'num_no_dep_bin': 0,
                            'no_xlcg': [], 'no_dep_bin': [], 'data': {}}

    def do_one(self, app):
        log.info(f'App = {app}')
        reached_cg_path = self.app2reachedcg[app]
        install_dir = self.app2installdir[app]
        deps_all = self.app2alldeps[app]
        deps_direct = self.app2directdeps[app]
        deps_transitive = [d for d in deps_all if d not in deps_direct]

        self.num_direct += len(deps_direct)
        self.num_transitive += len(deps_transitive)

        # log.info(f'app = {app}')
        # log.info(f'all = {deps_all}')
        # log.info(f'direct = {deps_direct}')
        # log.info(f'transitive = {deps_transitive}')

        # log.info(f'deps_all = {deps_all}')
        # log.info(f'deps_direct = {deps_direct}')
        # log.info(f'deps_transitive = {deps_transitive}')

        lib2totalsbssyms = {}
        lib2totalbcgsyms = {}
        lib2size = {}
        lib2reached = defaultdict(int)
        lib2pkg = {}
        lib2size = {}

        python_size_all = 0
        python_size_direct = 0
        python_size_transitive = 0


        reachable_python_packages = set()

        n2lib = {}

        stats = {'all': defaultdict(dict), 'direct': defaultdict(dict), 'transitive': defaultdict(dict)}

        if not os.path.exists(reached_cg_path):
            log.debug(f'App {app} has no reached CG. Skipping!')
            self.total_stats['no_xlcg'].append(app)
            return
        with open(reached_cg_path, 'r') as infile:
            reached_cg = json.loads(infile.read())

        for d in deps_all:
            name = d.split(':')[0]
            version = d.split(':')[1]
            bcg_stats_path = os.path.join(self.bcg_root, name[0], name, version, 'stats.json')
            sbs_stats_path = os.path.join(self.sbs_root, name[0], name, version, 'stats.json')
            sbs_path = os.path.join(self.sbs_root, name[0], name, version, 'sbs.json')
            if os.path.exists(bcg_stats_path) and os.path.exists(sbs_stats_path):
                with open(bcg_stats_path, 'r') as infile:
                    bcg_stats = json.loads(infile.read())
                with open(sbs_stats_path, 'r') as infile:
                    sbs_stats = json.loads(infile.read())

                for l, v in bcg_stats.items():
                    # lib = l
                    lib = l.replace('cpython-39', 'cpython')
                    lib = lib.replace('cpython-310', 'cpython')
                    num_syms = v['num_syms']
                    # libpath = os.path.join(install_dir, lib)
                    libpath = os.path.join(install_dir, l)
                    if self.must_compute_binary_sizes:
                        if os.path.exists(libpath):
                            size = os.path.getsize(libpath)
                            print(size)
                        elif os.path.exists(libpath.replace('cpython-39', 'cpython-310')):
                            size = os.path.getsize(libpath)
                            print(size)
                        else:
                            log.debug(f'Library at path {libpath} not found!')
                            # size = 0
                            continue
                    else:
                        # log.info(f"app = {app}")
                        # log.info(f"keys = {self.binary_sizes[app]}")
                        # k = lib.replace('cpython', 'cpython-310')
                        k = lib.replace('cpython', 'cpython-39')
                        # k = lib.replace('cpython-39', 'cpython-310')
                        # if k in self.binary_sizes[app].keys():
                        try:
                            size = self.binary_sizes[app][k]
                        except KeyError:
                            log.debug(f"{k} not in binary_sizes[{app}]")
                            continue
                    lib2totalbcgsyms[lib] = num_syms
                    lib2pkg[lib] = d
                    lib2size[lib] = size

                for l, v in sbs_stats.items():
                    lib = l
                    lib = l.replace('cpython-39', 'cpython')
                    lib = lib.replace('cpython-310', 'cpython')
                    num_syms = v['num_syms']
                    lib2totalsbssyms[lib] = num_syms

                with open(sbs_path, 'r') as infile:
                    sbs = json.loads(infile.read())
                for v in sbs['nodes'].values():
                    if 'library' in v.keys():
                        lib = v['library']
                        lib = lib.replace('cpython-39', 'cpython')
                        lib = lib.replace('cpython-310', 'cpython')
                        name = v['name']
                        n2lib[name] = lib
                log.debug(lib2pkg)
            else:
                log.debug(f'Dep: {d} has no binaries')
                continue

        # XXX: No dependency from this package includes a binary
        if len(lib2totalsbssyms) == 0:
            log.info(f'App {app} has no dependencies with binaries')
            self.total_stats['no_dep_bin'].append(app)
            return

        for k, v in reached_cg['nodes'].items():
            if 'package' in v.keys():
                pkg = v['package']
                reachable_python_packages.add(pkg)
            if 'library' in v.keys():
                rxlcg_lib = v['library']
                # XXX: Make sure lib agrees with SBS.
                name = v['name']
                self.total_names += 1
                try:
                    lib = n2lib[name]
                except KeyError:
                    log.debug(f'node {v} is not in any SBS')
                    self.lib_missing_sbs_sym.add(rxlcg_lib)
                    self.total_no_sbs_sym += 1
                    continue
                lib2reached[lib] += 1

        for lib in lib2totalsbssyms.keys():
            try:
                package = lib2pkg[lib]
            except Exception as e:
                log.debug(f'App {app}: Exception {e} when processing lib {lib}')
                continue
            total = lib2totalsbssyms[lib]
            # XXX: Silly defaultdict...
            if total == 0:
                continue
            reached = lib2reached[lib]
            size = lib2size[lib]
            # Two decimals
            # log.info(f'lib: {lib}, reached = {reached}, total = {total}')
            percent = round((reached / total), 4)
            # XXX: What percent of whole bincg does sbs reach?
            sbs_percent = round((total / lib2totalbcgsyms[lib]), 4)
            # XXX: Weigh it by the aforementioned percent
            reached_size = round(percent * sbs_percent * size)
            stats['all'][package][lib] = {'total_sbs_symbols': total,
                                   'total_bincg_symbols': lib2totalbcgsyms[lib],
                                   'reached_sbs_symbols': reached,
                                   'binary_size': size,
                                   'reached_percent': percent,
                                   'reached_size': reached_size,}
            if package in deps_direct:
                stats['direct'][package][lib] = {'total_sbs_symbols': total,
                                       'total_bincg_symbols': lib2totalbcgsyms[lib],
                                       'reached_sbs_symbols': reached,
                                       'binary_size': size,
                                       'reached_percent': percent,
                                       'reached_size': reached_size,}
            if package in deps_transitive:
                stats['transitive'][package][lib] = {'total_sbs_symbols': total,
                                       'total_bincg_symbols': lib2totalbcgsyms[lib],
                                       'reached_sbs_symbols': reached,
                                       'binary_size': size,
                                       'reached_percent': percent,
                                       'reached_size': reached_size,}

        for d in deps_all:
            name = d.split(':')[0]
            version = d.split(':')[1]
            appname = app.split(':')[0]
            appversion = app.split(':')[1]
            solo_dir_root = os.path.join(self.tmp_install_dir_toplevel_root, appname + '___' + appversion + '___TOPLEVEL')
            solo_dir = os.path.join(solo_dir_root, name + '___' + version)
            # log.info(f'solo_dir = {solo_dir}')
            if self.must_compute_python_sizes:
                total_size = get_py_files_size(solo_dir)
                self.python_sizes[solo_dir] = total_size
            else:
                # log.info(f"USING PRECOMPUTED PYTHON SIZE")
                try:
                    total_size = self.python_sizes[solo_dir]
                except KeyError as e:
                    log.debug(e)
                    continue
            log.debug(f'dep = {d}, total python size {total_size}')
            python_size_all += total_size
            if d in deps_direct:
                python_size_direct += total_size
            elif d in deps_transitive:
                python_size_transitive += total_size


        stats['reachable_python_packages'] = list(reachable_python_packages)
        stats['dependency_python_sizes'] = {'all': python_size_all, 'direct': python_size_direct, 'transitive': python_size_transitive}
        self.total_stats['data'][app] = stats

    def process(self):
        packages = utils.load_csv(self.input_file)

        self.packages = packages

        for p in self.packages:
            name = p.split(':')[0]
            version = p.split(':')[1]
            deps_dir = os.path.join(self.deps_dir_root, name[0], name, version)
            deps_all_path = os.path.join(deps_dir, 'deps.json')
            deps_direct_path = os.path.join(deps_dir, 'direct.json')

            with open(deps_all_path, 'r') as infile:
                deps_all = json.loads(infile.read())

            with open(deps_direct_path, 'r') as infile:
                deps_direct_raw = json.loads(infile.read())

            deps_direct = set()
            for dep_dict in deps_direct_raw:
                name = dep_dict['name']
                found = False
                for dd in deps_all:
                    if dd.split(':')[0] == name:
                        # version = dd.split(':')[1]
                        deps_direct.add(dd)
                        found = True
                if not found:
                    log.debug(f'Direct dep {name} of package {p} not found in all deps')

            self.app2alldeps[p] = deps_all
            self.app2directdeps[p] = list(deps_direct)

        # log.info(f'DEPS_ALL: {json.dumps(self.app2alldeps, indent=2)}')
        # log.info(f'DEPS_DIRECT: {json.dumps(self.app2directdeps, indent=2)}')


        for p in self.packages:
            name = p.split(':')[0]
            version = p.split(':')[1]
            reached_cg_path = os.path.join(self.reached_cg_root, name[0], name, version, 'reached.json')
            self.app2reachedcg[p] = reached_cg_path

            install_dir = os.path.join(self.tmp_install_dir_root, name + '___' + version)
            self.app2installdir[p] = install_dir

        for p in self.packages:
            self.do_one(p)

        self.total_stats['num_no_xlcg'] = len(self.total_stats['no_xlcg'])
        self.total_stats['num_no_dep_bin'] = len(self.total_stats['no_dep_bin'])
        # XXX: Deduct 2 for 'num_no_xlcg' and 'no_xlcg' and 'no_dep_bin' and 'num_no_dep_bin'
        self.total_stats['num_success'] = len(self.total_stats['data'])

        result = {'stats': {'num_success': self.total_stats['num_success'],
                            'num_no_xlcg': self.total_stats['num_no_xlcg'],
                            'num_no_dep_bin': self.total_stats['num_no_dep_bin'],
                            'no_xlcg': self.total_stats['no_xlcg'],
                            'no_dep_bin': self.total_stats['no_dep_bin']
                            },
                  'data': self.total_stats['data']
                  }


        log.debug(f'TOTAL_NAMES = {self.total_names}')
        log.debug(f'TOTAL_NO_SBS_SYM = {self.total_no_sbs_sym}')
        log.debug(f'LIBS_WITH_MISSING_SBS_SYMS = {json.dumps(list(self.lib_missing_sbs_sym), indent=2)}')

        log.debug(f'TOTAL_DEPS_DIRECT = {self.num_direct}')
        log.debug(f'TOTAL_DEPS_TRANSITIVE = {self.num_transitive}')

        if self.output_file is not None:
            with open(self.output_file, 'w') as outfile:
                outfile.write(json.dumps(self.total_stats, indent=2))
            log.info(f"Done. Wrote results to {self.output_file}.")
        else:
            log.info(json.dumps(self.total_stats, indent=2))

        if self.must_compute_python_sizes:
            with open(self.python_sizes_path, 'w') as outfile:
                outfile.write(json.dumps(self.python_sizes, indent=2))

        return 0

def main():
    args = parse_args()
    setup_logging(args)

    bloat = BloatCalculator(args.input, args.output)
    bloat.process()


if __name__ == "__main__":
    main()
