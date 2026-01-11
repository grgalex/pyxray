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

bridges = {'numpy': 3026, 'pillow': 233, 'scipy': 1203}

keep_cves = [
    "CVE-2020-10177",
    "CVE-2020-35654",
    "CVE-2020-5311",
    "CVE-2021-34141",
    "CVE-2021-25290",
    "CVE-2022-30595",
    "CVE-2023-25399",
    "CVE-2024-28219",
]

cve2row = {}

def main(stats_file):
    rows = []

    with open(stats_file, 'r') as infile:
        stats = json.loads(infile.read())

        for entry in stats:
            rdeps = int(entry['total_rdeps'])

            if entry['status'] != 'OK':
                continue

            if not rdeps > 0:
                continue

            cve = entry['id']

            if cve not in keep_cves:
                continue

            rdeps = rdeps
            vs = entry['vulnerable_symbols']
            vuln_sym = vs[0]
            # for v in vs[1:]:
            #     vuln_sym = vuln_sym + ' ' + v

            vuln_rdeps = entry['vuln_rdeps']
            pct_bridges_vuln = entry['avg_percent_package_api_leads_to_vulnerable']

            pkg = entry['package']

            row = [
                cve,
                pkg,
                vuln_sym,
                bridges[pkg],
                pct_bridges_vuln,
                rdeps,
                vuln_rdeps,
            ]

            cve2row[cve] = row

    headers = ["CVE", "Package", "Vuln. symbol", "Bridges (Total)", "Bridges (% vuln)", "Clients (Depend)", "Clients (Call)"]
    
    for cve in keep_cves:
        rows.append(cve2row[cve])

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

