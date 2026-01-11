import sys
import json
import argparse
import logging

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
        help=("Output file. Example --output bridges.json"),
    )
    p.add_argument(
        "-i",
        "--input",
        default=None,
        help=("Absolute path to the partial callgraph location"),
    )

    return p.parse_args()

def parse_fasten(infile, only_external, output_file):
    candidates = {'internal': [], 'external': []}
    with open(infile, 'r') as f:
        fasten = json.loads(f.read())
    if not only_external:
        internal_modules = fasten['modules']['internal']
        for km, vm in internal_modules.items():
            for kn, vn in vm['namespaces'].items():
                ns = vn['namespace']
                metadata = vn['metadata']
                if (metadata.get('first', None) is None and metadata.get('last') is None
                    or metadata == {}):
                    candidates['internal'].append(ns)
                    first_part = '/'.join(ns.split('/')[:-1]) + '/'
                    pyname = ns.split('/')[-1]
                    parts = pyname.split('.')
                    extra_candidates = []
                    extra = first_part + parts[0]
                    for piece in parts[1:]:
                        extra = extra + '.' + piece
                        if extra != ns and extra not in candidates['internal']:
                            extra_candidates.append(extra)
                    candidates['internal'].extend(extra_candidates)

    external_modules = fasten['modules']['external']
    for km, vm in external_modules.items():
        for kn, vn in vm['namespaces'].items():
            ns = vn['namespace']
            candidates['external'].append(ns)
            first_part = '//' + ns.split('//')[1] + '//'
            pyname = ns.split('//')[-1]
            parts = pyname.split('.')
            extra_candidates = []
            extra = first_part + parts[0]
            for piece in parts[1:]:
                extra = extra + '.' + piece
                if extra != ns and extra not in candidates['external']:
                    extra_candidates.append(extra)
            candidates['external'].extend(extra_candidates)

    if output_file is not None:
        with open(output_file, 'w') as outfile:
            outfile.write(json.dumps(candidates, indent=2))
    else:
        log.info(json.dumps(candidates, indent=2))

def main():
    args = parse_args()
    setup_logging(args)
    if args.input is None:
        log.error("Must give input file path")
        sys.exit(1)
    output_file = args.output
    candies = parse_fasten(args.input, args.output)

if __name__ == "__main__":
    main()

