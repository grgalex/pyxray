import os
import sys
import json
import argparse
import logging
import shutil
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
    p = argparse.ArgumentParser(description='Process a single Python-aware shared library, produce bridges')
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
        help=("Output (entended) partial CG path."),
    )
    p.add_argument(
        "-d",
        "--dir",
        default=None,
        help=("Absolute path to directory containing the call graphs."),
    )
    p.add_argument(
        "-i",
        "--input",
        default=None,
        help=("Absolute path to the bridges JSON."),
    )

    return p.parse_args()

class Augmentor():
    def __init__(self, tl2pkg_path, pkg2pcg_path, bridges_file, pkg2aug_path, given_package):
        with open(tl2pkg_path, 'r') as infile:
            self.tl2pkg = json.loads(infile.read())
        with open(pkg2pcg_path, 'r') as infile:
            self.pkg2pcg = json.loads(infile.read())
        with open(pkg2aug_path, 'r') as infile:
            self.pkg2aug = json.loads(infile.read())

        self.pkg2tl = defaultdict(list)
        for k, v in self.tl2pkg.items():
            self.pkg2tl[v].append(k)
        self.given_package = given_package
        self.bridges_file = bridges_file
        self.prev_num_nodes = None
        self.found_internals = []
        self.created_internals = []

        self.cg_path2cg = {}

    def tl_to_cg_path(self, tl):
        pkg = self.tl2pkg[tl]
        pcg_path = self.pkg2aug[pkg]
        return pcg_path

    def pyname_to_tl_external(self, pyname):
        return pyname.split('//')[1]

    def pyname_to_squash_external(self, pyname):
        return pyname.split('//')[-1]

    def process_internal_bridge(self, bridge):
        pyname = bridge['pyname']

        simple_bridge = {'symbol': bridge['cfunc'], 'library': bridge['library']}
        pkg = self.given_package
        cg_path = self.pkg2aug[pkg]
        if cg_path in self.cg_path2cg.keys():
            cg = self.cg_path2cg[cg_path]
        else:
            try:
                with open(cg_path, 'r+') as cg_file:
                    cg = json.load(cg_file)
            except FileNotFoundError as e:
                log.warn(e)
                return
            self.cg_path2cg[cg_path] = cg
        num_nodes = cg['nodes']
        internals = cg['modules']['internal']

        found = False
        changed = False
        for k, m in internals.items():
            for kk, n in m['namespaces'].items():
                ns = n['namespace']
                if (ns == pyname) or (ns == pyname +'()'):
                    if not ns.endswith('()'):
                        cg['modules']['internal'][k]['namespaces'][kk]['namespace'] += '()'
                        changed = True
                    meta = n['metadata']
                    if 'bridges' in meta.keys():
                        old_bridges = meta['bridges']
                        if simple_bridge not in old_bridges:
                            new_bridges = old_bridges + [simple_bridge]
                            cg['modules']['internal'][k]['namespaces'][kk]['metadata']['bridges'] = new_bridges
                            changed = True

                    else:
                        cg['modules']['internal'][k]['namespaces'][kk]['metadata']['bridges'] = [simple_bridge]
                        changed = True
                    found = True
                    self.found_internals.append({'bridge': bridge, 'cg_path': cg_path, 'namespace': n})
        if not found:
            log.warn(f"Internal bridge for {pyname} not found in internals of corresponding CG. This is bad...")

    def process_external_bridge(self, bridge):
        pyname = bridge['pyname']

        simple_bridge = {'symbol': bridge['cfunc'], 'library': bridge['library']}
        tl = self.pyname_to_tl_external(pyname)
        try:
            cg_path = self.tl_to_cg_path(tl)
        except KeyError as e:
            log.error(f'No package found for top-level import {e}')
            return

        if cg_path in self.cg_path2cg.keys():
            cg = self.cg_path2cg[cg_path]
        else:
            try:
                with open(cg_path, 'r+') as cg_file:
                    cg = json.load(cg_file)
            except FileNotFoundError as e:
                log.warn(e)
                return
            self.cg_path2cg[cg_path] = cg

        tls = self.pkg2tl[self.tl2pkg[tl]]


        squashed_pyname = self.pyname_to_squash_external(pyname)
        num_nodes = cg['nodes']
        internals = cg['modules']['internal']

        found = False
        changed = False
        for k, m in internals.items():
            for kk, n in m['namespaces'].items():
                ns = n['namespace']
                clean = ns.replace('/', '.')
                clean = clean.lstrip('.')
                if not any(clean.startswith(t + '.') for t in tls):
                    clean = tl + '.' + clean
                if (clean == squashed_pyname) or (clean == squashed_pyname +'()'):
                    meta = n['metadata']
                    if 'bridges' in meta.keys():
                        old_bridges = meta['bridges']
                        if simple_bridge not in old_bridges:
                            new_bridges = old_bridges + [simple_bridge]
                            cg['modules']['internal'][k]['namespaces'][kk]['metadata']['bridges'] = new_bridges
                            changed = True
                    else:
                        cg['modules']['internal'][k]['namespaces'][kk]['metadata']['bridges'] = [simple_bridge]
                        changed = True
                    found = True
                    self.found_internals.append({'bridge': bridge, 'cg_path': cg_path, 'namespace': n})
                    break
        if not found:
            modname = '/' + tl + '/'
            new_ns = modname + ".".join(squashed_pyname.split('.')[1::]) + '()'
            new_internal = {'namespace': new_ns,
                            'metadata': {'bridges': [simple_bridge]}}
            new_index = str(num_nodes)
            if modname not in internals.keys():
                internals[modname] = {'sourceFile': "__init__.py", 'namespaces': {}}
                bootstrap_mod = {'namespace': modname, 'metadata': {}}
                internals[modname]['namespaces'][new_index] = bootstrap_mod
                num_nodes += 1
                new_index = str(num_nodes)

            cg['modules']['internal'][modname]['namespaces'][new_index] = new_internal
            description = {'bridge': bridge, 'cg_path': cg_path, 'namespace': new_internal}
            self.created_internals.append(description)
            cg['nodes'] = num_nodes + 1
            changed = True

    def augment(self):
        with open(self.bridges_file, 'r') as infile:
            self.bridges = json.load(infile)

        for b in self.bridges['internal']:
            self.process_internal_bridge(b)
        for b in self.bridges['external']:
            self.process_external_bridge(b)

        for cgp in self.cg_path2cg.keys():
            with open(cgp, 'w') as outfile:
                cg = self.cg_path2cg[cgp]
                outfile.write(json.dumps(cg, indent=2))

