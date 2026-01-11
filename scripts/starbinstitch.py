import sys
import json
import argparse
import logging
from collections import defaultdict
import networkx as nx

log = logging.getLogger(__name__)

class StarBinStitcher():
    def __init__(self, starfile, output_file, socg_files):
        self.starfile = starfile
        self.socg_files = socg_files
        self.output_file = output_file
        self.bridges_not_found = []
        self.socgs = []
        self.bridges = []
        self.next_index = 0
        self.nodes = {}
        self.edges = []
        self.final_nodes = {}
        self.final_edges = []
        self.n2idx = {}
        self.idx2n = {}
        self.entrypoints = set()
        self.final_callgraph = {'nodes': {}, 'edges': []}

        self.egress_per_name_per_lib = defaultdict(dict)
        self.reachable_idxs = set()

    def get_and_bump_idx(self):
        ret = self.next_index
        self.next_index += 1
        return ret

    def load_starfile(self):
        with open(self.starfile, 'r') as infile:
            sb = json.loads(infile.read())
        self.bridges = sb['bridges']

    def load_socgs(self):
        for f in self.socg_files:
            with open(f, 'r') as infile:
                socg_raw = json.loads(infile.read())
            nodes = socg_raw['nodes']
            library = socg_raw['library']

            old2new = {}

            for k, v in nodes.items():
                name = v['name']
                log.info(f'name = {name}')
                if name not in self.n2idx.keys():
                    new_node = {'name': name, 'library': library}
                    new_idx = self.get_and_bump_idx()
                    self.nodes[str(new_idx)] = new_node
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
                self.edges.append([newsrc, newdst])
                if library in self.egress_per_name_per_lib[srcname].keys():
                    self.egress_per_name_per_lib[srcname][library] += 1
                else:
                    self.egress_per_name_per_lib[srcname][library] = 1


    def process_starfile(self):
        for b in self.bridges:
            pyname = b['pyname']
            cfunc = b['cfunc']
            if cfunc not in self.n2idx.keys():
                log.warn(f'cfunc {cfunc} from starfile {self.starfile} not found in any binary callgraph')
                self.bridges_not_found.append(b)
            else:
                if pyname not in self.n2idx.keys():
                    new_node = {'name': pyname, 'package': 'PYTHON'}
                    new_idx = self.get_and_bump_idx()
                    self.nodes[str(new_idx)] = new_node
                    self.n2idx[pyname] = new_idx
                    self.idx2n[new_idx] = pyname
                else:
                    new_idx = self.n2idx[pyname]
                self.edges.append([new_idx, self.n2idx[cfunc]])
                self.entrypoints.add(new_idx)


    def decide_final_libs(self):
        for idx, node in self.nodes.items():
            if 'library' in node.keys():
                name = node['name']
                lib = node['library']
                sorted_epln = sorted(self.egress_per_name_per_lib[name].items(), key=lambda item: item[1])
                if sorted_epln[0][1] == -1:
                    final_library = sorted_epln[0][0]
                else:
                    final_library = sorted_epln[-1][0]
                final_library = sorted_epln[0][0]
                self.nodes[idx]['library'] = final_library

    def calculate_reachable(self):
        for idx in self.entrypoints:
            idxs = nx.descendants(self.graph, idx)
            self.reachable_idxs.update(idxs)
            self.reachable_idxs.add(idx)

    def create_graph(self):
        graph = nx.DiGraph()
        for idxstr, v in self.callgraph["nodes"].items():
            idx = int(idxstr)
            name = v["name"]
            library = v.get('library', None)

            if library is None:
                if 'package' not in v.keys():
                    log.error(f'node with idx {idx} and value {v} has neither library nor package')
                    raise RuntimeError
                pkg = v["package"]

            self.idx2n[idx] = name
            self.n2idx[name] = idx
            graph.add_node(idx)

        self.graph = graph

        for edge in self.callgraph["edges"]:
            graph.add_edge(edge[0], edge[1])

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

    def stitch(self):
        self.load_starfile()

        self.load_socgs()

        self.process_starfile()

        self.decide_final_libs()

        self.callgraph = {'nodes': self.nodes, 'edges': self.edges}

        self.create_graph()

        self.calculate_reachable()

        self.generate_final_callgraph()

        if self.output_file is None:
            log.info(json.dumps(self.final_callgraph, indent=2))
        else:
            with open(self.output_file, 'w') as outfile:
                outfile.write(json.dumps(self.final_callgraph, indent=2))
