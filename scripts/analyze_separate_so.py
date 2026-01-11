import os
import gc
import time
import re
import sys
import queue
import ctypes
import types
import logging
import argparse
import importlib
import json
import multiprocessing

from pathlib import Path

import subprocess
import tempfile

import objects
import utils

EXCLUDE_LIBS = [str(Path(sys.executable).resolve())]

log = logging.getLogger(__name__)

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
    p = argparse.ArgumentParser(description='Process a Python package, produce bridges.')
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
        "-p",
        "--packages",
        nargs='+',
        help=("Package names. Used to construct FQNs when missing info."),
    )
    p.add_argument(
        "-n",
        "--naked",
        nargs='+',
        help=("Naked modules under sysdir. Sometimes happens."),
    )
    p.add_argument(
        "-s",
        "--sysdir",
        default=None,
        help=("Optionally extend sys.path with this path. Example -s /tmp/mypackages"),
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
        # print("script = %s" % script)

        # XXX: Need sudo, because otherwise can't trace process.
        gdb_launch_cmd = f'sudo gdb --batch -ex "source {cmd_file_path}" --pid {pid_self_str}'
        # print("LAUNCH_CMD = %s" % gdb_launch_cmd)
        # try:
        #     ret, out, err = utils.run_cmd(gdb_launch_cmd, timeout=None, shell=True)
        # except Exception as e:
        #     log.error(e)
        #     raise
        # if ret != 0:
        #     log.error(f"cmd {cmd} returned non-zero exit code {ret}")
        #     # log.info(out)
        #     log.info(err)
        #     raise RuntimeError('GDB RUN FAILED')
        #
        # return out

        # Use shell=True plus a single argument string cause otherwise GDB acts up.

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
        # log.debug(f"STDOUT = {stdout}")
        # log.debug(f"STDERR = {stderr}")
        fout.close()
        ferr.close()
        try:
            os.remove(fout.name)
            os.remove(ferr.name)
        except Exception as e:
            log.debug(e)
        return stdout

# from Include/object.h:
class PyObject(ctypes.Structure):
    _fields_ = [
        ('ob_refcnt', ctypes.c_size_t),
        ('ob_type', ctypes.py_object),
    ]


# XXX: Pybind11
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

#     _fields_ = [
#         ("name", ctypes.c_char_p),
#         ("get", ctypes.c_void_p),
#         ("set", ctypes.c_void_p),
#         ("doc", ctypes.c_char_p),
#         ("closure", ctypes.c_void_p),
#     ]

class PyGetSetDef(ctypes.Structure):
    _fields_ = [
        ('name', ctypes.c_char_p),
        ('get', ctypes.c_void_p),
        ('set', ctypes.c_void_p),
        ('doc', ctypes.c_char_p),
        ('closure', ctypes.c_void_p),
    ]

class PyGetSetDescrObject(ctypes.Structure):
    _fields_ = [
        ('descr_common', PyDescrObject),
        ('d_getset', ctypes.POINTER(PyGetSetDef)),
    ]

PyObject_p = ctypes.py_object
Py_ssize_t = ctypes.c_ssize_t
class PyTypeObject(ctypes.Structure):
    _fields_ = [
    ('ob_base', PyObject),
    ('ob_size', Py_ssize_t),
    ('tp_name', ctypes.c_char_p),
    ('tp_basicsize', ctypes.c_void_p),
    ('tp_itemsize', Py_ssize_t),
    ('tp_dealloc', ctypes.c_void_p),
    ('tp_vectorcall_offset', Py_ssize_t),
    ('tp_getattr', ctypes.c_void_p),
    ('tp_setattr', ctypes.c_void_p),
    ('tp_as_async', ctypes.c_void_p),
    ('tp_repr', ctypes.c_void_p),
    ('tp_as_number', ctypes.c_void_p),
    ('tp_as_sequence', ctypes.c_void_p),
    ('tp_as_mapping', ctypes.c_void_p),
    ('tp_hash', ctypes.c_void_p),
    ('tp_call', ctypes.c_void_p),
    ('tp_str', ctypes.c_void_p),
    ('tp_getattro', ctypes.c_void_p),  # Type not declared yet
    ('tp_setattro', ctypes.c_void_p),  # Type not declared yet
    ('tp_as_buffer', ctypes.c_void_p),  # Type not declared yet
    ('tp_flags', ctypes.c_ulong),  # Type not declared yet
    ('tp_doc', ctypes.c_char_p),  # Type not declared yet
    ('tp_traverse', ctypes.c_void_p),  # Type not declared yet
    ('tp_clear', ctypes.c_void_p),  # Type not declared yet
    ('tp_richcompare', ctypes.c_void_p),  # Type not declared yet
    ('tp_weaklistoffset', Py_ssize_t),  # Type not declared yet
    ('tp_iter', ctypes.c_void_p),  # Type not declared yet
    ('tp_iternext', ctypes.c_void_p),  # Type not declared yet
    ('tp_methods', ctypes.c_void_p),  # Type not declared yet
    ('tp_members', ctypes.c_void_p),  # Type not declared yet
    ('tp_getset', ctypes.POINTER(PyGetSetDef)),  # Type not declared yet
    ('tp_base', ctypes.c_void_p),  # Type not declared yet
    ('tp_dict', ctypes.c_void_p),  # Type not declared yet
    ('tp_descr_get', ctypes.c_void_p),  # Type not declared yet
    ('tp_descr_set', ctypes.c_void_p),  # Type not declared yet
    ('tp_dictoffset', Py_ssize_t),
    ('tp_init', ctypes.c_void_p),
    ('tp_alloc', ctypes.c_void_p),
    ('tp_new', ctypes.c_void_p),
    ('tp_free', ctypes.c_void_p),
    ('tp_is_gc', ctypes.c_void_p), # For PyObject_IS_GC
    ('tp_bases', ctypes.c_void_p),
    ('tp_mro', ctypes.c_void_p),
    ('tp_cache', ctypes.c_void_p),
    ('tp_subclasses', ctypes.c_void_p),
    ('tp_weaklist', ctypes.c_void_p),
    ('tp_del', ctypes.c_void_p),
    ('tp_version_tag', ctypes.c_uint),
    ('tp_finalize', ctypes.c_void_p),
    ('tp_vectorcall', ctypes.c_void_p),]

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
        log.debug("Could not match pat for line:\n %s" % line)

    return ret

def is_dunder(attr):
    return attr.startswith('__') and attr.endswith('__')

class Analyzer():
    def __init__(self, package_path, sysdir_path, module_path, output_file):
        self.is_native_extension = False
        self.module_path = module_path
        self.package_path = package_path
        self.mod_import_name = None
        self.sysdir_path = sysdir_path
        self.package_name = os.path.basename(self.sysdir_path).split('___')[0]
        self.package_version = os.path.basename(self.sysdir_path).split('___')[1]
        self.relimp_name = os.path.basename(package_path)
        self.visited = set()
        self.output_file = output_file
        self.symbol_addresses = set()
        self.addr2pyname = {}
        self.pyname_addr_pairs = []
        self.hops = []
        self.mod_pointers = []
        self.jump_libs = set()
        self.modules = []
        self.max_recurse_depth = 1000000
        self.types_encountered = {}

        self.objects_examined = 0
        self.callable_objects = 0
        self.foreign_callable_objects = 0

    def check_bingo(self, obj, pyname):
        self.foreign_callable_objects += 1
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
        elif "cython_function" in type(obj).__name__:
            ret = self.extract_cfunc_pycfunction(obj, pyname)
        elif type(obj).__name__ == 'ufunc' and (hasattr(obj, 'nin') and hasattr(obj, 'nout')):
            ret = self.extract_cfunc_numpy_ufunc(obj, pyname)

        elif type(obj) == types.GetSetDescriptorType:
            if not self.package_name == 'grpcio':
                ret = self.extract_cfunc_getsetdescriptor(obj, pyname)
        else:
            try:
                if isinstance(obj, type):
                    ret = self.extract_cfunc_auxfuncs(obj, pyname)
                else:
                    x = getattr(obj, '__self__', None)
                    if isinstance(x, type):
                        ret = self.extract_cfunc_auxfuncs(x, pyname)
                    ret = self.extract_cfunc_auxfuncs(type(obj), pyname)
            except Exception as e:
                log.debug(e)

        return ret

    def recursive_inspect(self, obj, pyname, current_module, depth):
        pending = [[obj, pyname]]
        cur_dotlength = len(pyname.split('.'))
        already_seen = 0
        self.seen = set()
        self.types_encountered = {}
        lendir_lastn = []
        pending_ptypes = {}
        ignore_types = set()
        visited = 0

        prev_toptype = None

        default_types = [types.FunctionType,
                     types.GeneratorType, types.CoroutineType,
                     types.AsyncGeneratorType, types.CodeType,
                     types.CellType, types.MethodType,
                     types.BuiltinFunctionType, types.WrapperDescriptorType,
                     types.MethodWrapperType,
                     types.MethodDescriptorType, types.ClassMethodDescriptorType,
                     types.ModuleType,
                     types.GenericAlias,
                     types.FrameType,
                     types.MemberDescriptorType, types.MappingProxyType]


        while len(pending) > 0:
            obj, pyname = pending.pop(0)
            if 'np.ma' in pyname:
                continue
            if 'Timestamp' in pyname:
                continue

            tobj = type(obj)
            if tobj in ignore_types:
                continue

            visited += 1
            if visited % 10000 == 0:
                log.debug(f"Visited: {visited}")

            dotlength = len(pyname.split('.'))
            if dotlength > cur_dotlength:
                cur_dotlength = dotlength
                log.debug(f"current max length: {cur_dotlength}")

            ret = self.check_bingo(obj, pyname)
            if ret < 0:
                continue

            for k in dir(obj):
                try:
                    v = getattr(obj, k)
                except Exception as e:
                    continue
                ident = (id(v), type(v))
                self.objects_examined += 1
                if callable(v):
                    self.callable_objects += 1
                if ident in self.seen:
                    already_seen += 1
                    continue
                else:
                    self.seen.add(ident)
                vtype = type(v)
                if vtype == types.ModuleType:
                    if hasattr(v, '__file__'):
                        p = getattr(v, '__file__')
                        try:
                            log.debug(f"self.package_path = {self.package_path}")
                            log.debug(f"p = {p}")
                            if os.path.commonpath([self.package_path, p]) != self.package_path:
                                log.debug(f"Ignoring module {k} with file {p}")
                                continue
                            else:
                                if p not in self.seen:
                                    log.debug(f"Accepting module {k} with file {p}")
                                    self.seen.add(p)
                                else:
                                    continue
                        except Exception as e:
                            log.debug(e)
                            continue

                if vtype in ignore_types:
                    log.debug(f"Ignoring type {vtype}")
                    continue
                if tobj not in default_types and v.__class__.__module__ != 'builtins':
                    if tobj not in pending_ptypes.keys():
                        pending_ptypes[tobj] = 1
                    else:
                        pending_ptypes[tobj] += 1

                pending.append([v, pyname + '.' + k])
                if len(pending) > 0 and len(pending) % 100000 == 0:
                    log.debug(f"Pending: {len(pending)}")
                if len(pending) % 200000 == 0:
                    log.debug(f"Pending: {len(pending)}")
                    log.debug(f"Pending parent types:")
                    stotal = sum(pending_ptypes.values())
                    if stotal > 0:
                        pcts = []
                        for tk, tv in pending_ptypes.items():
                            pct = round((tv/stotal) * 100, 2)
                            pcts.append([tk, pct])
                        pcts = sorted(pcts, key=lambda x: x[1], reverse=True)
                        for pct in pcts[:10]:
                            log.debug(f"{pct[0]}: {pct[1]}")
                        curr_toptype = pcts[0][0]
                        if curr_toptype == prev_toptype:
                            log.debug(f"Henceforth ignoring type: {curr_toptype}")
                            ignore_types.add(curr_toptype)
                            del pending_ptypes[curr_toptype]
                        else:
                            prev_toptype = curr_toptype

            self.seen.add((id(obj), type(obj)))

    def decide_bridge(self, pyname, addr):
        if addr not in self.symbol_addresses:
            self.symbol_addresses.add(addr)
            self.addr2pyname[addr] = pyname
            # self.pyname_addr_pairs.append({"pyname": pyname, "address": addr})
            return 0
        else:
            pass
            # if not pyname.startswith("PEEK_GC") and self.addr2pyname[addr].startswith("PEEK_GC"):
            #     self.addr2pyname[addr] = pyname


            return -1

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

    def extract_cfunc_getsetdescriptor(self, obj, pyname):
        function_pointers = []
        descr = PyGetSetDescrObject.from_address(id(obj))
        gsd = descr.d_getset[0]
        if gsd is not None:
            if gsd.get is not None:
                function_pointers.append(gsd.get)
            if gsd.set is not None:
                function_pointers.append(gsd.set)

        found_one = False
        for f in function_pointers:
            ret = self.decide_bridge(pyname, f)
            if ret == 0:
                found_one = True
        if found_one:
            return 0
        else:
            return -1

    def extract_cfunc_auxfuncs(self, obj, pyname):
        if not isinstance(obj, type):
            return

        self.objects_examined += 22

        addr = id(obj)

        type_struct = PyTypeObject.from_address(addr)
        function_pointers = []

        name = type_struct.tp_name.decode('utf-8')
        # log.info(f"PYNAME = {pyname}")
        # log.info(f"TYPE NAME = {name}")
        # if pyname.startswith("PEEK_GC"):
        #     # log.info("INSIDE")
        #     pyname = name
        if self.package_name not in PACKAGES_3:
            deallocfunc = type_struct.tp_dealloc
            if deallocfunc is not None:
                function_pointers.append(deallocfunc)

        getattrfunc = type_struct.tp_getattr
        if getattrfunc is not None:
            function_pointers.append(getattrfunc)

        setattrfunc = type_struct.tp_setattr
        if setattrfunc is not None:
            function_pointers.append(setattrfunc)

        reprfunc = type_struct.tp_repr
        if reprfunc is not None:
            function_pointers.append(reprfunc)

        hashfunc = type_struct.tp_hash
        if hashfunc is not None:
            function_pointers.append(hashfunc)

        callfunc = type_struct.tp_call
        if callfunc is not None:
            function_pointers.append(callfunc)

        getattrofunc = type_struct.tp_getattro
        if getattrofunc is not None:
            function_pointers.append(getattrofunc)

        setattrofunc = type_struct.tp_setattro
        if setattrofunc is not None:
            function_pointers.append(setattrofunc)

        traversefunc = type_struct.tp_traverse
        if traversefunc is not None:
            function_pointers.append(traversefunc)

        clearfunc = type_struct.tp_clear
        if clearfunc is not None:
            function_pointers.append(clearfunc)

        richcomparefunc = type_struct.tp_richcompare
        if richcomparefunc is not None:
            function_pointers.append(richcomparefunc)

        iterfunc = type_struct.tp_iter
        if iterfunc is not None:
            function_pointers.append(iterfunc)

        iternextfunc = type_struct.tp_iternext
        if iternextfunc is not None:
            function_pointers.append(iternextfunc)

        descr_getfunc = type_struct.tp_descr_get
        if descr_getfunc is not None:
            function_pointers.append(descr_getfunc)

        descr_setfunc = type_struct.tp_descr_set
        if descr_setfunc is not None:
            function_pointers.append(descr_setfunc)

        initfunc = type_struct.tp_init
        if initfunc is not None:
            function_pointers.append(initfunc)

        allocfunc = type_struct.tp_alloc
        if allocfunc is not None:
            function_pointers.append(allocfunc)

        newfunc = type_struct.tp_new
        if newfunc is not None:
            function_pointers.append(newfunc)

        freefunc = type_struct.tp_free
        if freefunc is not None:
            function_pointers.append(freefunc)

        is_gcfunc = type_struct.tp_is_gc
        if is_gcfunc is not None:
            function_pointers.append(is_gcfunc)

        delfunc = type_struct.tp_del
        if delfunc is not None:
            function_pointers.append(delfunc)

        finalizefunc = type_struct.tp_finalize
        if finalizefunc is not None:
            function_pointers.append(finalizefunc)

        vectorcallfunc = type_struct.tp_vectorcall
        if vectorcallfunc is not None:
            function_pointers.append(vectorcallfunc)

        self.callable_objects += len(function_pointers)


        found_one = False
        for f in function_pointers:
            ret = self.decide_bridge(pyname, f)
            if ret == 0:
                found_one = True
        return 0

    def peek_gc(self):
        i = 0
        for obj in gc.get_objects():
            self.objects_examined += 1
            if callable(obj):
                self.callable_objects += 1
            i += 1
            pyname = f'PEEK_GC_{i}'
            self.check_bingo(obj, pyname)

    def inspect_module(self):
        log.debug(f"module_path = {self.module_path}, package_path = {self.package_path}")
        self.mod_import_name = utils.get_mod_import_name(self.module_path, self.package_path)
        # # XXX: Hacky fix for opencv-python
        # if self.mod_import_name == 'cv2.cv2':
        #     self.mod_import_name = 'cv2'
        log.debug(f"mod_import_name: {self.mod_import_name}")
        try:
            module = importlib.import_module(self.mod_import_name)

            self.is_native_extension = True
            self.mod_basename = self.mod_import_name.split(".")[-1]
            self.recursive_inspect(module, self.mod_import_name, self.module_path, 0)
            # XXX: Uncomment to enable GC introspection
            # self.peek_gc()
            self.modules.append({'path': self.module_path, 'import_name': self.mod_import_name})
            sorted_types = {k: v for k, v in sorted(self.types_encountered.items(), key=lambda item: item[1], reverse=True)}
            log.debug(sorted_types)
            log.debug(f"TOTAL VISITED: {len(self.seen)}")
        except Exception as e:
            log.debug(f"Exception {e} while processing Module {self.module_path} with import name {self.mod_import_name}.")


    def analyze(self):
        sys.path.insert(0, self.sysdir_path)
        # # XXX: Hacky fix for opencv-python
        # if 'opencv-python' in self.sysdir_path:
        #     sys.path.insert(0, self.sysdir_path + 'cv2')

        self.inspect_module()

        gdb_output = run_gdb(self.symbol_addresses)
        for line in gdb_output.splitlines():
            hop = parse_gdb_line(line)
            if hop is not None:
                self.hops.append(hop)
        if (len(self.symbol_addresses) != len(self.hops)):
            log.debug(("len(symbol_addresses) = %s != %s = len(hops)"
                   % (len(self.symbol_addresses), len(self.hops))))
        else:
            log.debug("len(hops) = %s" % len(self.hops))

        for addr, pyname in self.addr2pyname.items():
            self.pyname_addr_pairs.append({"pyname": pyname, "address": addr})

        log.debug("len(pyname_addr_pairs) = %s" % len(self.pyname_addr_pairs))

        bridges = []

        all_libs = set()

        for p in self.pyname_addr_pairs:
            found = False
            ignored = False
            for h in self.hops:
                all_libs.add(h.library)
                if p["address"] == h.address:
                    found = True
                    lib_path = os.path.abspath(h.library)
                    if os.path.commonpath([lib_path, self.sysdir_path]) == self.sysdir_path:
                        pkg_ver_uuid = os.path.basename(self.sysdir_path)
                        root_norm = os.path.normpath(self.sysdir_path)
                        lib_norm = os.path.normpath(h.library)
                        jl_clean = os.path.join(pkg_ver_uuid, os.path.relpath(h.library, start=self.sysdir_path))
                        bridges.append(objects.PyCBridge(p['pyname'], h.cfunc, jl_clean).to_dict())
                        self.jump_libs.add(jl_clean)
                    else:
                        ignored = True
                    h.pyname = p["pyname"]
                    continue
            if not found and not ignored:
                log.debug(f"No symbol found for pyname {p['pyname']}")

        if self.is_native_extension:
            pkg_ver_uuid = os.path.basename(self.sysdir_path)
            jl_clean = os.path.join(pkg_ver_uuid, os.path.relpath(self.module_path, start=self.sysdir_path))
            bridges.append(objects.PyCBridge("___IMPORT___", "PyInit_" + self.mod_basename, jl_clean).to_dict())
        log.debug(f"ALL LIBS WITH HOPS = {all_libs}")

        result = {'count': len(bridges), 'modules': self.modules,
                  'jump_libs': list(self.jump_libs), 'bridges': bridges,
                  'objects_examined': self.objects_examined,
                  'callable_objects': self.callable_objects,
                  'foreign_callable_objects': self.foreign_callable_objects}
        return result

def locate_somodules(package_path):
    so_files = []
    for root, _, files in os.walk(package_path):
        for file in files:
            if file.endswith(".so"):
                so_files.append(os.path.join(root, file))
    return so_files

def update_big(big, res):
    rm = res['modules']
    bm = big['modules']
    for m in rm:
        if m not in bm:
            bm.append(m)
    big['modules'] = bm
    rjl = res['jump_libs']
    bjl = big['jump_libs']
    for jl in rjl:
        if jl not in bjl:
            bjl.append(jl)
    big['jump_libs'] = bjl
    rb = res['bridges']
    bb = big['bridges']
    for new in rb:
        found = False
        for old in bb:
            if (new['cfunc'] == old['cfunc'] and new['library'] == old['library']):
                found = True
        if not found:
            bb.append(new)
    big['bridges'] = bb
    big['objects_examined'] += res['objects_examined']
    big['callable_objects'] += res['callable_objects']
    big['foreign_callable_objects'] += res['foreign_callable_objects']

    return big


def analyze_single(pkg, sysdir, so_file, output, queue):
    analyzer = Analyzer(pkg, sysdir, so_file, output)
    res = analyzer.analyze()
    queue.put(res)


def main():
    start_time = time.time()

    args = parse_args()
    setup_logging(args)
    if args.packages is None and args.naked is None:
        log.error("Must give at least one package root path or naked")
        sys.exit(1)

    packages_so_map = {}
    if args.packages is not None:
        for p in args.packages:
            if not os.path.exists(p):
                log.warning(f"No directory for package {p} found. Ignoring...")
                continue
            so_files = locate_somodules(p)
            log.info(f"Shared object files in package {p}: {so_files}")
            packages_so_map[p] = so_files

    if args.naked is not None:
        packages_so_map['naked'] = args.naked

    big = {'objects_examined': 0, 'callable_objects': 0, 'foreign_callable_objects': 0,
           'duration_sec': 0,
           'count': 0, 'modules': [], 'jump_libs': [], 'bridges': []}
    mpq = multiprocessing.Queue()
    for pkg, so_files in packages_so_map.items():
        for so_file in so_files:
            p = multiprocessing.Process(target=analyze_single, args=(pkg, args.sysdir, so_file, args.output, mpq))
            p.start()
            while True:
                try:
                    res = mpq.get(timeout=30)
                    big = update_big(big, res)
                    p.join()
                    break
                except queue.Empty as e:
                    if not p.is_alive():
                        break
                    continue

    end_time = time.time()

    duration = end_time - start_time
    duration_sec = round(duration)
    big['duration_sec'] = duration_sec

    log.info(f"Duration (seconds): {big['duration_sec']}")
    log.info(f"Total Bridges Found: {len(big['bridges'])}")
    log.info(f"Objects Examined: {big['objects_examined']}")
    log.info(f"Callable Objects Examined: {big['callable_objects']}")
    log.info(f"Foreign-callable Objects Examined: {big['foreign_callable_objects']}")
    big['count'] = len(big['bridges'])

    if args.output is None:
        log.info(json.dumps(big, indent=2))
    else:
        with open(args.output, 'w') as outfile:
            outfile.write(json.dumps(big, indent=2))

if __name__ == "__main__":
    main()
