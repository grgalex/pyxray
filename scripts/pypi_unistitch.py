import os
import sys
import json
import argparse
import logging
from pathlib import Path
import shutil
import multiprocessing
import concurrent.futures
import tempfile

import starbinstitch
import utils
import find_candidates
import analyze_candidates
import augment_partial_cg
import unify_cg_all_binary
import sbs

log = logging.getLogger(__name__)

PRV_PYHIDRA_ROOT = '/prv-pyhidra-cg'

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
        "-i",
        "--input",
        default=None,
        help=("Provide path to the CSV containing the user/repo pairs"),
    )
    p.add_argument(
        "-A",
        "--always",
        default=False,
        action='store_true',
        help=("Always generate artifacts, never reuse existing stuff."),
    )
    p.add_argument(
        "-B",
        "--binary-always",
        default=False,
        action='store_true',
        help=("Always generate binary artifacts, never reuse existing stuff."),
    )
    p.add_argument(
        "-S",
        "--use-sbs",
        default=False,
        action='store_true',
        help=("Stitch with SBS instead of raw binary callgraphs."),
    )
    return p.parse_args()

class UnifiedStitcher():
    def __init__(self, package, always, use_sbs, binary_always):
        self.always = always
        self.use_sbs = use_sbs
        self.package = package
        self.binary_always = binary_always
        self.name = package.split(':')[0]
        self.version = package.split(':')[1]
        self.git_root = utils.find_git_root()
        if self.git_root is None:
            log.error(f"CWD is outside Xray git repo.")
            return
        else:
            log.info(f"Git Root: {self.git_root}")
        self.n2cgpath = None

        self.namesnip = self.name[0] + '/' + self.name + '/' + self.version

        self.tempinst_uuid = self.name + '___' + self.version
        self.tmp_install_dir_root = os.path.join(self.git_root, 'data/install')
        self.tmp_install_dir = os.path.join(self.tmp_install_dir_root, self.tempinst_uuid)
        self.tmp_install_dir_toplevel_root = os.path.join(os.path.join(self.git_root, 'data/install_toplevel', self.tempinst_uuid + '___TOPLEVEL'))

        self.deps_dir_root = os.path.join(self.git_root, 'data/dependencies')
        self.deps_dir = os.path.join(self.deps_dir_root, self.namesnip)
        self.deps_path = os.path.join(self.deps_dir, 'deps.json')
        self.deps = []

        self.partial_cg_root = os.path.join(self.git_root, 'data/partial_callgraphs')

        self.bridges_root = os.path.join(self.git_root, 'data/bridges')
        self.bridges_apps_root = os.path.join(self.git_root, 'data/bridges/pypi')

        self.augmented_cg_root = os.path.join(self.git_root, 'data/augmented_partial_cg/pypi')
        self.augmented_cg_dir = os.path.join(self.augmented_cg_root, self.namesnip)

        self.augstitched_cg_root = os.path.join(self.git_root, 'data/augstitched_cg/pypi')
        self.augstitched_cg_dir = os.path.join(self.augstitched_cg_root, self.namesnip)
        self.augstitched_cg_path = os.path.join(self.augstitched_cg_dir, 'augstitched.json')
        self.stitching_stats_path = os.path.join(self.augstitched_cg_dir, 'stats.json')

        self.unified_cg_root = os.path.join(self.git_root, 'data/unified_cg/pypi')
        self.unified_cg_dir = os.path.join(self.unified_cg_root, self.namesnip)
        self.unified_cg_path = os.path.join(self.unified_cg_dir, 'unified.json')

        self.bcg_root = os.path.join(self.git_root, 'data/binary_callgraphs')
        self.lib2bcg = {}
        self.pkg2pcg = {}
        self.pkg2pcg_path = os.path.join(self.bridges_apps_root, self.namesnip, 'pkg2pcg.json')
        self.tl2pkg = {}
        self.tl2pkg_path = os.path.join(self.bridges_apps_root, self.namesnip, 'tl2pkg.json')
        self.first_comp2pkg = {}
        self.first_comp2pkg_path = os.path.join(self.bridges_apps_root, self.namesnip, 'first_comp2pkg.json')
        self.pkg2aug = {}
        self.pkg2aug_path = os.path.join(self.bridges_apps_root, self.namesnip, 'pkg2aug.json')

        self.libs = set()
        self.lib2pkg = {}

        self.all_libs = None

        self.sbs_paths = set()

        utils.create_dir(os.path.join(self.bridges_apps_root, self.namesnip))

    def load_dependencies(self):
        log.info(f"Loading dependencies of {self.package} from {self.deps_path}")
        try:
            with open(self.deps_path, 'r') as infile:
                self.deps = json.loads(infile.read())
        except Exception as e:
            log.error(e)
            return -1

        return 0

    def find_toplevels(self):
        log.info(f"Finding top_level import names for {self.package}")
        skip_install = False
        if os.path.exists(self.tl2pkg_path) and os.path.exists(self.first_comp2pkg_path):
            with open(self.tl2pkg_path, 'r') as infile:
                self.tl2pkg = json.loads(infile.read())
            with open(self.first_comp2pkg_path, 'r') as infile:
                self.first_comp2pkg = json.loads(infile.read())
            log.info('in here')
            return
        if os.path.exists(self.tmp_install_dir_toplevel_root) and not self.always:
            log.info(f"Temp TOPLEVEL install dir for {self.package} already exists at {self.tmp_install_dir_toplevel_root} - Skipping...")
            log.info(f"Use -A to force recreation.")
            # manual = True
        else:
            try:
                utils.create_dir(self.tmp_install_dir_toplevel_root)
            except FileExistsError as e:
                log.warning(e)
        # if manual:
        #     all_packages = self.deps
        # else:
        #     all_packages = [self.package] + self.deps
        all_packages = [self.package] + self.deps
        for dep in all_packages:
            log.info(f"Processing dep {dep}")
            (pkg, version) = utils.pkg_name_to_tuple(dep)
            install_dir = os.path.join(self.tmp_install_dir_toplevel_root, pkg + '___' + version)
            if not skip_install:
                cmd = [
                    'pip3',
                    'install',
                    '-t', install_dir,
                    '--no-deps',
                    '--no-binary', 'Pillow',
                    "{}=={}".format(pkg, version)
                ]
                try:
                    ret, out, err = utils.run_cmd(cmd)
                except Exception as e:
                    log.error(e)
                    return -1
                if ret != 0:
                    log.error(f"cmd {cmd} returned non-zero exit code {ret}")
                    log.info(out)
                    log.info(err)
                    if os.path.exists(install_dir):
                        shutil.rmtree(install_dir)
                    return ret
            if not os.path.exists(install_dir):
                log.error(f"Install dir {install_dir} does not exist post-installation. Aborting!")
                return -1

            root_path = Path(install_dir)
            top_levels = [
                os.path.basename(str(subdir)) for subdir in root_path.iterdir()
                if subdir.is_dir() and (subdir / '__init__.py').exists()
            ]
            first_comps = [
                os.path.basename(str(subdir)) for subdir in root_path.iterdir()
            ]
            for tl in top_levels:
                self.tl2pkg[tl] = dep
            for c in first_comps:
                self.first_comp2pkg[c] = dep
            naked = [item.split('.')[0] for item in os.listdir(install_dir) if item.endswith('.py') or item.endswith('.so')]
            for n in naked:
                self.tl2pkg[n] = dep
        return 0

    def save_toplevels(self):
        if not os.path.exists(self.tl2pkg_path):
            with open(self.tl2pkg_path, 'w') as outfile:
                outfile.write(json.dumps(self.tl2pkg, indent=2))
            log.info(f"Saved tl2pkg to {self.tl2pkg_path}")

        if not os.path.exists(self.first_comp2pkg_path):
            with open(self.first_comp2pkg_path, 'w') as outfile:
                outfile.write(json.dumps(self.first_comp2pkg, indent=2))
            log.info(f"Saved first_comp2pkg to {self.first_comp2pkg_path}")

        return 0

    def install_packages(self):
        log.info(f"Installing dependency packages for {self.package}")
        if os.path.exists(self.tmp_install_dir) and not self.always:
            log.info(f"Temp install dir for {self.package} already exists at {self.tmp_install_dir} - Skipping...")
            log.info(f"Use -A to force recreation.")
            return 0
        else:
            utils.create_dir(self.tmp_install_dir)
            all_packages = [self.package] + self.deps
            for dep in all_packages:
                log.info(f"Processing dep {dep}")
                (pkg, version) = utils.pkg_name_to_tuple(dep)
                cmd = [
                    'pip3',
                    'install',
                    '-t', self.tmp_install_dir,
                    '--no-binary', 'Pillow',
                    '--no-deps',
                    "{}=={}".format(pkg, version)
                ]
                log.info(cmd)
                try:
                    ret, out, err = utils.run_cmd(cmd)
                except Exception as e:
                    log.error(e)
                    return -1
                if ret != 0:
                    log.error(f"cmd {cmd} returned non-zero exit code {ret}")
                    log.info(out)
                    log.info(err)
                    if os.path.exists(self.tmp_install_dir):
                        shutil.rmtree(self.tmp_install_dir)
                    return ret
            return 0

    def find_partial_cgs(self):
        log.info(f"Finding partial cgs for {self.package} and deps")

        all_packages = [self.package] + self.deps
        for dep in all_packages:
            log.info(f"Finding partial CG of dep {dep}")
            (pkg, version) = utils.pkg_name_to_tuple(dep)
            partial_cg_path = os.path.join(self.partial_cg_root, pkg[0], pkg, version, 'cg.json')
            if not os.path.exists(partial_cg_path):
                log.error(f"CG path {partial_cg_path} does not exist. Aborting...")
                return -1
            self.pkg2pcg[dep] = partial_cg_path

        with open(self.pkg2pcg_path, 'w') as outfile:
            outfile.write(json.dumps(self.pkg2pcg, indent=2))

        return 0

    def do_find_candidates_single(self, partial_cg_path, output_file, only_external=False):
        p = multiprocessing.Process(target=find_candidates.parse_fasten, args=(partial_cg_path, only_external, output_file))
        p.start()
        p.join()

    def do_analyze_candidates_single(self, candidates_path, sysdir_path, output_file, pkg):
        cmd = [
            'python3',
            'analyze_candidates.py',
            '-i', candidates_path,
            '-s', sysdir_path,
            '-o', output_file,
            '-p', pkg
        ]

        try:
            ret, out, err = utils.run_cmd(cmd)
        except Exception as e:
            log.error(f'Failed to run cmd {cmd}: {e}')
            return -1
        log.info(out)
        log.info(err)
        if ret != 0:
            log.error(f"cmd {cmd} returned non-zero exit code {ret}")
            log.info(out)
            log.info(err)
            return ret

    def find_bridges(self):
        log.info(f"Generating bridges for {self.package} and its dependencies")
        bridges_dir = os.path.join(self.bridges_apps_root, self.namesnip)
        if not os.path.exists(bridges_dir):
            utils.create_dir(bridges_dir)
        candidates_path = os.path.join(bridges_dir, 'candidates.json')
        bridges_path = os.path.join(bridges_dir, 'bridges.json')

        if os.path.exists(candidates_path) and not self.always:
            log.info(f"Candidates file {candidates_path} exists - Skipping...")
            log.info(f"Use -A to force recreation.")
        else:
            try:
                self.do_find_candidates_single(self.pkg2pcg[self.package], candidates_path, only_external=False)
                log.info(f"Candidates written to {candidates_path}")
            except Exception as e:
                log.error(e)
                return -1
        if os.path.exists(bridges_path) and not self.always:
            log.info(f"Bridges file {bridges_path} exists - Skipping...")
            log.info(f"Use -A to force recreation.")
        else:
            try:
                self.do_analyze_candidates_single(candidates_path, self.tmp_install_dir, bridges_path, self.name)
                log.info(f"Bridges written to {bridges_path}")
            except Exception as e:
                log.error(e)
                return -1
        for dep in self.deps:
            pkg = dep.split(':')[0]
            ver = dep.split(':')[1]
            log.info(f"Generating bridges for {pkg}:{ver}...")
            bridges_dir = os.path.join(self.bridges_root, pkg[0], pkg, ver)
            candidates_path = os.path.join(bridges_dir, 'candidates.json')
            bridges_path = os.path.join(bridges_dir, 'bridges.json')
            if not os.path.exists(bridges_dir):
                utils.create_dir(bridges_dir)
            if os.path.exists(candidates_path) and not self.always:
                log.info(f"Candidates file {candidates_path} exists - Skipping...")
                log.info(f"Use -A to force recreation.")
            else:
                try:
                    self.do_find_candidates_single(self.pkg2pcg[dep], candidates_path, only_external=False)
                    log.info(f"Candidates written to {candidates_path}")
                except Exception as e:
                    return -1
            if os.path.exists(bridges_path) and not self.always:
                log.info(f"Bridges file {bridges_path} exists - Skipping...")
                log.info(f"Use -A to force recreation.")
            else:
                try:
                    log.info(f"Analyzing candidates for {pkg}:{ver}")
                    self.do_analyze_candidates_single(candidates_path, self.tmp_install_dir, bridges_path, pkg)
                    log.info(f"Bridges written to {bridges_path}")
                except Exception as e:
                    log.error(f'Exception when creating bridges for {dep}: {e}')
                    log.error(e)
                    return -1
        return 0

    def augment_partial_cg_single(self, bridges_path, current_package):
        augmentor = augment_partial_cg.Augmentor(self.tl2pkg_path, self.pkg2pcg_path, bridges_path, self.pkg2aug_path, current_package)
        augmentor.augment()

    def augment_partial_cgs(self):
        if os.path.exists(self.augstitched_cg_path) and not self.always:
            log.info(f"Augstitched Call graph exists at {self.augstitched_cg_path} - Skipping...")
            log.info(f"Use -A to force recreation.")
            return 0
        log.info(f"Augmenting partial callgraphs for {self.namesnip} and its dependencies")
        all_packages = [self.package] + self.deps
        for dep in all_packages:
            pkg = dep.split(':')[0]
            ver = dep.split(':')[1]
            uuid = pkg + '___' + ver
            self.pkg2aug[dep] = os.path.join(self.augmented_cg_dir, uuid + '.json')

        utils.create_dir(self.augmented_cg_dir)

        for p in self.pkg2pcg.keys():
            shutil.copyfile(self.pkg2pcg[p], self.pkg2aug[p])

        with open(self.pkg2aug_path, 'w') as outfile:
            outfile.write(json.dumps(self.pkg2aug, indent=2))

        bridges_dir = os.path.join(self.bridges_apps_root, self.namesnip)
        bridges_path = os.path.join(bridges_dir, 'bridges.json')

        try:
            self.augment_partial_cg_single(bridges_path, self.package)
        except Exception as e:
            log.error(e)
            return -1

        for dep in self.deps:
            pkg = dep.split(':')[0]
            ver = dep.split(':')[1]
            log.info(f"Augmenting bridges based on {pkg}:{ver}...")
            bridges_dir = os.path.join(self.bridges_root, pkg[0], pkg, ver)
            bridges_path = os.path.join(bridges_dir, 'bridges.json')
            try:
                self.augment_partial_cg_single(bridges_path, dep)
            except Exception as e:
                log.error(e)
                return -1
        log.info(f"Done augmenting callgraphs for {self.package} and its dependencies")

        return 0

    def stitch_augmented_cgs(self):
        log.info(f"Stitching augmented callgraphs for {self.package} and its dependencies")

        if os.path.exists(self.augstitched_cg_path) and not self.always:
            log.info(f"Augstitched Call graph exists at {self.augstitched_cg_path} - Skipping...")
            log.info(f"Use -A to force recreation.")
            return 0

        utils.create_dir(self.augstitched_cg_dir)

        cgs = [os.path.join(self.augmented_cg_dir, f) for f in os.listdir(self.augmented_cg_dir)]

        cmd = [
            'python3',
            'stitch.py',
            '-o', self.augstitched_cg_path,
            '-t', self.tl2pkg_path,
            '-s', self.tmp_install_dir,
            '-f', self.stitching_stats_path,
        ]

        for cg in cgs:
            cmd.append(cg)

        log.info(cmd)
        try:
            ret, out, err = utils.run_cmd(cmd)
        except Exception as e:
            log.error(e)
            return -1
        log.info(out)
        log.info(err)
        if ret != 0:
            log.error(f"cmd {cmd} returned non-zero exit code {ret}")
            log.info(out)
            log.info(err)
            return ret

        log.info(f"Saved augstitched callgraph to {self.augstitched_cg_path}")
        return 0

    def do_bincg_single(self, lib):
        log.info(f"Generating bincg for library: {lib}")
        log.info(f'lib2bcg = {self.lib2bcg}')

        try:
            output_path = self.lib2bcg[lib]
        except Exception as e:
            log.error(e)
            return -1

        binary_path = os.path.join(self.tmp_install_dir, lib)

        if os.path.exists(output_path) and not self.binary_always:
            utils.bincg_add_fun_suffix(lib, output_path)
            log.info(f"Call graph of {lib} from package {self.lib2pkg[lib]} already exists at {output_path} - Skipping...")
            log.info(f"Use -B to force recreation.")
            return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            cmd = [
                'python3',
                os.path.join(PRV_PYHIDRA_ROOT, 'ghidra_pyhidra_callgraphs.py'),
                "-i", binary_path,
                "-o", output_path,
                "-d", temp_dir,
                "-n", lib,
            ]
            log.info(cmd)
            try:
                ret, out, err = utils.run_cmd(cmd, timeout=None, shell=False)
            except Exception as e:
                log.error(e)
                return -1
            if ret != 0:
                log.error(f"cmd {cmd} returned non-zero exit code {ret}")
                log.info(out)
                log.info(err)
                return ret

        utils.bincg_add_fun_suffix(lib, output_path)
        log.info(f"Stored binary cg at: {output_path}")
        return 0

    def find_all_libs(self):
        root = Path(self.tmp_install_dir)
        all_libs_absolute = [p.resolve().as_posix().strip() for p in root.glob("**/*") if p.suffix == ".so" or ".so." in p.name]
        self.all_libs = [os.path.relpath(p, start=self.tmp_install_dir) for p in all_libs_absolute]

        return 0

    def prepare_unify(self):
        log.info(f"Preparing to unify augstitched callgraph with binary callgraphs for package {self.package}")
        log.info(f'NUM_LIBS: {len(self.all_libs)}')

        for lib in self.all_libs:
            try:
                pkg_and_ver = self.first_comp2pkg[lib.split('/')[0]]
                self.lib2pkg[lib] = pkg_and_ver
                package = pkg_and_ver.split(':')[0]
                version = pkg_and_ver.split(':')[1]
                binary_path = os.path.join(self.tmp_install_dir, lib)
                bcg_trail = lib + '.json'
                namesnip = package[0] + '/' + package + '/' + version
                bcg_dir = os.path.join(self.bcg_root, namesnip)
                bcg_path = os.path.join(bcg_dir, bcg_trail)
                # if not os.path.exists(bcg_path):
                #     continue
                self.lib2bcg[lib] = bcg_path
            except Exception as e:
                log.error(f"Exception {e} when processing library {lib} in prepare_unify()")
                continue


        for lib in self.all_libs:
            ret = 0
            try:
                ret = self.do_bincg_single(lib)
            except Exception as e:
                log.error(e)
            if ret != 0:
                # TODO: Handle this gracefully
                continue
                # return ret
        return 0

    def do_unify(self):
        log.info(f"Unifying augstitched callgraph with binary callgraphs for package {self.package}")

        bcg_paths = self.lib2bcg.values()
        try:
            unifier = unify_cg_all_binary.Unifier(self.augstitched_cg_path, bcg_paths)

            unified_cg = unifier.unify()
            utils.create_dir(self.unified_cg_dir)
            with open(self.unified_cg_path, 'w') as outfile:
                outfile.write(json.dumps(unified_cg, indent=2))
        except Exception as e:
            log.error(f'Failed to Unify callgraph for package {self.package}')
            return -1
        log.info(f"Wrote Unified callgraph for package {self.package} to {self.unified_cg_path}")
        return 0

    def process(self):

        if os.path.exists(self.unified_cg_path) and not self.always:
            log.info(f'Unified CG for {self.package} already exists at {self.unified_cg_path}. Skipping...')
            return

        log.info(f"Processing 'package': {self.package}")
        ret = self.load_dependencies()
        if ret != 0:
            return ret

        log.info(f"DEPS = {self.deps}")
        ret = self.find_toplevels()
        if ret != 0:
            return ret

        log.info(f"TL2PKG = {self.tl2pkg}")
        log.info(f"FIRST_COMP2PKG = {self.first_comp2pkg}")

        ret = self.save_toplevels()
        if ret != 0:
            return ret

        ret = self.install_packages()
        if ret != 0:
            return ret

        ret = self.find_all_libs()
        if ret != 0:
            return ret

        ret = self.find_partial_cgs()
        if ret != 0:
            return ret

        log.info(f"self.pkg2pcg = {self.pkg2pcg}")
        p = multiprocessing.Process(target=self.find_bridges, args=())
        p.start()
        p.join()

        ret = self.augment_partial_cgs()
        if ret != 0:
            return ret

        ret = self.stitch_augmented_cgs()
        if ret != 0:
            return ret

        ret = self.prepare_unify()
        if ret != 0:
            return ret

        ret = self.do_unify()
        return ret

def do_single(p, always, use_sbs, binary_always):
    log.info(f"Processing 'package' {p}")
    unistitcher = UnifiedStitcher(p, always, use_sbs, binary_always)
    unistitcher.process()

def main():
    args = parse_args()
    setup_logging(args)

    if args.input is None:
        log.error("Must provide input CSV file")
        sys.exit(1)

    package_names = utils.load_csv(args.input)
    log.info(f"package_names = {package_names}")

    with concurrent.futures.ProcessPoolExecutor(max_workers=10) as executor:
        for pkg in package_names:
            executor.submit(do_single, pkg, args.always, False, args.binary_always)

if __name__ == "__main__":
    main()


