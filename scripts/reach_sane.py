import os
import re
import sys
import json
import argparse
import logging
import networkx as nx

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
        "-p",
        "--package",
        default=None,
        help=("Provide package in either user/repo or name:version format."),
    )
    p.add_argument(
        "-i",
        "--callgraph",
        default=None,
        help=("Path to unified callgraph to process."),
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help=("Output path."),
    )
    p.add_argument(
        "-F",
        "--fasten",
        default=False,
        action='store_true',
        help=("Indicates that unified CG is in FASTEN format."),
    )
    return p.parse_args()

class ReachabilityDetector:
    def __init__(self, package, unified_cg_path, output, fasten):
        self.package = package
        self.fasten = fasten
        if ':' in self.package:
            self.pypi = True
        elif '/' in self.package:
            self.pypi = False
            self.package = package + ':1'
        else:
            log.error(f'Unrecognized package naming format: {self.package}')
            raise ValueError(f'Unrecognized package naming format: {self.package}')

        self.unified_cg_path = unified_cg_path
        if not os.path.exists(unified_cg_path):
            raise ValueError(f'No file exists at {self.unified_cg_path}. Aborting...')

        self.output = output

        self.graph = None
        self.entrypoints = None
        self.reachable_idxs = set()

        self.final_callgraph = {'nodes': {}, 'edges': []}
        self.n2idx = {}
        self.idx2n = {}
        self.n2pkg = {}


    def generate_final_callgraph(self):
        for idx, v in self.callgraph['nodes'].items():
            if int(idx) in self.reachable_idxs:
                self.final_callgraph['nodes'][idx] = self.callgraph['nodes'][idx]
        for e in self.callgraph['edges']:
            src = e[0]
            dst = e[1]
            if src in self.reachable_idxs and dst in self.reachable_idxs:
                self.final_callgraph['edges'].append(e)
            elif (src in self.reachable_idxs and not dst in self.reachable_idxs):
                log.warning(f'dst of edge {e} is not in reachable nodes while src is')


    def load_callgraph(self):
        with open(self.unified_cg_path, 'r') as infile:
            self.callgraph = json.loads(infile.read())

    def calculate_reachable(self):
        for idx in self.entrypoints:
            idxs = nx.descendants(self.graph, idx)
            self.reachable_idxs.update(idxs)
            self.reachable_idxs.add(idx)

    def find_entrypoints(self):
        entrypoints=set()

        for n, p in self.n2pkg.items():
            if p == self.package:
                entrypoints.add(self.n2idx[n])

        self.entrypoints = entrypoints


    def uri2package_fasten(self, text):
        match = re.search(r'!(.+?)\$([^/]+)/', text)
        if match:
            name = match.group(1)
            version = match.group(2)
        else:
            log.error(f"Could not parse URI {uri}")
            return -1

        return(name,version)

    def create_graph(self):
        graph = nx.DiGraph()
        for idxstr, v in self.callgraph["nodes"].items():
            idx = int(idxstr)
            name = v["name"]
            library = v.get('library', None)
            uri = (name, library)

            if library is None:
                if 'package' not in v.keys():
                    log.error(f'node with idx {idx} and value {v} has neither library nor package')
                    raise RuntimeError
                pkg = v["package"]
                self.n2pkg[name] = pkg

            self.idx2n[idx] = name
            self.n2idx[name] = idx
            graph.add_node(idx)

        self.graph = graph

        for edge in self.callgraph["edges"]:
            graph.add_edge(edge[0], edge[1])

    def reach(self):
        self.load_callgraph()
        self.create_graph()
        self.find_entrypoints()
        log.info(f'Entrypoints for {self.package}: {len(self.entrypoints)}')
        self.calculate_reachable()
        self.generate_final_callgraph()

        if self.output is not None:
            with open(self.output, 'w') as outfile:
                outfile.write(json.dumps(self.final_callgraph, indent=2))
            log.info(f'Wrote reached callgraph to {self.output}')
        else:
            log.info(json.dumps(self.final_callgraph, indent=2))


def main():
    args = parse_args()
    setup_logging(args)

    if args.package is None:
        log.error("Must provide package to process")
        sys.exit(1)

    if args.callgraph is None:
        log.error("Must provide callgraph to process")
        sys.exit(1)

    reacher = ReachabilityDetector(args.package, args.callgraph, args.output, args.fasten)
    reacher.reach()


if __name__ == "__main__":
    main()

