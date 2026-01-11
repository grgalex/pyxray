import os
import re
import sys
import ctypes
import types
import logging
import argparse
import importlib
import json

import subprocess
import tempfile

from pathlib import Path

import objects

log = logging.getLogger(__name__)

EXCLUDE_LIBS = []

GDB_PYTHON_SCRIPT_HEADER = """
import gdb

def addr2symbol(address):
    try:
        gdb_address = gdb.parse_and_eval(f'({address})')

        # Use GDB's `info symbol` to get the symbol at the address
        symbol_info = gdb.execute(f'info symbol {gdb_address}', to_string=True).strip()

        if symbol_info:
            print(f'___ADDRESS___{address}___ADDRESS______FUNC___{symbol_info}___FUNC___')
        else:
            print(f'___ADDRESS___{address}___ADDRESS______FUNC___NOTFOUND___FUNC___')
    except gdb.error as e:
        print(f'___ADDRESS___{address}___ADDRESS______ERROR___{e}___ERROR___')
"""

GDB_NO_DEMANGLE_INVOKE = "gdb.execute('set print demangle off')\n"
GDB_ADDR2SYMBOL_INVOKE = "addr2symbol(%s)\n"
GDB_QUIT_INVOKE = "gdb.execute('quit')\n"


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
        help=("Output file. Example --output bridges.json"),
    )
    p.add_argument(
        "-s",
        "--sysdir",
        default=None,
        help=("Optionally extend sys.path with this path. Example -s /tmp/mypackages"),
    )
    p.add_argument(
        "-p",
        "--package",
        default=None,
        help=("Package name. Used to construct FQNs when missing info."),
    )
    p.add_argument(
        "-i",
        "--input",
        default=None,
        help=("Absolute path to the candidates JSON file."),
    )

    return p.parse_args()

def run_gdb(symbol_addresses):
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w') as cmd_file:
        cmd_file_path = cmd_file.name
        script = GDB_PYTHON_SCRIPT_HEADER
        script += GDB_NO_DEMANGLE_INVOKE
        for addr in symbol_addresses:
            script += GDB_ADDR2SYMBOL_INVOKE % addr
        script += GDB_QUIT_INVOKE

        cmd_file.write(script)
        cmd_file.flush()

        pid_self_str = str(os.getpid())

        gdb_launch_cmd = f'sudo gdb --batch -ex "source {cmd_file_path}" --pid {pid_self_str}'

        try:
            fout = tempfile.NamedTemporaryFile(delete=False)
            ferr = tempfile.NamedTemporaryFile(delete=False)
            p = subprocess.run(
                gdb_launch_cmd,
                shell=True,  # Run the command through the shell
                stdout=fout,
                stderr=ferr,
                text=True,  # Return output as a string (available in Python 3.7+)
            )
        except subprocess.CalledProcessError as e:
            print("subprocess run failed: %s" % e)
            raise
        fout.close()
        ferr.close()
        fout = open(fout.name, 'r')
        ferr = open(ferr.name, 'r')
        stdout = fout.read()
        stderr = ferr.read()
        log.debug(fout.name)
        log.debug(ferr.name)
        fout.close()
        ferr.close()
        try:
            os.remove(fout.name)
            os.remove(ferr.name)
        except Exception as e:
            log.warning(e)
        return stdout


class PyObject(ctypes.Structure):
    _fields_ = [
        ('ob_refcnt', ctypes.c_size_t),
        ('ob_type', ctypes.py_object),
    ]

class FunctionRecord(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),  # char*
        ("doc", ctypes.c_char_p),  # char*
        ("signature", ctypes.c_char_p),  # char*
        ("args", ctypes.c_void_p * 3),
        ("impl", ctypes.c_void_p),  # function pointer
        ("data", ctypes.c_void_p * 3),  # void* data[3]
        ("free_data", ctypes.c_void_p),  # void (*free_data)(function_record*)
        ("policy", ctypes.c_int),  # pybind11::return_value_policy
        ("is_constructor", ctypes.c_uint8, 1),
        ("is_new_style_constructor", ctypes.c_uint8, 1),
        ("is_stateless", ctypes.c_uint8, 1),
        ("is_operator", ctypes.c_uint8, 1),
        ("is_method", ctypes.c_uint8, 1),
        ("is_setter", ctypes.c_uint8, 1),
        ("has_args", ctypes.c_uint8, 1),
        ("has_kwargs", ctypes.c_uint8, 1),
        ("prepend", ctypes.c_uint8, 1),
        ("nargs", ctypes.c_uint16),
        ("nargs_pos", ctypes.c_uint16),
        ("nargs_pos_only", ctypes.c_uint16),
        ("def_ptr", ctypes.c_void_p),  # PyMethodDef*
        ("scope", ctypes.c_void_p),  # pybind11::handle
        ("sibling", ctypes.c_void_p),  # pybind11::handle
        ("next", ctypes.c_void_p)  # function_record* (linked list)
    ]

