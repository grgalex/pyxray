import os
import re
import sys
import json
import argparse
import logging
import networkx as nx
from collections import deque

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
    p = argparse.ArgumentParser(description='Find call chains for a given symbol.')
    p.add_argument(
        "-l",
        "--log",
        default="info",
        help=("Provide logging level. Example --log debug"),
    )
    p.add_argument(
        "-s",
        "--symbol",
        default=None,
        help=("Symbol to calculate chains towards."),
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
    return p.parse_args()

class ChainCalculator:
    def __init__(self, reached_cg_path, symbol, output_file=None):
        self.symbol = symbol
        self.reached_cg_path = reached_cg_path

        if not os.path.exists(reached_cg_path):
            raise ValueError(f'No file exists at {self.reached_cg_path}. Aborting...')

        self.output_file = output_file

        self.symbol_idx = None

        self.graph = None

        self.final_callgraph = {'nodes': {}, 'edges': []}
        self.n2idx = {}
        self.idx2n = {}
        self.n2pkg = {}

        self.call_chains = None

        self.num_leaves = 0
        self.centrality = 0



    def load_callgraph(self):
        with open(self.reached_cg_path, 'r') as infile:
            self.callgraph = json.loads(infile.read())

    def create_graph(self):
        graph = nx.DiGraph()
        for idxstr, v in self.callgraph["nodes"].items():
            idx = int(idxstr)
            name = v["name"]
            library = v.get('library', None)

            if library is None:
                if 'package' not in v.keys():
                    log.error(f'node with idx {idx} and value {v} has neither library nor package')
                    pkg = 'foo' 
                    # raise RuntimeError
                else:
                    pkg = v["package"]
                self.n2pkg[name] = pkg

            if name == self.symbol:
                self.symbol_idx = idx

            self.idx2n[idx] = name
            self.n2idx[name] = idx
            graph.add_node(idx)
        if self.symbol_idx is None:
            log.debug(f'Symbol not in reached callgraph.')
            return -1

        self.graph = graph

        for edge in self.callgraph["edges"]:
            graph.add_edge(edge[0], edge[1])
        return 0

    def find_callchains(self):
        G = self.graph.reverse()
        paths = []

        self.num_leaves = 0

        for node in G:
            if G.out_degree(node)==0:
                self.num_leaves += 1
                try:
                    sps = nx.shortest_path(G, self.symbol_idx, node)
                    paths.append(sps)
                except Exception as e:
                    continue
        rpaths = [reversed(p) for p in paths]
        self.call_chains = rpaths

        self.centrality = len(self.call_chains) / self.num_leaves

    def process(self):
        self.load_callgraph()

        ret = self.create_graph()
        if ret < 0:
            return []

        self.find_callchains()

        named_chains = []
        for c in self.call_chains:
            nc = [self.idx2n[i] for i in c]
            named_chains.append(nc)

        self.named_chains = sorted(named_chains, key=len)

        log.info(f'Call chains to {self.symbol}')
        i = 0
        for c in self.named_chains:
            chain = c[0]
            i += 1
            for n in c[1:]:
                chain += ' -> '
                chain += n
            log.info(f'#[{i}]: {chain}')


        if self.output_file is not None:
            with open(self.output_file, 'w') as outfile:
                outfile.write(json.dumps(self.named_chains, indent=2))
            log.info(f'Wrote chains to {self.output_file}')
        else:
            log.info(json.dumps(self.named_chains, indent=2))

        log.info(f'CENTRALITY: {self.centrality}')

        return self.named_chains


def main():
    args = parse_args()
    setup_logging(args)

    if args.symbol is None:
        log.error("Must provide symbol to calculate chains towards")
        sys.exit(1)

    if args.callgraph is None:
        log.error("Must provide callgraph to process")
        sys.exit(1)

    chain = ChainCalculator(args.callgraph, args.symbol, args.output)
    chain.process()


if __name__ == "__main__":
    main()


