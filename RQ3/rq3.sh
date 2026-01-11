python3 prepare_cves.py
python3 calculate_needed_sbs_versions.py /pyxray/data/cves.json > cve_package_versions.csv
# Precomputed to save time during artifact evaluation
# python3 /pyxray/scripts/sbs.py -i cve_package_versions.csv
python3 check_cve_sbs.py
python3 cve_find_transitive_vuln.py -a /pyxray/packages_final.csv -c /pyxray/data/cves_post_sbs.json -o vuln_clients.json
python3 rq3_stats.py -s vuln_clients.json -o results.json
python3 rq3_table.py results.json
