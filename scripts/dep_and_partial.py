import os
import sys
import json
import argparse
import logging
import concurrent.futures

import utils
import resolve_deps
import produce_partial_cg

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

def single_resolve_deps(package, always):
    depresolver = resolve_deps.DependencyResolver(package, always)
    depresolver.process()

def single_partial_cg(package, always, is_app):
    pcg_producer = produce_partial_cg.PartialCallgraphGenerator(package, always, is_app)
    pcg_producer.process()

def main():
    args = parse_args()
    setup_logging(args)

    if args.input is None:
        log.error("Must provide input CSV file")
        sys.exit(1)

    packages = utils.load_csv(args.input)

    git_root = utils.find_git_root()
    deps_dir_root = os.path.join(git_root, 'data/dependencies')


    with concurrent.futures.ProcessPoolExecutor(max_workers=10) as executor:
        for pkg in packages:
            executor.submit(single_resolve_deps, pkg, args.always)

    # for pkg in packages:
    #     single_resolve_deps(pkg, args.always)

    union_deps = set()
    for pkg in packages:
        name = pkg.split(':')[0]
        version = pkg.split(':')[1]
        dfp = os.path.join(deps_dir_root, name[0], name, version, 'deps.json')
        with open(dfp, 'r') as infile:
            deps = json.loads(infile.read())
            for dep in deps:
                union_deps.add(dep)

    with concurrent.futures.ProcessPoolExecutor(max_workers=10) as executor:
        for pkg in packages:
            executor.submit(single_partial_cg, pkg, args.always, True)

        for pkg in union_deps:
            executor.submit(single_partial_cg, pkg, args.always, False)


if __name__ == "__main__":
    main()



