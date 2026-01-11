#!/usr/bin/env python3
import subprocess
import sys
import re

def get_latest_version(package: str) -> str:
    """Return the latest version of a package using pip index."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", package],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None

    match = re.search(r"Available versions:\s*(.*)", proc.stdout)
    if not match:
        return None

    versions = [v.strip() for v in match.group(1).split(",")]
    return versions[0] if versions else None


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input-file> <output-file>", file=sys.stderr)
        sys.exit(1)

    input_file, output_file = sys.argv[1], sys.argv[2]

    with open(input_file, "r") as fin, open(output_file, "w") as fout:
        for line in fin:
            pkg = line.strip()
            if not pkg:
                continue
            version = get_latest_version(pkg)
            fout.write(f"{pkg}:{version if version else '<not found>'}\n")

if __name__ == "__main__":
    main()

