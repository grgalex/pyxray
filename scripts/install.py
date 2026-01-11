#!/usr/bin/env python3
import os
import sys
import argparse
import logging
import shutil
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
            f"log level given: {args.log} -- must be one of: {' | '.join(levels.keys())}"
        )

    fmt = "%(asctime)s %(module)s:%(lineno)s [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)

def parse_args():
    p = argparse.ArgumentParser(description="Install packages (and optionally their pinned deps) into a target directory.")
    p.add_argument(
        "-l",
        "--log",
        default="info",
        help="Logging level: critical|error|warning|info|debug",
    )
    p.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to CSV containing package:version entries (one per line or CSV column as used by utils.load_csv).",
    )
    p.add_argument(
        "-A",
        "--always",
        default=False,
        action="store_true",
        help="Always reinstall. If unset, reuse existing install directories when present.",
    )
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=10,
        help="Parallel workers.",
    )
    return p.parse_args()

class Installer:
    def __init__(self, package: str, always: bool):
        self.package = package  # "name:version"
        self.always = always

        self.name = package.split(":")[0]
        self.version = package.split(":")[1]

        self.git_root = utils.find_git_root()
        if self.git_root is None:
            raise RuntimeError("CWD is outside the Xray git repo")

        self.tempinst_uuid = self.name + "___" + self.version
        self.tmp_install_dir_root = os.path.join(self.git_root, "data/install")
        self.tmp_install_dir = os.path.join(self.tmp_install_dir_root, self.tempinst_uuid)

        self.deps_dir_root = os.path.join(self.git_root, "data/dependencies")
        self.namesnip = self.name[0] + "/" + self.name + "/" + self.version
        self.deps_dir = os.path.join(self.deps_dir_root, self.namesnip)
        self.deps_path = os.path.join(self.deps_dir, "deps.json")
        self.deps = []

    def load_dependencies(self) -> int:
        log.info(f"Loading dependencies of {self.package} from {self.deps_path}")
        try:
            with open(self.deps_path, "r") as infile:
                self.deps = utils.json_load(infile) if hasattr(utils, "json_load") else __import__("json").load(infile)
        except Exception as e:
            log.error(f"Failed to load deps for {self.package}: {e}")
            return -1
        return 0

    def install_packages(self) -> int:
        log.info(f"Installing {self.package} and deps into {self.tmp_install_dir}")

        if os.path.exists(self.tmp_install_dir) and not self.always:
            log.info(f"Install dir exists, skipping: {self.tmp_install_dir} (use -A to force)")
            return 0

        # Force reinstall: remove old dir if present
        if os.path.exists(self.tmp_install_dir) and self.always:
            shutil.rmtree(self.tmp_install_dir, ignore_errors=True)

        utils.create_dir(self.tmp_install_dir)

        all_packages = [self.package] + self.deps
        for dep in all_packages:
            (pkg, version) = utils.pkg_name_to_tuple(dep)
            cmd = [
                "pip3",
                "install",
                "-t",
                self.tmp_install_dir,
                "--no-deps",
                "--no-binary",
                "Pillow",
                f"{pkg}=={version}",
            ]
            log.info(f"Running: {cmd}")
            try:
                ret, out, err = utils.run_cmd(cmd)
            except Exception as e:
                log.error(f"Failed to run {cmd}: {e}")
                return -1

            if ret != 0:
                log.error(f"pip failed for {dep} (exit {ret})")
                if out:
                    log.info(out)
                if err:
                    log.info(err)
                # keep directory for debugging unless you want to clean up:
                # shutil.rmtree(self.tmp_install_dir, ignore_errors=True)
                return ret

        return 0

    def process(self) -> int:
        ret = self.load_dependencies()
        if ret != 0:
            return ret
        return self.install_packages()

def do_single(pkg: str, always: bool) -> int:
    try:
        inst = Installer(pkg, always)
        return inst.process()
    except Exception as e:
        log.error(f"Failed processing {pkg}: {e}")
        return -1

def main():
    args = parse_args()
    setup_logging(args)

    package_names = utils.load_csv(args.input)
    log.info(f"Loaded {len(package_names)} packages")

    failures = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(do_single, pkg, args.always) for pkg in package_names]
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            if r != 0:
                failures += 1

    if failures:
        log.error(f"Done with failures: {failures}")
        sys.exit(1)

    log.info("Done")
    sys.exit(0)

if __name__ == "__main__":
    main()

