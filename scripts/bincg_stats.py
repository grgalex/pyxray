import os
import sys
import json
import logging
import argparse
from collections import defaultdict

import concurrent.futures
from pathlib import Path

import utils
import reach_sane

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
        "-A",
        "--always",
        default=False,
        action='store_true',
        help=("Always process callgraphs."),
    )
    return p.parse_args()

class BinaryStats():
    def __init__(self):
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")

        self.bcg_root = os.path.join(self.git_root, 'data/binary_callgraphs')
        self.bcgs_per_package = defaultdict(list)
        self.stats = defaultdict(dict)


    def find_package_bincg_roots(self):
        root_dir = Path(self.bcg_root)
        all_paths = [str(path) for path in root_dir.rglob("*") if path.is_file() and path.name.endswith('.json') and not path.name == 'stats.json']

        all_paths_rel = [os.path.relpath(p, start=self.bcg_root) for p in all_paths]
        for p in all_paths_rel:
            parts = p.split('/')
            name = parts[1]
            version = parts[2]
            pkgver = name + ':' + version
            lib = os.path.relpath(os.path.join(self.bcg_root, p), start=os.path.join(self.bcg_root, name[0], name, version))
            self.bcgs_per_package[pkgver].append(lib)
        return 0


    def calculate_stats(self):
        for pkg, bcg_relpaths in self.bcgs_per_package.items():
            for b in bcg_relpaths:
                try:
                    lib = b.removesuffix('.json')
                    name = pkg.split(':')[0]
                    version = pkg.split(':')[1]
                    bcg_path = os.path.join(self.bcg_root, name[0], name, version, b)
                    with open(bcg_path, 'r') as infile:
                        bcg = json.loads(infile.read())
                        num_syms = len(bcg['nodes'].keys())
                    self.stats[pkg][lib] = {'num_syms': num_syms}
                except Exception as e:
                    log.error(f'Exception {e} when processing {bcg_path}')
        return 0

    def process(self):
        ret = self.find_package_bincg_roots()
        if ret != 0:
            return ret

        ret = self.calculate_stats()
        if ret != 0:
            return ret

        for p, st in self.stats.items():
            name = p.split(':')[0]
            version = p.split(':')[1]
            stats_path = os.path.join(self.bcg_root, name[0], name, version, 'stats.json')
            with open(stats_path, 'w') as outfile:
                outfile.write(json.dumps(st, indent=2))

        # log.info(json.dumps(self.stats, indent=2))


def do_single(package, inpath, outpath):
    log.info(f'do_single({package}, {inpath}, {outpath})')
    reacher = reach_sane.ReachabilityDetector(package, inpath, outpath, False)
    reacher.reach()

def main():
    args = parse_args()
    setup_logging(args)

    bs = BinaryStats()
    bs.process()


if __name__ == "__main__":
    main()


