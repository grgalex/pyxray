#!/usr/bin/env python3
import json
import sys

def main():
    if len(sys.argv) != 2:
        print("Usage: python script.py <path.json>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]

    with open(path, "r") as f:
        data = json.load(f)

    seen = set()

    for key, entry in data.items():
        package = entry.get("package")
        max_vuln = entry.get("max_vuln_version")
        latest = entry.get("latest_version")

        if not package:
            continue

        for version in (max_vuln, latest):
            if version is None:
                continue

            pair = f"{package}:{version}"
            if pair not in seen:
                print(pair)
                seen.add(pair)

if __name__ == "__main__":
    main()

