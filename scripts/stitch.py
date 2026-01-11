import os
import sys
import json
import argparse
import logging
import inspect

import importlib

from stdlib_list import stdlib_list

STD_MODULES = stdlib_list('.'.join(sys.version.split('.')[:2]))
STD_MODULE_PREFIXES = [ m + '.' for m in STD_MODULES ]

STR_METHOD_SUFFIXES = [ i for i in dir(str) if not i.startswith('__') ]

BUGGY_PREFIXES = ['numpy.distutils']


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
    p = argparse.ArgumentParser(description='Stitch Python callgraphs in a sane way.')
    p.add_argument("call_graph_paths",
        nargs="*",
        help="Paths to call graphs to be stitched together in JSON format")
    p.add_argument(
        "-o",
        "--output",
        help="Output path",
        default=None
    )
    p.add_argument(
        "-t",
        "--toplevel",
        help="TL2PKG path",
        default=None
    )
    p.add_argument(
        "-l",
        "--log",
        default="info",
        help=("Provide logging level. Example --log debug"),
    )
    p.add_argument(
        "-s",
        "--sysdir",
        default=None,
        help=("Provide sysdir path to insert."),
    )
    p.add_argument(
        "-f",
        "--statsfile",
        default=None,
        help=("Provide stats output file path"),
    )
    return p.parse_args()


def get_import_name_pairs(import_name):
    parts = import_name.split(".")
    pairs = []

    for i in range(1, len(parts)):
        prefix = ".".join(parts[:i])
        suffix = ".".join(parts[i:])
        pairs.append((prefix, suffix))
    return pairs

def mod_path_to_fqn(mod_path, root_dir):
    if os.path.commonpath([mod_path, root_dir]) != root_dir:
        log.debug(f'mod_path {mod_path} is not subdirectory of {root_dir}')
        return None
    if mod_path.endswith('__init__.py'):
        mod_path = os.path.dirname(mod_path)
    elif mod_path.endswith('.so'):
        first_part = os.path.dirname(mod_path)
        last_part = os.path.basename(mod_path).split('.')[0]
        mod_path = os.path.join(first_part, last_part)

    rel = os.path.relpath(mod_path, root_dir)

    rel_no_suffix = os.path.splitext(rel)[0]

    fqn = rel_no_suffix.replace('/', '.')
    return fqn




