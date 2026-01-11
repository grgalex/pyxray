import os
import json
from collections import defaultdict

from packaging.version import Version

import concurrent.futures
from pathlib import Path

import utils
import logging
import argparse

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
        "-o",
        "--output",
        default=None,
        help=("Provide path to output JSON"),
    )
    return p.parse_args()

class CVEParser():
    def __init__(self, output_file):
        self.output_file = output_file
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")

        self.tmp_install_dir_root = os.path.join(self.git_root, 'data/cve_tempinst')
        utils.create_dir(self.tmp_install_dir_root)

        self.cve_dir = os.path.join(self.git_root, 'RQ3/cve')
        self.cves = {}
        self.cves_raw = []
        self.cve_packages = set()
        self.cves_all_file = os.path.join(self.git_root, 'data/cves.json')

    def get_latest_package_version(self, name):
        install_dir = self.install(name)
        if install_dir is None:
            log.debug(f'Failed to install latest version of {name}.')
            return None
        version = self.find_version(name, install_dir)
        if version is None:
            log.warn(f'Failed to use pipdeptree to find latest version of {name}.')
            return None
        return version

    def install(self, name):
        tmp_install_dir = os.path.join(self.tmp_install_dir_root, name)
        log.debug(f'Trying to install {name} in {tmp_install_dir}')

        if not os.path.exists(tmp_install_dir):
            cmd = [
                'pip3',
                'install',
                '-t', tmp_install_dir,
                "{}".format(name)
            ]
            try:
                ret, out, err = utils.run_cmd(cmd)
            except Exception as e:
                log.debug(e)
                return None
        else:
            log.info(f'Tmp install dir already exists... Skipping install')
            return tmp_install_dir


        if not os.path.exists(tmp_install_dir):
            log.debug(f'Failed to install package {name}, {out}, {err}')
            return None
        return tmp_install_dir

    def find_version(self,name, install_dir):
        log.info(f'Finding latest version for {name}')
        cmd = [
            'pipdeptree',
            '--path', install_dir,
            '--json'
        ]
        try:
            ret, out, err = utils.run_cmd(cmd)
        except Exception as e:
            log.debug(f'pipdeptree error {e} when processing {name} at {install_dir}')
            return None

        deps_raw = json.loads(out)
        for entry in deps_raw:
            p = entry['package']
            pname = p['package_name']
            version = p['installed_version']
            name = name.lower()
            pname = pname.lower()
            # XXX: Pillow -> pillow
            if pname == name:
                return version
        return None

    def load_cves(self):
        cve_files = [os.path.join(self.cve_dir, p) for p in os.listdir(self.cve_dir) if p.startswith('CVE') and p.endswith('.json')]
        log.info(f'cve_files = {cve_files}')

        for f in cve_files:
            with open(f, 'r') as infile:
                cve = json.loads(infile.read())
                self.cves_raw.append(cve)
        log.debug(json.dumps(self.cves, indent=2))


        for cve in self.cves_raw:
            # XXX: Each JSON contains a list with a single element
            cve = cve[0]
            log.info(cve)
            id = cve['cve_id']
            package = cve['package'].lower()
            # XXX: Again, the 'analysis' is a list with a single item, hence the 0
            vuln_symbols = cve['analysis'][0]['vulnerable_symbols']
            vuln_versions = cve['vulnerable_versions']
            max_vuln_version = sorted(vuln_versions, key=Version)[-1]
            latest_version = self.get_latest_package_version(package)

            log.info(f'CVE: {id}, package = {package}, vuln_symbols = {vuln_symbols}, max_vuln_version = {max_vuln_version}, latest_version = {latest_version}')

            self.cves[id] = {'package': package, 'vuln_symbols': vuln_symbols,
                             'vuln_versions': vuln_versions, 'max_vuln_version': max_vuln_version,
                             'latest_version': latest_version}

    def process(self):
        self.load_cves()

        for id, v in self.cves.items():
            package = v['package']
            max_vuln_version = v['max_vuln_version']
            latest_version = v['latest_version']
            pkgver = package + ':' + max_vuln_version
            self.cve_packages.add(pkgver)
            if latest_version is not None:
                pkgverlatest = package + ':' + latest_version
                self.cve_packages.add(pkgverlatest)

        if self.output_file is not None:
            with open(self.output_file, 'w') as outfile:
                for p in self.cve_packages:
                    outfile.write(f'{p}\n')
        else:
            log.info(json.dumps(list(self.cve_packages), indent=2))

        with open(self.cves_all_file, 'w') as outfile:
            outfile.write(json.dumps(self.cves, indent=2))

def main():
    args = parse_args()
    setup_logging(args)

    cveparser = CVEParser(args.output)
    cveparser.process()


if __name__ == "__main__":
    main()

