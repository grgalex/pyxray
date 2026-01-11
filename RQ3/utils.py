import os
import csv
import json
import logging
import Levenshtein
from pathlib import Path
import subprocess as sp

log = logging.getLogger(__name__)

def load_csv(filename):
    package_names = []
    with open(filename, 'r') as file:
        csv_reader = csv.reader(file)
        package_names = [row[0] for row in csv_reader if row]
    return package_names

def to_mod_name(name):
    return os.path.splitext(name)[0].replace("/", ".")

def repo_name_to_tuple(pkg):
    parts = pkg.split('/')
    user = parts[0]
    repo = parts[1]
    return (user,repo)

def pkg_name_to_tuple(pkg):
    parts = pkg.split(':')
    name = parts[0]
    version = parts[1]
    return (name,version)

def get_mod_import_name(mod_path, pkg_root_path):
    if pkg_root_path == 'naked':
        return os.path.basename(mod_path).split('.')[0]

    if mod_path.endswith(".so"):
        first_part = os.path.dirname(mod_path)
        last_part = os.path.basename(mod_path).split('.')[0]
        mod_path = os.path.join(first_part, last_part)

    rel = os.path.relpath(mod_path, pkg_root_path)
    import_name = os.path.basename(pkg_root_path) + '.' + to_mod_name(rel)

    return import_name

def run_cmd(opts, timeout=None, shell=False):
    cmd = sp.Popen(opts, stdout=sp.PIPE, stderr=sp.PIPE, text=True, shell=shell)
    out, err = cmd.communicate(timeout=None)
    ret = cmd.returncode
    log.debug(opts)
    log.debug("ret = %s" % ret)
    log.debug(out)
    log.debug(err)
    return ret, out, err

def create_dir(path):
    p = Path(path)
    if not p.exists():
        p.mkdir(parents=True)

def find_git_root():
    path = Path.cwd()
    if (path/".git").exists():
        return path.as_posix()
    for parent in path.parents:
        if (parent/".git").exists():
            return parent.as_posix()
    return None

def find_closest_match(query, options):
    distances = {option: Levenshtein.distance(query, option) for option in options}
    return min(distances, key=distances.get)

def bincg_add_fun_suffix(lib, bincg_path):
    # XXX: Add extra lib-specific suffix on FUN_* nodes to avoid clashes
    #      with similarly-named nodes from other binaries when stitching.
    # lib_basename = lib.split('/')[-1]
    # suffix = lib_basename.split('.')[0] # XXX: strip the file's suffix (e.g. libxcb.so -> libxcb)
    suffix = lib.replace('/', '_')
    with open(bincg_path, 'r') as infile:
        cg = json.loads(infile.read())
    nodes = cg["nodes"]
    for k in nodes.keys():
        if nodes[k]["name"].startswith("FUN_"):
            newname = nodes[k]["name"] + '_' + suffix
            cg["nodes"][k]["name"] = newname

    with open(bincg_path, 'w') as outfile:
        outfile.write(json.dumps(cg, indent=2))