class MyStitcher():
    def __init__(self, cg_paths, tl2pkg_path, output_file, sysdir_path, stats_file):
        self.sysdir_path = sysdir_path
        self.cg_paths = set(cg_paths)
        self.tl2pkg_path = tl2pkg_path
        self.output_file = output_file
        self.stats_file = stats_file
        self.tl2pkg = {}

        self.cgs = []

        self.final_nodes = {}
        self.final_edges = []
        self.next_index = 0
        self.n2idx = {}
        self.idx2n = {}
        self.n2fqn = {}

        self.pkg2cg = {}
        self.old2new = {}

        self.num_externals_found = 0
        self.num_externals_missed = 0
        self.num_externals_ignored = 0
        self.num_None_dst = 0

        self.final_cg = {'edges': self.final_edges, 'nodes': self.final_nodes}

        self.pynames_not_found = set()

        self.external_stats = {}

        if tl2pkg_path is not None:
            with open(tl2pkg_path, 'r') as infile:
                tl2pkg_raw = json.loads(infile.read())
            for tl, pkg in tl2pkg_raw.items():
                self.tl2pkg[tl] = pkg.split

    def get_and_bump_idx(self):
        ret = self.next_index
        self.next_index += 1
        return ret

    def load_callgraphs(self):
        for p in self.cg_paths:
            if not os.path.exists(p):
                raise RuntimeError(f'Call graph at provided path {p} does not exist!')
            with open(p, 'r') as infile:
                cg = json.loads(infile.read())
            self.cgs.append(cg)


    def add_internal(self):
        for cg in self.cgs:
            oldidx2newidx = {}
            name = cg['product']
            version = cg['version']
            package = name + ':' + version
            self.pkg2cg = cg
            internal_modules = cg['modules']['internal']
            for km, vm in internal_modules.items():
                for kn, vn in vm['namespaces'].items():
                    oldidx = int(kn)
                    ns = vn['namespace']
                    meta = vn['metadata']
                    newname = ns.replace('/', '.').lstrip('.').rstrip('.').removesuffix('()')

                    newmetadata = {'package': package}
                    if 'bridges' in meta.keys():
                        newmetadata['bridges'] = meta['bridges']
                    else:
                        newmetadata['bridges'] = None

                    newidx = self.get_and_bump_idx()
                    newnode = {'URI': newname, 'metadata': newmetadata}
                    self.final_nodes[str(newidx)] = newnode
                    self.idx2n[newidx] = newname
                    self.n2idx[newname] = newidx
                    oldidx2newidx[oldidx] = newidx

            internal_calls = cg["graph"]["internalCalls"]
            for call in internal_calls:
                src = int(call[0])
                dst = int(call[1])
                newsrc = oldidx2newidx[src]
                newdst = oldidx2newidx[dst]
                self.final_edges.append([newsrc, newdst])
                dstname = self.idx2n[newdst]
                dst_name_init = dstname + '.__init__'
                dst_init = self.n2idx.get(dst_name_init, None)
                if dst_init is not None:
                    log.debug(f'Also added edge to __init__ for {dstname}')
                    self.final_edges.append([newsrc, dst_init])

            self.old2new[package] = oldidx2newidx

    def try_import(self, name):
        pairs = get_import_name_pairs(name)
        log.debug(f'import pairs = {pairs}')
        found = None
        for m, rest in pairs:
            obj = None
            module = None
            success = True
            babushka = rest.split('.')
            try:
                module = importlib.import_module(m)
            except Exception as e:
                success = False
                log.debug(e)
                continue
            obj = module
            for o in babushka:
                try:
                    log.debug(f'getattr(m, {o})')
                    obj = getattr(obj, o)
                except Exception as e:
                    success = False
                    log.debug(e)
                    break
            if success:
                found = obj
                return found
        return found


    def pyname_to_fqn(self, pyname):
        obj = self.try_import(pyname)
        if obj is None:
            log.debug(f'No object found for external pyname {pyname}')
            return None

        mod = inspect.getmodule(obj)
        if mod is None:
            log.debug(f'None inspect.getmodule({pyname})')
            return None

        mod_path = getattr(mod, '__file__', None)
        if mod_path is None:
            log.debug(f'No __file__ for module returned by inspect.getmodule({pyname})')
            return None

        qualname = getattr(obj, '__qualname__', None)
        if qualname is None:
            log.debug(f'No __qualname__ attribute for pyname {pyname}. Falling back to last name after dot.')
            qualname = pyname.split('.')[-1]

        modname = mod_path_to_fqn(mod_path, self.sysdir_path)
        if modname is None:
            return None

        fqn = modname + '.' + qualname
        return fqn



    def resolve_externals(self):
        for cg in self.cgs:
            name = cg['product']
            version = cg['version']
            package = name + ':' + version
            unresolved = set()
            oldidx2extname = {}
            blacklist = set()
            external_modules = cg['modules']['external']
            log.info(package)
            for km, vm in external_modules.items():
                for kn, vn in vm['namespaces'].items():
                    oldidx = int(kn)
                    ns = vn['namespace']
                    extname = ns.split("//")[-1]
                    if (ns.startswith('//.builtin')
                        or any([extname.startswith(m) for m in STD_MODULE_PREFIXES])
                        or any([pref in extname for pref in BUGGY_PREFIXES])):
                        blacklist.add(oldidx)
                        log.debug(f'Added ns {ns} to blacklist')

                    possible_names = []
                    possible_names.append(extname)
                    possible_names.extend([ extname.removesuffix(s) for s in STR_METHOD_SUFFIXES if extname.removesuffix(s) not in possible_names])
                    oldidx2extname[oldidx] = possible_names

            external_calls = cg["graph"]["externalCalls"]
            count_externals = len(external_calls)
            found_externals = 0
            missed_externals = 0
            ignored_externals = 0

            for call in external_calls:
                try:
                    src = int(call[0])
                    dst = int(call[1])
                except Exception as e:
                    self.num_None_dst += 1
                    log.debug(f'Exception {e} when handling edge {call} from CG of package {package}')

                if dst in blacklist:
                    self.num_externals_ignored += 1
                    continue

                newsrc = self.old2new[package][src]
                dstnames = oldidx2extname.get(dst, None)

                if dstnames is None:
                    log.debug(f'No oldidx2extname for idx {dst}')
                    continue


                found = False
                for dname in dstnames:
                    options = [dname, dname + '.__init__']

                    fqn = self.n2fqn.get(dname, None)
                    if fqn is None:
                        fqn = self.pyname_to_fqn(dname)
                        if fqn is None:
                            fqn = 'NONE'
                        self.n2fqn[dname] = fqn

                    if fqn != 'NONE':
                        log.debug(f'FQN({dname}) = {fqn}')
                        fqns = [fqn, fqn + '.__init__']
                        for f in fqns:
                            if f not in options:
                                options.append(f)
                    else:
                        log.debug(f'FQN({dname}) = NONE')


                    for name in options:
                        if name in self.n2idx.keys():
                            log.debug(f'name = {name}, found in internals')
                            newdst = self.n2idx[name]
                            self.final_edges.append([newsrc, newdst])
                            if not found:
                                found_externals += 1
                                self.num_externals_found += 1
                            found = True


                if not found:
                    log.debug(f'No node found for externalCall to {dstnames[0]} from package {package}')
                    missed_externals += 1
                    self.num_externals_missed += 1
                    unresolved.add(dstnames[0])
                    self.external_stats[package] = {'total': count_externals,
                                               'found': found_externals,
                                               'missed': missed_externals,
                                               'which_missed': sorted(list(unresolved))}
                    self.pynames_not_found.add(dstnames[0])

    def stitch(self):
        sys.path.insert(0, self.sysdir_path)
        log.info(f'SYS_PATH = {sys.path}')
        self.load_callgraphs()
        self.add_internal()
        self.resolve_externals()

        log.info(f'NUM_EXTERNALS_FOUND = {self.num_externals_found}')
        log.info(f'NUM_EXTERNALS_MISSING = {self.num_externals_missed}')
        log.info(f'NUM_EXTERNALS_IGNORED = {self.num_externals_ignored}')
        log.info(f'NUM_NONE_DST_EDGES = {self.num_None_dst}')
        log.debug(f'Pynames not found:')

        for n in sorted(list(self.pynames_not_found)):
            log.debug(n)

        if self.stats_file is None:
            log.info(json.dumps(self.external_stats, indent=2))
        else:
            with open(self.stats_file, 'w') as outfile:
                outfile.write(json.dumps(self.external_stats, indent=2))

        if self.output_file is None:
            log.info(json.dumps(self.final_cg, indent=2))
        else:
            with open(self.output_file, 'w') as outfile:
                outfile.write(json.dumps(self.final_cg, indent=2))


def main():
    args = parse_args()
    setup_logging(args)

    if args.sysdir is None:
        log.error(f'No sysdir path provided')
        sys.exit(1)

    stitcher = MyStitcher(args.call_graph_paths, args.toplevel, args.output, args.sysdir, args.statsfile)
    stitcher.stitch()

if __name__ == "__main__":
    __name__ = 'FOO'
    main()

