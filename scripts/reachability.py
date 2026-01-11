import os
import sys
import json
import logging
import argparse

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
        "-G",
        "--github",
        default=False,
        action='store_true',
        help=("Process github apps"),
    )
    p.add_argument(
        "-P",
        "--pypi",
        default=False,
        action='store_true',
        help=("Process PyPI packages"),
    )
    p.add_argument(
        "-A",
        "--always",
        default=False,
        action='store_true',
        help=("Always process callgraphs."),
    )
    return p.parse_args()

class FullReachability_G():
    def __init__(self, always):
        self.always = always
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")
        self.unified_cg_root = os.path.join(self.git_root, 'data/unified_cg/apps')
        self.reached_cg_root = os.path.join(self.git_root, 'data/reached_cg/apps')

        self.cg_paths = []
        self.cg2out = {}
        self.cg2pkg = {}

    def find_callgraphs(self):
        self.cg_paths = [str(path) for path in Path(self.unified_cg_root).rglob("*")
                         if path.is_file()
                         and path.name == 'unified.json']
        for inpath in self.cg_paths:
            namesnip = os.path.relpath(os.path.dirname(inpath), start=self.unified_cg_root)
            outpath = os.path.join(self.reached_cg_root, namesnip, 'reached.json')
            self.cg2out[inpath] = outpath
            user = namesnip.split('/')[0]
            repo = namesnip.split('/')[1]
            self.cg2pkg[inpath] = user + '/' + repo

    def process(self):
        self.find_callgraphs()
        log.info(self.cg_paths)
        log.info(f'len(cg_paths) = {len(self.cg_paths)}')
        if len(self.cg_paths) != len(set(self.cg_paths)):
            log.error('CG_PATHS CONTAIN DUPLICATES')

        for cg in self.cg_paths:
            if os.path.exists(self.cg2out[cg]) and not self.always:
                log.info(f'Reached cg for {self.cg2pkg[cg]} already exists at {self.cg2out[cg]}. Use -A to force rerun')
            else:
                utils.create_dir(os.path.dirname(self.cg2out[cg]))
                do_single(self.cg2pkg[cg], cg, self.cg2out[cg])


class FullReachability_P():
    def __init__(self, always):
        self.always = always
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")
        self.unified_cg_root = os.path.join(self.git_root, 'data/unified_cg/pypi')
        self.reached_cg_root = os.path.join(self.git_root, 'data/reached_cg/pypi')
        self.cg_paths = []
        self.cg2out = {}
        self.cg2pkg = {}

    def find_callgraphs(self):
        self.cg_paths = [str(path) for path in Path(self.unified_cg_root).rglob("*")
                         if path.is_file()
                         and path.name == 'unified.json'
                         and '/apps/' not in str(path)]

        for inpath in self.cg_paths:
            namesnip = os.path.relpath(os.path.dirname(inpath), start=self.unified_cg_root)
            outpath = os.path.join(self.reached_cg_root, namesnip, 'reached.json')
            self.cg2out[inpath] = outpath
            name = namesnip.split('/')[1]
            version = namesnip.split('/')[2]
            self.cg2pkg[inpath] = name + ':' + version

    def process(self):
        self.find_callgraphs()
        log.info(self.cg_paths)
        log.info(f'len(cg_paths) = {len(self.cg_paths)}')
        if len(self.cg_paths) != len(set(self.cg_paths)):
            log.error('CG_PATHS CONTAIN DUPLICATES')

        for cg in self.cg_paths:
            utils.create_dir(os.path.dirname(self.cg2out[cg]))
            do_single(self.cg2pkg[cg], cg, self.cg2out[cg])

def do_single(package, inpath, outpath):
    log.info(f'do_single({package}, {inpath}, {outpath})')
    reacher = reach_sane.ReachabilityDetector(package, inpath, outpath, False)
    reacher.reach()

def main():
    args = parse_args()
    setup_logging(args)

    if not args.pypi and not args.github:
        log.error(f"Must provide one of '-G', '-P' arguments")
        sys.exit(1)
    if args.pypi:
        fr = FullReachability_P(args.always)
    elif args.github:
        fr = FullReachability_G(args.always)

    fr.process()

if __name__ == "__main__":
    main()

