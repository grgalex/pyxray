import os
import sys
import json
import logging
import argparse
from collections import defaultdict
from packaging.version import Version
from packaging.specifiers import SpecifierSet
from pypi_simple import PyPISimple

import utils
import call_chain

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
    p = argparse.ArgumentParser(description='Find transitive vulnerable apps for each CVE')
    p.add_argument(
        "-l",
        "--log",
        default="info",
        help=("Provide logging level. Example --log debug"),
    )
    p.add_argument(
        "-a",
        "--apps",
        default=None,
        required=True,
        help=("Provide path to the JSON containing post-sbs cve info"),
    )
    p.add_argument(
        "-c",
        "--cves",
        default=None,
        required=True,
        help=("Provide path to the JSON containing post-sbs cve info"),
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help=("Provide path to output JSON"),
    )
    return p.parse_args()

def get_compatible_versions(package, constraints):
    """
    Fetches all available versions of a package from PyPI
    and filters them based on the given version constraints.

    Args:
        package (str): Package name (e.g., "numpy").
        constraints (str): Version constraints (e.g., ">=1.20,<1.26").

    Returns:
        List[str]: Sorted compatible versions (highest first).
    """
    client = PyPISimple()
    try:
        # Fetch the package info from PyPI
        project_page = client.get_project_page(package)
        all_versions = {pkg.version for pkg in project_page.packages}
    except Exception as e:
        print(f"Error fetching versions for {package}: {e}")
        return []

    try:
        # Parse version constraints
        specifier = SpecifierSet(constraints)
    except Exception as e:
        print(f"Invalid version constraint '{constraints}': {e}")
        return []

    # Filter versions that match the constraints
    compat_versions = []
    for v in all_versions:
        try:
            if Version(v) in specifier:
                compat_versions.append(v)
        except Exception as e:
            log.debug(e)
            continue
    compatible_versions = sorted(
        compat_versions,
        key=Version,
        reverse=True
    )

    return compatible_versions


def find_call_chains(reached_cg_path, symbol):
    chain_calc = call_chain.ChainCalculator(reached_cg_path, symbol)
    return (chain_calc.process(), chain_calc.centrality)

