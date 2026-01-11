import argparse
import os
from pathlib import Path
import re
import base64
import zlib
import json
from typing import List, Union, Tuple, TYPE_CHECKING
import logging

import pyhidra

pyhidra.start(True)

if TYPE_CHECKING:
    import ghidra
    from ghidra_builtins import *

from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.listing import Function

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
    p = argparse.ArgumentParser(description='Generate a call graph for a given binary using Ghidra.')

    p.add_argument(
        "-i",
        "--input",
        default=None,
        help=("Provide path to input binary file."),
    )
    p.add_argument(
        "-d",
        "--dir",
        default=None,
        help=("Directory to store Ghidra project."),
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help=("Output file."),
    )
    p.add_argument(
        "-n",
        "--name",
        default=None,
        help=("Provide library fullpath include in library field of JSON."),
    )
    p.add_argument(
        "-l",
        "--log",
        default="info",
        help=("Provide logging level. Example --log debug"),
    )

    return p.parse_args()

class CallGraphGenerator():
    def __init__(self, bin_path, project_location, project_name, lib_name):
        self.n2idx = {}
        self.idx2n = {}
        self.nodes = {}
        self.edges = []
        self.lib_name = lib_name
        self.cg = None
        self.next_index = 0
        self.bin_path = bin_path
        self.project_location = project_location
        self.project_name = project_name
        self.monitor = ConsoleTaskMonitor()

    def get_and_bump_idx(self):
        ret = self.next_index
        self.next_index += 1
        return ret

    def generate_cg(self):
        with pyhidra.open_program(self.bin_path, project_location=self.project_location, project_name=self.project_name, analyze=False) as flat_api:
            from ghidra.program.util import GhidraProgramUtilities
            from ghidra.app.script import GhidraScriptUtil

            program: "ghidra.program.model.listing.Program" = flat_api.getCurrentProgram()


            if GhidraProgramUtilities.shouldAskToAnalyze(program):
                GhidraScriptUtil.acquireBundleHostReference()
                flat_api.analyzeAll(program)
                GhidraProgramUtilities.markProgramAnalyzed(program)
                GhidraScriptUtil.releaseBundleHostReference()

            all_funcs = program.functionManager.getFunctions(True)
            st = program.getSymbolTable()

            for f in all_funcs:
                called = []
                calling = []
                lh = st.getLabelHistory(f.getEntryPoint())
                fullname = lh[0].labelString
                if fullname not in self.n2idx.keys():
                    new_idx = self.get_and_bump_idx()
                    node = {'name': fullname}
                    self.n2idx[fullname] = new_idx
                    self.idx2n[new_idx] = fullname
                    self.nodes[new_idx] = node

            all_funcs = program.functionManager.getFunctions(True)
            for src in all_funcs:
                lh = st.getLabelHistory(src.getEntryPoint())
                srcname = lh[0].labelString
                called = src.getCalledFunctions(self.monitor)
                for dst in called:
                    lh = st.getLabelHistory(dst.getEntryPoint())
                    dstname = lh[0].labelString
                    edge = [self.n2idx[srcname], self.n2idx[dstname]]
                    if edge not in self.edges:
                        self.edges.append(edge)

            all_funcs = program.functionManager.getFunctions(True)
            for dst in all_funcs:
                lh = st.getLabelHistory(dst.getEntryPoint())
                dstname = lh[0].labelString
                calling = dst.getCallingFunctions(self.monitor)
                for src in calling:
                    lh = st.getLabelHistory(src.getEntryPoint())
                    srcname = lh[0].labelString
                    edge = [self.n2idx[srcname], self.n2idx[dstname]]
                    if edge not in self.edges:
                        self.edges.append(edge)


            cg = {'library': self.lib_name, 'edges': self.edges, 'nodes': self.nodes}
            return cg


def main():
    args = parse_args()
    setup_logging(args)
    print(args)

    bin_path = Path(args.input)
    if args.dir is not None:
        project_location = os.path.join(args.dir, '.ghidra_projects')
    else:
        project_location = Path('.ghidra_projects')

    generator = CallGraphGenerator(bin_path, project_location, bin_path.name, args.name)
    result = generator.generate_cg()

    if args.output is None:
        log.info(json.dumps(result, indent=2))
    else:
        dir = os.path.dirname(args.output)
        if dir:
            os.makedirs(dir, exist_ok=True)
        with open(args.output, 'w') as outfile:
            outfile.write(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
