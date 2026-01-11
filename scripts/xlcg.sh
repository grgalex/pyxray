#!/bin/bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <packages.csv>" >&2
  exit 1
fi

PACKAGES_CSV="$1"

python3 dep_and_partial.py -i "$PACKAGES_CSV" && \
python3 pypi_unistitch.py -i "$PACKAGES_CSV" && \
python3 reachability.py -P