class VulnFinder():
    def __init__(self, apps_file, cves_file, output_file):
        self.apps_file = apps_file
        self.cves_file = cves_file
        self.output_file = output_file
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")

        self.deps_dir_root = os.path.join(self.git_root, 'data/dependencies')
        self.reached_cg_root = os.path.join(self.git_root, 'data/reached_cg/pypi')
        self.pkg2rdeps_path = os.path.join(self.git_root, 'data/pkg2rdeps.json')
        self.dependency_patches_path = os.path.join(self.git_root, 'data/dependencies/cve_patches.json')

        self.app2reachedcg = {}
        self.cves = None

        self.no_reached_cg_apps = set()

        self.apps = None
        self.pkg2rdeps = defaultdict(set)
        self.final_stats = []


        self.dependency_patches = defaultdict(list)

    def load_cve_stats(self):
        with open(self.cves_file, 'r') as infile:
            self.cves = json.loads(infile.read())

    def populate_rdeps(self):
        apps = utils.load_csv(self.apps_file)

        self.apps = apps

        n = len(self.apps)
        i = 0

        if os.path.exists(self.pkg2rdeps_path):
            with open(self.pkg2rdeps_path, 'r') as infile:
                self.pkg2rdeps = json.loads(infile.read())
        else:
            for p in self.apps:
                log.info(p)
                log.info(f"{i} / {n} apps")
                i += 1

                name = p.split(':')[0]
                version = p.split(':')[1]
                deps_dir = os.path.join(self.deps_dir_root, name[0], name, version)
                deps_direct_path = os.path.join(deps_dir, 'direct.json')

                with open(deps_direct_path, 'r') as infile:
                    deps_direct_raw = json.loads(infile.read())

                deps_direct = set()
                for dep_dict in deps_direct_raw:
                    name = dep_dict['name']
                    name = name.lower()

                    constraints = dep_dict['required_version']
                    # XXX: https://packaging.pypa.io/en/stable/specifiers.html
                    #      'Any' from pipdeptree is semantically equivalent to ''
                    if constraints == 'Any':
                        constraints = ''

                    # log.info(f'package = {p}, dep = {name}, constraints = {constraints}')

                    # XXX: Add all possible candidates for a direct dep
                    #      to the rdeps dict.
                    #      This way, we can check if an app can potentially
                    #      depend on a vuln. version of a package.
                    candidates = get_compatible_versions(name, constraints)
                    for c in candidates:
                        namever = name + ':' + c
                        self.pkg2rdeps[namever].add(p)

            self.pkg2rdeps = {key: list(value) for key, value in self.pkg2rdeps.items()}


            with open(self.pkg2rdeps_path, 'w') as outfile:
                outfile.write(json.dumps(self.pkg2rdeps, indent=2))
            log.info(f'Wrote pkg2rdeps to {self.pkg2rdeps_path}')


        for p in self.apps:
            name = p.split(':')[0]
            version = p.split(':')[1]
            reached_cg_path = os.path.join(self.reached_cg_root, name[0], name, version, 'reached.json')
            self.app2reachedcg[p] = reached_cg_path

    def do_one(self, cve_id, stats):
        log.info(f'Processing {cve_id}')
        name = stats['package']
        name = name.lower()
        vuln_versions = stats['vuln_versions']
        vuln_symbols = stats['vuln_symbols']
        max_vuln_version = stats['max_vuln_version']

        transitively_vulnerable_packages = set()
        total_rdeps = set()
        sample_chains = defaultdict(dict)
        num_chains_per_rdep = defaultdict(int)
        centrality_per_rdep = defaultdict(int)

        for vuln_version in vuln_versions:
            pkgver = name + ':' + vuln_version
            if not pkgver in self.pkg2rdeps.keys():
                continue
            rdependents = self.pkg2rdeps[pkgver]
            log.debug(f'vuln_version = {vuln_version}, pkgver = {pkgver}, rdependents = {rdependents}')
            for rdep in rdependents:
                total_rdeps.add(rdep)
                all_chains = []
                reached_cg_path = self.app2reachedcg[rdep]
                if not os.path.exists(reached_cg_path):
                    if rdep not in self.no_reached_cg_apps:
                        log.debug(f'No reached CG found for {rdep} at {reached_cg_path}. Skipping')
                        self.no_reached_cg_apps.add(rdep)
                    continue
                for sym in vuln_symbols:
                    (chains, centr) = find_call_chains(reached_cg_path, sym)
                    if len(chains) > 0:
                        sample_chains[rdep][sym] = chains[0]
                        if centr > centrality_per_rdep[rdep]:
                            centrality_per_rdep[rdep] = centr
                    all_chains += chains
                if len(all_chains) > 0:
                    transitively_vulnerable_packages.add(rdep)
                    num_chains_per_rdep[rdep] = len(all_chains)

        # XXX: Generate dep patches.
        for rdep in total_rdeps:
            self.dependency_patches[rdep].append(name + ':' + max_vuln_version)

        results = {'id': cve_id,
                   'stats': stats,
                   'transitively_vulnerable_packages': list(transitively_vulnerable_packages),
                   'num_vuln': len(transitively_vulnerable_packages),
                   'num_rdeps': len(total_rdeps),
                   'sample_chains': sample_chains,
                   'num_chains_per_rdep': num_chains_per_rdep,
                   'centrality_per_rdep': centrality_per_rdep,
                   }
        log.info(f'RESULTS: {json.dumps(results, indent=2)}')
        self.final_stats.append(results)

    def process(self):
        self.load_cve_stats()
        self.populate_rdeps()

        for id, stats in self.cves.items():
            self.do_one(id, stats)

        if self.output_file is not None:
            with open(self.output_file, 'w') as outfile:
                outfile.write(json.dumps(self.final_stats, indent=2))
        else:
            log.info(json.dumps(self.final_stats, indent=2))

        with open(self.dependency_patches_path, 'w') as outfile:
            outfile.write(json.dumps(self.dependency_patches, indent=2))

        return 0

def main():
    args = parse_args()
    setup_logging(args)

    vf = VulnFinder(args.apps, args.cves, args.output)
    vf.process()


if __name__ == "__main__":
    main()

