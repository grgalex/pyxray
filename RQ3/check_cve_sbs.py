import os
import sys
import json
import logging
import argparse
from collections import defaultdict

from packaging.version import Version

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
    return p.parse_args()

class SBSFinder():
    def __init__(self):
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")

        self.cves_all_file = os.path.join(self.git_root, 'data/cves.json')
        self.cves_post_sbs_file = os.path.join(self.git_root, 'data/cves_post_sbs.json')
        self.sbs_root = os.path.join(self.git_root, 'data/sbs')

        self.cves = {}
        self.cve_packages = set()

        self.cves_found_max_vuln = []
        self.cves_not_found_max_vuln = []
        self.cves_found_latest = []
        self.cves_not_found = []

        self.cves_failed_sbs_max_vuln = []
        self.cves_failed_sbs_latest = []

    def process(self):
        with open(self.cves_all_file, 'r') as infile:
            self.cves = json.loads(infile.read())
        # XXX: Max Vuln version
        for id, v in self.cves.copy().items():
            package = v['package']
            pkg_lower = package.lower()
            version = v['max_vuln_version']
            vuln_symbols = v['vuln_symbols']
            sbs_path_1 = os.path.join(self.sbs_root, package[0], package, version, 'sbs.json')
            sbs_path_2 = os.path.join(self.sbs_root, pkg_lower[0], pkg_lower, version, 'sbs.json')
            if not os.path.exists(sbs_path_1) and not os.path.exists(sbs_path_2):
                log.debug(f'CVE {id}: SBS does not exist at {sbs_path}')
                self.cves_failed_sbs_max_vuln.append(id)
                self.cves[id]['found_in_sbs_max_vuln'] = []
                continue

            if os.path.exists(sbs_path_1):
                sbs_path = sbs_path_1
            else:
                sbs_path = sbs_path_2

            with open(sbs_path, 'r') as infile:
                sbs = json.loads(infile.read())
            sbs_symbols = [node['name'] for node in sbs['nodes'].values()]
            found = set()
            for s in vuln_symbols:
                if s in sbs_symbols:
                    found.add(s)
            found = list(found)
            self.cves[id]['found_in_sbs_max_vuln'] = found
            if len(found) > 0:
                self.cves_found_max_vuln.append(id)
            else:
                self.cves_not_found_max_vuln.append(id)

        # XXX: Latest version
        for id, v in self.cves.copy().items():
            found_max_vuln = self.cves[id]['found_in_sbs_max_vuln']
            package = v['package']
            pkg_lower = package.lower()
            version = v['latest_version']
            if version is None:
                log.debug(f'CVE {id}: SBS does not exist at {sbs_path}')
                self.cves_failed_sbs_latest.append(id)
                continue
            vuln_symbols = v['vuln_symbols']
            sbs_path_1 = os.path.join(self.sbs_root, package[0], package, version, 'sbs.json')
            sbs_path_2 = os.path.join(self.sbs_root, pkg_lower[0], pkg_lower, version, 'sbs.json')
            if not os.path.exists(sbs_path_1) and not os.path.exists(sbs_path_2):
                log.debug(f'CVE {id}: SBS does not exist at {sbs_path}')
                self.cves_failed_sbs_latest.append(id)
                self.cves[id]['found_in_sbs_max_vuln'] = []
                continue

            if os.path.exists(sbs_path_1):
                sbs_path = sbs_path_1
            else:
                sbs_path = sbs_path_2

            # if len(found_max_vuln) > 0:
            #     continue

            with open(sbs_path, 'r') as infile:
                sbs = json.loads(infile.read())
            sbs_symbols = [node['name'] for node in sbs['nodes'].values()]

            found = set()
            for s in vuln_symbols:
                if s in sbs_symbols:
                    found.add(s)
            found = list(found)
            self.cves[id]['found_in_sbs_latest'] = found
            if len(found) > 0:
                self.cves_found_latest.append(id)
            else:
                self.cves_not_found.append(id)

        log.info(f'NUM_CVES_TOTAL: {len(self.cves)}')

        log.info(f'CVES_SYM_FOUND_MAX_VULN: {self.cves_found_max_vuln}')
        log.info(f'NUM_CVES_SYM_FOUND_MAX_VULN: {len(self.cves_found_max_vuln)}')

        # XXX: This applies only to those for whom not found in max vuln
        log.info(f'CVES_SYM_FOUND_LATEST: {self.cves_found_latest}')
        log.info(f'NUM_CVES_SYM_FOUND_LATEST: {len(self.cves_found_latest)}')

        log.info(f'CVES_SYM_NOT_FOUND: {self.cves_not_found}')
        log.info(f'NUM_CVES_SYM_NOT_FOUND: {len(self.cves_not_found)}')

        log.debug(f'CVES_SBS_NOEXIST_MAXVULN: {self.cves_failed_sbs_max_vuln}')
        log.debug(f'NUM_CVES_SBS_NOEXIST_MAXVULN: {len(self.cves_failed_sbs_max_vuln)}')

        # XXX: No SBS produced for latest version. This is bad.
        log.debug(f'CVES_SBS_NOEXIST_LATEST: {self.cves_failed_sbs_latest}')
        log.debug(f'NUM_CVES_SBS_NOEXIST_LATEST: {len(self.cves_failed_sbs_latest)}')

        with open(self.cves_post_sbs_file, 'w') as outfile:
            outfile.write(json.dumps(self.cves, indent=2))

def main():
    args = parse_args()
    setup_logging(args)

    sbsfinder = SBSFinder()
    sbsfinder.process()


if __name__ == "__main__":
    main()

