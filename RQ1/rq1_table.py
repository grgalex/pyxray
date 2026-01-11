import csv
import json
import os
import sys
import subprocess

try:
    from tabulate import tabulate
    USE_TABULATE = True
except ImportError:
    USE_TABULATE = False


BASE = "/pyxray/data/star_bridges"

GROUND_TRUTH_DIR = "/pyxray/RQ1/ground_truth"

# Deduct 3 lines from wc -l of torch,
# because we have a 3-line comment in tools/autograd/gen_python_functions.py.csv
TORCH_DEDUCT = 3

GROUND_TRUTH_PATHS = {
        'pyaudio': 'pyaudio.csv',
        'python-ldap': 'python-ldap.csv',
        'trace-cruncher': 'trace-cruncher.csv',
        'pynacl': 'pynacl.csv',
        'pyyaml': 'pyyaml.csv',
        'cryptography': 'cryptography',
        'grpcio': 'grpcio',
        'numpy': 'numpy',
        'pandas': 'pandas',
        'torch': 'torch'
        }

def human_units(n):
    if n < 1_000:
        return str(n)
    if n < 1_000_000:
        return f"{n/1_000:.1f}K"
    if n < 1_000_000_000:
        return f"{n/1_000_000:.1f}M"
    if n < 1_000_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    return f"{n/1_000_000_000_000:.1f}T"

def find_unique_lines(path):
    cmd = f"find {path} -type f -exec cat {{}} + | sort | uniq | wc -l"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return int(result.stdout.strip())

def load_starbridges(pkg):
    """Load starbridges.json for a package, or return None if missing."""
    prefix = pkg[0].lower()
    path = os.path.join(BASE, prefix, pkg, "RQ1", "starbridges.json")

    if not os.path.isfile(path):
        return None, path

    with open(path, "r") as f:
        try:
            data = json.load(f)
            return data, path
        except Exception:
            return None, path


def main(csv_file):
    rows = []

    with open(csv_file, newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            pkg = row[0].strip().split(':')[0] # remove :RQ1 suff
            data, path = load_starbridges(pkg)
            gt_path = os.path.join(GROUND_TRUTH_DIR, GROUND_TRUTH_PATHS[pkg])
            gt_count = find_unique_lines(gt_path)
            if pkg == 'torch':
                pkg == 'pytorch'
                gt_count -= TORCH_DEDUCT

            if pkg in ["numpy", "pandas", "torch"]:
                pkg += '*'

            if data is None:
                rows.append([pkg, "-", "-", "-", "-", "-", f"(missing: {path})"])
            else:
                rows.append([
                    pkg,
                    gt_count,
                    data.get("count", "-"),
                    data.get("duration_sec", "-"),
                    human_units(data.get("objects_examined", "-")),
                    human_units(data.get("callable_objects", "-")),
                    human_units(data.get("foreign_callable_objects", "-")),
                ])

    headers = ["Package", "Ground Truth", "Found", "Time(s)", "Objects", "Callable", "Foreign"]

    if USE_TABULATE:
        print(tabulate(rows, headers=headers, tablefmt="github"))
    else:
        # manual formatting if tabulate is missing
        col_widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
        fmt = " | ".join("{:<" + str(w) + "}" for w in col_widths)

        print(fmt.format(*headers))
        print("-+-".join("-" * w for w in col_widths))
        for r in rows:
            print(fmt.format(*r))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 script.py packages.csv")
        sys.exit(1)

    main(sys.argv[1])

