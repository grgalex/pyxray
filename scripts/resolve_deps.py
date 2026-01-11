import os
import sys
import json
import argparse
import logging
import concurrent.futures

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
    p.add_argument(
        "-A",
        "--always",
        default=False,
        action='store_true',
        help=("Always generate artifacts, never reuse existing stuff."),
    )
    return p.parse_args()



class DependencyResolver():
    def __init__(self, package, always):
        self.package = package
        self.always = always
        if ':' not in self.package:
            err = (f'Unrecognized package format: {package}')
            raise ValueError(err)
        self.name = self.package.split(':')[0]
        self.version = self.package.split(':')[1]
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")

        self.tmp_install_dir_root = os.path.join(self.git_root, 'data/install')
        self.tmp_install_dir = os.path.join(self.tmp_install_dir_root, self.name[0], self.name, self.version)

        self.deps_dir_root = os.path.join(self.git_root, 'data/dependencies')
        self.deps_dir = os.path.join(self.deps_dir_root, self.name[0], self.name, self.version)
        self.deps_all_path = os.path.join(self.deps_dir, 'deps.json')
        self.deps_direct_path = os.path.join(self.deps_dir, 'direct.json')

        self.deps_direct = {}
        self.deps_all = []


    def install(self):
        log.info(f'Installing package {self.package} and its deps in {self.tmp_install_dir}')

        if not os.path.exists(self.tmp_install_dir) or self.always:
            cmd = [
                'pip3',
                'install',
                '-t', self.tmp_install_dir,
                '--ignore-installed',
                '--upgrade',
                '--force-reinstall',
                "{}=={}".format(self.name, self.version)
            ]
            try:
                ret, out, err = utils.run_cmd(cmd)
            except Exception as e:
                log.error(e)
                return -1
        else:
            log.info(f'Tmp install dir already exists... Skipping install')
        return 0

    def resolve_deps(self):
        log.info(f'Resolving dependencies for {self.package}')
        cmd = [
            'pipdeptree',
            '--path', self.tmp_install_dir,
            '--json'
        ]
        try:
            ret, out, err = utils.run_cmd(cmd)
        except Exception as e:
            log.error(e)
            log.error('bad')
            return -1

        deps_raw = json.loads(out)
        deps_direct = {}
        deps_all = set()
        for entry in deps_raw:
            p = entry['package']
            dependencies = entry['dependencies']
            if p['package_name'] == self.name and p['installed_version'] == self.version:
                deps_direct = [{'name': d['package_name'], 'required_version': d['required_version']} for d in dependencies]
        for entry in deps_raw:
            p = entry['package']
            name = p['package_name']
            if name == self.name:
                continue
            version = p['installed_version']
            pkgver = name + ':' + version
            deps_all.add(pkgver)

        self.deps_all = list(deps_all)
        self.deps_direct = deps_direct
        log.info('OK')
        return 0

    def save_deps(self):
        utils.create_dir(self.deps_dir)
        with open(self.deps_direct_path, 'w') as outfile:
            outfile.write(json.dumps(self.deps_direct, indent=2))

        log.info(f'Wrote direct deps to {self.deps_direct_path}')

        with open(self.deps_all_path, 'w') as outfile:
            outfile.write(json.dumps(self.deps_all, indent=2))

        log.info(f'Wrote all deps to {self.deps_all_path}')

    def process(self):
        ret = self.install()
        if ret != 0:
            return ret

        if os.path.exists(self.deps_direct_path) and os.path.exists(self.deps_all_path) and not self.always:
            return 0

        ret = self.resolve_deps()
        if ret != 0:
            return ret

        ret = self.save_deps()
        if ret != 0:
            return ret


def do_single(package, always):
    depresolver = DependencyResolver(package, always)
    depresolver.process()

def main():
    args = parse_args()
    setup_logging(args)

    if args.input is None:
        log.error("Must provide input CSV file")
        sys.exit(1)

    packages = utils.load_csv(args.input)
    log.info(f"packages = {packages}")


    for pkg in packages:
        do_single(pkg, args.always)

if __name__ == "__main__":
    main()