class PyCapsule(ctypes.Structure):
    _fields_ = [
        ('ob_base', PyObject),
        ("pointer", ctypes.c_void_p),  # void* (stores the actual C pointer)
        ("name", ctypes.c_char_p),     # const char* (optional name)
        ("context", ctypes.c_void_p),  # void* (optional context)
        ("destructor", ctypes.c_void_p)  # void (*destructor)(PyObject*)
    ]


# from Include/methodobject.h:
class PyMethodDef(ctypes.Structure):
    _fields_ = [
        ('ml_name', ctypes.c_char_p),
        ('ml_meth', ctypes.c_void_p),
        ('ml_flags', ctypes.c_int),
        ('ml_doc', ctypes.c_char_p),
    ]

# from Include/cpython/methodobject.h:
class PyCFunctionObject(ctypes.Structure):
    _fields_ = [
        ('ob_base', PyObject),
        ('m_ml', ctypes.POINTER(PyMethodDef)),
        ('m_self', ctypes.py_object),
        ('m_module', ctypes.py_object),
        # (other fields aren't interesting here)
    ]

class PyDescrObject(ctypes.Structure):
    _fields_ = [
        ('ob_base', PyObject),
        ('d_type', ctypes.c_void_p),
        ('d_name', ctypes.c_void_p),
        ('d_qualname', ctypes.c_void_p),
        # (other fields aren't interesting here)
    ]

class PyMethodDescrObject(ctypes.Structure):
    _fields_ = [
        ('descr_common', PyDescrObject),
        ('d_method', ctypes.POINTER(PyMethodDef)),
        ('vectorcall', ctypes.c_void_p),
        # (other fields aren't interesting here)
    ]

class PyWrapperDescrObject(ctypes.Structure):
    _fields_ = [
        ('descr_common', PyDescrObject),
        ('d_base', ctypes.c_void_p),
        ('d_wrapped', ctypes.c_void_p),
        # (other fields aren't interesting here)
    ]

class PyMethodWrapperObject(ctypes.Structure):
    _fields_ = [
        ('ob_base', PyObject),
        ('descr', ctypes.POINTER(PyWrapperDescrObject)),
        # (other fields aren't interesting here)
    ]

class PyUFuncObject(ctypes.Structure):
    _fields_ = [
        ('ob_base', PyObject),
        ('nin', ctypes.c_int),
        ('nout', ctypes.c_int),
        ('nargs', ctypes.c_int),
        ('identity', ctypes.c_int),
        ('functions', ctypes.POINTER(ctypes.c_void_p)),
        ("data", ctypes.POINTER(ctypes.c_void_p)),
        ("ntypes", ctypes.c_int),
        # (other fields aren't interesting here)
    ]

def parse_gdb_line(line):
    ret = None

    notfound_pattern = r"___ADDRESS___(.*?)___ADDRESS______FUNC___NOTFOUND___FUNC___"
    match = re.search(notfound_pattern, line)

    if match:
        address = match.group(1)
        log.debug("Address: %s | NOTFOUND" % address)
        return ret

    pattern = r"___ADDRESS___(.*?)___ADDRESS______FUNC___(\S+)\s+in section\s+(\S+)\s+of\s+(.+)___FUNC___"
    match = re.search(pattern, line)

    if match:
        address = match.group(1)
        c_name = match.group(2)
        section = match.group(3)
        library = match.group(4)
        log.debug("Address: %s" % address)
        log.debug("C Name: %s" % c_name)
        log.debug("Library: %s" % library)

        ret = objects.PyCHop(None, address, c_name, section, library)
    else:
        log.debug(f"Could not match pat for line: {line}")

    return ret

def get_import_name_pairs(import_name):
    parts = import_name.split(".")
    pairs = []

    for i in range(1, len(parts)):
        prefix = ".".join(parts[:i])
        suffix = ".".join(parts[i:])
        pairs.append((prefix, suffix))
    return pairs

