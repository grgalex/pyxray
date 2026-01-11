import sys
import json
import argparse
import logging
from collections import defaultdict

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
    p = argparse.ArgumentParser(description='Stitch Python and shared library call graphs based on bridges')
    p.add_argument("socg_files", nargs="*", help="Shared object Call graphs to process")
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
        help=("Provide path to input PyCG stitched callgraph."),
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help=("Output file."),
    )
    return p.parse_args()


class Unifier():
    def __init__(self, pycg_file, socg_files):
        self.pycg_file = pycg_file
        self.socg_files = socg_files
        self.socgs = []
        self.pycg_nodes = {}
        self.pycg_edges = []
        self.next_index = 0
        self.hops = []
        self.final_nodes = {}
        self.final_edges = []
        self.seen_names = set()
        self.n2idx = {}
        self.idx2n = {}
        self.libs_reparse = set()

        self.egress_per_name_per_lib = defaultdict(dict)

    def get_and_bump_idx(self):
        ret = self.next_index
        self.next_index += 1
        return ret

    def load_pycg(self):
        with open(self.pycg_file, 'r') as infile:
            cg = json.loads(infile.read())
        self.pycg_edges = cg['edges']
        self.pycg_nodes = cg['nodes']

    def load_socgs(self):
        for f in self.socg_files:
            with open(f, 'r') as infile:
                socg_raw = json.loads(infile.read())
            nodes = socg_raw['nodes']
            library = socg_raw['library']

            old2new = {}

            for k, v in nodes.items():
                name = v['name']
                if name not in self.n2idx.keys():
                    new_node = {'name': name, 'library': library}
                    new_idx = self.get_and_bump_idx()
                    self.final_nodes[str(new_idx)] = new_node
                    self.n2idx[name] = new_idx
                    self.idx2n[new_idx] = name
                    old2new[int(k)] = new_idx
                else:
                    old2new[int(k)] = self.n2idx[name]
                self.egress_per_name_per_lib[name][library] = 0


            for e in socg_raw['edges']:
                src = e[0]
                dst = e[1]
                newsrc = old2new[src]
                newdst = old2new[dst]
                srcname = self.idx2n[newsrc]
                self.final_edges.append([newsrc, newdst])
                if library in self.egress_per_name_per_lib[srcname].keys():
                    self.egress_per_name_per_lib[srcname][library] += 1
                else:
                    self.egress_per_name_per_lib[srcname][library] = 1


    def process_pycg(self):
        old2new = {}
        for old_idx, node in self.pycg_nodes.items():
            name = node['URI']
            new_node = {'name': name, 'package': node['metadata']['package']}
            new_idx = self.get_and_bump_idx()
            self.final_nodes[new_idx] = new_node
            self.n2idx[name] = new_idx
            self.idx2n[new_idx] = name
            old2new[int(old_idx)] = new_idx
            bridges = node['metadata']['bridges']
            if bridges is not None:
                for b in bridges:
                    hop_name = b['symbol']
                    lib = b['library']
                    if hop_name in self.n2idx.keys():
                        hop_idx = self.n2idx[hop_name]
                        self.final_edges.append([new_idx, hop_idx])
                        self.egress_per_name_per_lib[hop_name][lib] = -1
                    else:
                        log.warn(f'hop symbol for bridge {b} not found for {self.pycg_file}')

        for e in self.pycg_edges:
            src = e[0]
            dst = e[1]
            newsrc = old2new[src]
            newdst = old2new[dst]
            self.final_edges.append([newsrc, newdst])

    def decide_final_libs(self):
        for idx, node in self.final_nodes.items():
            if 'library' in node.keys():
                name = node['name']
                lib = node['library']
                sorted_epln = sorted(self.egress_per_name_per_lib[name].items(), key=lambda item: item[1])
                if sorted_epln[0][1] == -1:
                    final_library = sorted_epln[0][0]
                else:
                    final_library = sorted_epln[-1][0]
                final_library = sorted_epln[0][0]
                self.final_nodes[idx]['library'] = final_library

    def unify(self):
        self.load_pycg()

        self.load_socgs()

        self.process_pycg()

        self.decide_final_libs()
        result = {'nodes': self.final_nodes, 'edges': self.final_edges}
        return result

def main():
    args = parse_args()
    setup_logging(args)
    output_file = args.output

    if args.input is None:
        log.error("Must provide input cg path")
        sys.exit(1)

    unifier = Unifier(args.input, args.socg_files)
    result = unifier.unify()

    if output_file is None:
        log.info(json.dumps(result, indent=2))
    else:
        with open(output_file, 'w') as outfile:
            outfile.write(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

