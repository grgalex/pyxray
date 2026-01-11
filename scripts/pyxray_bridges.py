import os
import sys
import json
import argparse
import logging
from pathlib import Path
import shutil
from multiprocessing import cpu_count, Pool
import concurrent.futures
import tempfile

import starbinstitch
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
    p = argparse.ArgumentParser(description='Produce SBS for a CSV containing package:version pairs (from PyPI).')
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
        help=("Provide path to the CSV containing the package:version pairs"),
    )
    p.add_argument(
        "-A",
        "--always",
        default=False,
        action='store_true',
        help=("Always generate artifacts, never reuse existing stuff."),
    )
    return p.parse_args()

class FullSBS():
    def __init__(self, package, version, always):
        self.always = always
        self.package = package
        self.version = version
        self.git_root = utils.find_git_root()
        self.namesnip = package[0] + '/' + package + '/' + version
        self.tmp_install_dir_root = os.path.join(self.git_root, 'data/install')
        self.tempinst_uuid = package + '___' + version
        self.tmp_install_dir = os.path.join(self.tmp_install_dir_root, self.tempinst_uuid)
        self.tmp_install_dir_toplevel = os.path.join(self.tmp_install_dir_root, self.tempinst_uuid + '___TOPLEVEL')
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")
        self.sb_root = os.path.join(self.git_root, 'data/star_bridges')
        self.sb_dir = os.path.join(self.sb_root, self.namesnip)
        self.sb_path = os.path.join(self.sb_dir, 'starbridges.json')

        self.top_levels = None
        self.naked = None
        self.first_comps = None

    def find_toplevels(self):
        log.info(f"Finding top_level import names for {self.package}:{self.version}")
        if os.path.exists(self.tmp_install_dir_toplevel) and not self.always:
            log.info(f"Temp TOPLEVEL install dir for {self.package}:{self.version} already exists at {self.tmp_install_dir_toplevel} - Skipping...")
            log.info(f"Use -A to force recreation.")
        else:
            try:
                utils.create_dir(self.tmp_install_dir_toplevel)
            except FileExistsError as e:
                log.warning(e)
            cmd = [
                'pip3',
                'install',
                '-t', self.tmp_install_dir_toplevel,
                '--no-build-isolation',
                '--no-deps',
                "{}=={}".format(self.package, self.version)
            ]
            try:
                ret, out, err = utils.run_cmd(cmd)
            except Exception as e:
                log.error(e)
                raise
            if ret != 0:
                log.error(f"cmd {cmd} returned non-zero exit code {ret}")
                log.debug(out)
                log.debug(err)
                if os.path.exists(self.tmp_install_dir_toplevel):
                    shutil.rmtree(self.tmp_install_dir_toplevel)
                return ret

        root_path = Path(self.tmp_install_dir_toplevel)
        top_levels = [
            os.path.basename(str(subdir)) for subdir in root_path.iterdir()
            if subdir.is_dir() and (subdir / '__init__.py').exists()
        ]
        first_comps = [
            os.path.basename(str(subdir)) for subdir in root_path.iterdir()
        ]
        self.first_comps = first_comps
        log.debug(f'FIRST_COMPS = {self.first_comps}')
        if len(top_levels) > 0:
            self.top_levels = [os.path.join(self.tmp_install_dir, tl) for tl in top_levels]
        # naked = [item for item in os.listdir(self.tmp_install_dir_toplevel) if item.endswith('.py') or item.endswith('.so')]
        naked = [item for item in os.listdir(self.tmp_install_dir_toplevel) if item.endswith('.so')]
        if len(naked) > 0:
            self.naked = [os.path.join(self.tmp_install_dir, n) for n in naked]
        log.debug(f"top_levels for {self.package}:{self.version} are {self.top_levels}")
        log.debug(f"naked modules for {self.package}:{self.version} are {self.naked}")


        return 0

    def install_package(self):
        log.info(f"Installing package {self.package}:{self.version} and deps in {self.tmp_install_dir}")
        if os.path.exists(self.tmp_install_dir) and not self.always:
            log.info(f"Temp install dir for {self.package}:{self.version} already exists at {self.tmp_install_dir} - Skipping...")
            log.info(f"Use -A to force recreation.")
            return 0
        else:
            try:
                utils.create_dir(self.tmp_install_dir)
            except FileExistsError as e:
                log.warning(e)
            cmd = [
                'pip3',
                'install',
                '-t', self.tmp_install_dir,
                '--no-binary', 'Pillow',
                '--upgrade', '--force-reinstall',
                "{}=={}".format(self.package, self.version)
            ]
            try:
                ret, out, err = utils.run_cmd(cmd)
            except Exception as e:
                log.error(e)
                raise
            # log.info(out)
            # log.info(err)

            if ret != 0:
                log.error(f"cmd {cmd} returned non-zero exit code {ret}")
                log.info(out)
                log.info(err)
                if os.path.exists(self.tmp_install_dir):
                    shutil.rmtree(self.tmp_install_dir)
                return ret

            return 0

    def generate_starbridges(self):
        log.info(f"Generating starbridges for {self.package}:{self.version}")
        if os.path.exists(self.sb_path) and not self.always:
            log.info(f"Bridges file for {self.package}:{self.version} already exists at {self.sb_path} - Skipping...")
            log.info(f"Use -A to force recreation.")
        else:
            try:
                utils.create_dir(self.sb_dir)
            except FileExistsError as e:
                log.warning(e)
            cmd = [
                'python3',
                os.path.join(self.git_root, 'scripts/analyze_separate_so.py'),
                '-o', self.sb_path,
                '-s', self.tmp_install_dir,
            ]

            if self.top_levels is not None:
                cmd.append('-p')
                for tl in self.top_levels:
                    cmd.append(tl)
            # else:
            #     # XXX: This means that the package comprises a naked .so native extension without python entry points
            #     cmd.append(self.tmp_install_dir)
            if self.naked is not None:
                cmd.append('-n')
                for n in self.naked:
                    cmd.append(n)
            # log.info(cmd)
            try:
                ret, out, err = utils.run_cmd(cmd, timeout=None)
            except Exception as e:
                log.error(e)
                raise

            log.info(out)
            log.info(err)

            if ret != 0:
                log.error(f"cmd {cmd} returned non-zero exit code {ret}")
                log.debug(out)
                log.debug(err)
                return ret

        return 0

    def process(self):
        log.info(f"Processing package: {self.package}:{self.version}")

        ret = self.find_toplevels()
        if ret != 0:
            return ret

        ret = self.install_package()
        if ret != 0:
            return ret

        ret = self.generate_starbridges()
        if ret != 0:
            return ret

        return ret

def do_single(p, always):
    # log.info(f"Processing package {p}")
    (name,version) = utils.pkg_name_to_tuple(p)
    fullsbs = FullSBS(name, version, always)
    fullsbs.process()

def main():
    args = parse_args()
    setup_logging(args)

    if args.input is None:
        log.error("Must provide input CSV file")
        sys.exit(1)

    package_names = utils.load_csv(args.input)
    # log.info(f"package_names = {package_names}")

    # with concurrent.futures.ProcessPoolExecutor(max_workers=6) as executor:
    #     for pkg in package_names:
    #         executor.submit(do_single, pkg, args.always)

    for pkg in package_names:
        do_single(pkg, args.always)
if __name__ == "__main__":
    main()