class Analyzer():
    def __init__(self, candidates_path, sysdir_path, output_file, package):
        with open(candidates_path, 'r') as infile:
            self.candidates = json.loads(infile.read())
        log.info(f"SYSDIR_PATH = {sysdir_path}")
        self.package = package
        self.sysdir_path = sysdir_path
        self.output_file = output_file
        self.symbol_addresses = set()
        self.pyname_addr_pairs = []
        self.hops = []
        self.jump_libs = set()
        self.ignored_libs = set()

    def check_bingo(self, obj, pyname):
        ret = 0
        if type(obj) == types.BuiltinFunctionType:
            ret = self.extract_cfunc_pycfunction(obj, pyname)
            x = getattr(obj, '__self__', None) # PyCapsule Object (if bingo)
            if x is not None:
                y = type(x) # PyCapsule Type (if bingo)
                z = getattr(y, '__name__', None)
                if z == 'PyCapsule':
                    ret = self.extract_cfunc_pybind11(x, pyname)
        elif type(obj) == types.MethodDescriptorType:
            ret = self.extract_cfunc_pymethoddescr(obj, pyname)
        elif type(obj) == types.MethodWrapperType:
            ret = self.extract_cfunc_pymethodwrapper(obj, pyname)
        elif type(obj) == types.WrapperDescriptorType:
            ret = self.extract_cfunc_pywrapperdescr(obj, pyname)
        elif type(obj).__name__ == 'cython_function_or_method':
            ret = self.extract_cfunc_pycfunction(obj, pyname)
        elif type(obj).__name__ == 'ufunc' and (hasattr(obj, 'nin') and hasattr(obj, 'nout')):
            ret = self.extract_cfunc_numpy_ufunc(obj, pyname)

        return ret

    def decide_bridge(self, pyname, addr):
        self.symbol_addresses.add(addr)
        pyname_addr = {"pyname": pyname, "address": addr}
        if pyname_addr not in self.pyname_addr_pairs:
            self.pyname_addr_pairs.append(pyname_addr)
        else:
            pass
        return 0

    def extract_cfunc_pycfunction(self, obj, pyname):
        func = PyCFunctionObject.from_address(id(obj))
        addr = func.m_ml[0].ml_meth
        return self.decide_bridge(pyname, addr)

    def extract_cfunc_pymethoddescr(self, obj, pyname):
        func = PyMethodDescrObject.from_address(id(obj))
        addr = func.d_method[0].ml_meth
        return self.decide_bridge(pyname, addr)

    def extract_cfunc_pymethodwrapper(self, obj, pyname):
        wrap = PyMethodWrapperObject.from_address(id(obj))
        addr = wrap.descr[0].d_wrapped
        return self.decide_bridge(pyname, addr)

    def extract_cfunc_pywrapperdescr(self, obj, pyname):
        descr = PyWrapperDescrObject.from_address(id(obj))
        addr = descr.d_wrapped
        return self.decide_bridge(pyname, addr)

    def extract_cfunc_numpy_ufunc(self, obj, pyname):
        ufunc = PyUFuncObject.from_address(id(obj))
        func_array_ptr = ufunc.functions
        num_funcs = ufunc.ntypes
        function_pointers = []
        i = 0
        while i < num_funcs:
            function_pointers.append(func_array_ptr[i])
            i += 1

        log.debug(f'pyname = {pyname}, len_pointers = {len(function_pointers)}, pointers = {function_pointers}')

        ret = 0
        for addr in function_pointers:
            ret += self.decide_bridge(pyname, addr)

        return ret

    def extract_cfunc_pybind11(self, obj, pyname):
        capsule = ctypes.cast(id(obj), ctypes.POINTER(PyCapsule))
        func_record = ctypes.cast(capsule[0].pointer, ctypes.POINTER(FunctionRecord))

        ret1 = -1
        ret2 = -1

        impl = func_record[0].impl
        ret1 = self.decide_bridge(pyname, impl)

        data = func_record[0].data[0]
        if data is not None:
            ret2 = self.decide_bridge(pyname, data)

        if ret1 < 0 and ret2 < 0:
            return -1
        else:
            return 0


    def try_import(self, name):
        pairs = get_import_name_pairs(name)
        found = []
        for m, rest in pairs:
            log.debug(f'm = {m}, rest = {rest}')
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
                    obj = getattr(obj, o)
                except Exception as e:
                    obj = None
                    success = False
                    log.debug(e)
                    break
            if success:
                found.append(obj)
        if len(found) == 0:
            log.warn(f"No object for pyname {name} found")
        return found

    def internal_analyze_single(self, candidate):
        log.debug(f"internal candidate = {candidate}")
        clean = candidate.replace('/', '.')
        clean = clean.lstrip('.')
        try:
            objs = self.try_import(clean)
        except Exception as e:
            log.error("analyze_single: %s" % e)
            raise

        for obj in objs:
            self.check_bingo(obj, candidate)

    def external_analyze_single(self, candidate):
        if '.builtin' in candidate:
            return
        clean = candidate.split("//")[-1]
        try:
            objs = self.try_import(clean)
        except Exception as e:
            log.error("analyze_single: %s" % e)
            raise
        for obj in objs:
            self.check_bingo(obj, candidate)


    def process(self):
        sys.path.insert(0, self.sysdir_path)
        log.debug(f'ANALYZE_CANDIDATES, PROCESSING {self.package}')
        for c in self.candidates['internal']:
            self.internal_analyze_single(c)
        for c in self.candidates['external']:
            self.external_analyze_single(c)
        sys.path.pop(0)
        log.info('Running GDB')
        gdb_output = run_gdb(self.symbol_addresses)
        for line in gdb_output.splitlines():
            hop = parse_gdb_line(line)
            if hop is not None:
                self.hops.append(hop)
        if (len(self.symbol_addresses) != len(self.hops)):
            log.info(("len(symbol_addresses) = %s != %s = len(hops)"
                   % (len(self.symbol_addresses), len(self.hops))))
        else:
            log.info("len(hops) = %s" % len(self.hops))

        log.info("len(pyname_addr_pairs) = %s" % len(self.pyname_addr_pairs))

        log.info(f"EXCLUDE_LIBS = {EXCLUDE_LIBS}")

        bridges = []

        for p in self.pyname_addr_pairs:
            found = False
            for h in self.hops:
                if p["address"] == h.address:
                    found = True
                    if h.library not in EXCLUDE_LIBS and h.library not in self.ignored_libs:
                        pkg_ver_uuid = os.path.basename(self.sysdir_path)
                        root_norm = os.path.normpath(self.sysdir_path)
                        lib_norm = os.path.normpath(h.library)
                        if os.path.commonpath([root_norm, lib_norm]) == root_norm:
                            jl_clean = os.path.relpath(h.library, start=self.sysdir_path)
                            bridges.append(objects.PyCBridge(p['pyname'], h.cfunc, jl_clean))
                            self.jump_libs.add(jl_clean)
                        else:
                            log.debug(f"{lib_norm} is not child of root {root_norm}. Ignoring...")
                            self.ignored_libs.add(lib_norm)
                    h.pyname = p["pyname"]
                    continue
            if not found:
                log.warning(f"No symbol found for pyname {p['pyname']}")
                pass

        result = {'count_internal': None, 'count_external': None, 'jump_libs': list(self.jump_libs),
                  'ignored_libs': list(self.ignored_libs), 'internal': [], 'external': []}
        for b in bridges:
            if b.pyname.startswith('//'):
                result['external'].append(b.to_dict())
            else:
                result['internal'].append(b.to_dict())
        result['count_internal'] = len(result['internal'])
        result['count_external'] = len(result['external'])
        if self.output_file is None:
            log.info(json.dumps(result, indent=2))
        else:
            with open(self.output_file, 'w') as outfile:
                outfile.write(json.dumps(result, indent=2))

def do_one(candidates_path, sysdir_path, output_file, pkg):
    analyzer = Analyzer(candidates_path, sysdir_path, output_file, pkg)
    analyzer.process()


def main():
    args = parse_args()
    setup_logging(args)
    if args.input is None:
        log.error("Must give input file path")
        sys.exit(1)
    json_path = args.input
    if not os.path.exists(json_path):
        log.error(f"Input file {json_path} does not exist")
        sys.exit(1)
    output_file = args.output
    if args.package is None:
        log.warning("No package name given. Candidate resolution might fail...")
    analyzer = Analyzer(args.input, args.sysdir, output_file, args.package)
    analyzer.process()

if __name__ == "__main__":
    main()
