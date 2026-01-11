import os
import sys
import json
import logging
import argparse
from collections import defaultdict

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
        "-s",
        "--stats",
        default=None,
        required=True,
        help=("Provide path to the JSON CVE stats for a given dataset."),
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help=("Provide path to output JSON"),
    )
    return p.parse_args()

def find_call_chains(reached_cg_path, symbol):
    chain_calc = call_chain.ChainCalculator(reached_cg_path, symbol)
    return (chain_calc.process(), chain_calc.centrality)

class CveFinalStats():
    def __init__(self, stats_file, output_file):
        self.stats_file = stats_file
        self.output_file = output_file
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")

        self.reached_cg_root = os.path.join(self.git_root, 'data/reached_cg/pypi')
        self.sbs_root = os.path.join(self.git_root, 'data/sbs')


        self.cve_stats = None
        self.final_stats = []

        self.not_visible = []
        self.visible = []
        self.failed = {}

        self.avg_client_centrality = {}
        self.package_centrality = {}

    def load_cve_stats(self):
        with open(self.stats_file, 'r') as infile:
            self.cve_stats = json.loads(infile.read())

    def decide_visible(self):
        for cve in self.cve_stats:
            stats = cve['stats']
            if stats['latest_version'] is None:
                self.failed[cve['id']] = 'FAILED_INSTALL_LATEST'
                continue
            if stats['latest_version'] is not None and 'found_in_sbs_latest' not in stats.keys():
                self.failed[cve['id']] = 'FAILED_COMPUTE_SBS_LATEST'
                continue
            if (len(stats['found_in_sbs_max_vuln']) > 0) or (len(stats['found_in_sbs_latest']) > 0):
                self.visible.append(cve['id'])
            else:
                self.not_visible.append(cve['id'])


    def compute_client_centrality(self):
        for cve in self.cve_stats:
            if cve['id'] in self.failed:
                continue
            cprs = cve['centrality_per_rdep']
            if len(cprs) == 0:
                average_centrality = 'N/A'
            else:
                sum = 0
                num_rdeps = len(cprs)
                for rdep, centrality in cprs.items():
                    sum += centrality
                average_centrality = round(100 * sum / num_rdeps, 2)
            self.avg_client_centrality[cve['id']] = average_centrality

    def compute_package_centrality(self):
        for cve in self.cve_stats:
            if cve['id'] in self.failed:
                continue
            stats = cve['stats']
            log.info(cve)
            package = stats['package']
            version = stats['latest_version']
            pkgver = package + ':' + version
            sbs_path = os.path.join(self.sbs_root, package[0], package, version, 'sbs.json')

            centrality = 0
            for sym in stats['found_in_sbs_latest']:
                (chains, centr) = find_call_chains(sbs_path, sym)
                if centr > centrality:
                    centrality = centr
            # XXX: Convert to percentage
            centrality = round(100 * centrality, 2)
            if centrality == 0:
                centrality = 'N/A'
            self.package_centrality[cve['id']] = centrality

    def compute_final_stats(self):
        total_cnt = len(self.failed) + len(self.visible) + len(self.not_visible)
        if total_cnt != len(self.cve_stats):
            log.warn(f'TOTAL CVES: {len(self.cve_stats)}, FAILED: {len(self.failed)}, VISIBLE: {len(self.visible)}, NOT_VISIBLE: {len(self.not_visible)}')
        for cve in self.cve_stats:
            id = cve['id']
            package = cve['stats']['package']
            vuln_symbols = cve['stats']['vuln_symbols']
            if id in self.failed.keys():
                status = self.failed[id]
                stat = {'id': id,
                        'status': status,
                        'package': package,
                        'vulnerable_symbols': vuln_symbols}
            else:
                if id in self.not_visible:
                    status = 'SYM_NOT_VISIBLE'
                elif id in self.visible:
                    status = 'OK'
                    num_rdeps = cve['num_rdeps']
                    num_vuln_rdeps = cve['num_vuln']
                    client_centrality = self.avg_client_centrality[id]
                    package_centrality = self.package_centrality[id]

                stat = {'id': id,
                        'status': status,
                        'total_rdeps': num_rdeps,
                        'package': package,
                        'vulnerable_symbols': vuln_symbols,
                        'vuln_rdeps': num_vuln_rdeps,
                        'avg_percent_client_api_leads_to_vulnerable': client_centrality,
                        'avg_percent_package_api_leads_to_vulnerable': package_centrality}

            self.final_stats.append(stat)


    def process(self):
        self.load_cve_stats()

        self.decide_visible()
        log.info(f'NOT_VISIBLE: {self.not_visible}')
        self.compute_client_centrality()
        self.compute_package_centrality()
        self.compute_final_stats()

        log.debug(f'LEN(FINAL_STATS) = {len(self.final_stats)}')

        if self.output_file is not None:
            with open(self.output_file, 'w') as outfile:
                outfile.write(json.dumps(self.final_stats, indent=2))
        else:
            log.info(json.dumps(self.final_stats, indent=2))



def main():
    args = parse_args()
    setup_logging(args)

    cvs = CveFinalStats(args.stats, args.output)
    cvs.process()

if __name__ == "__main__":
    main()


