python3 rq4_sbs.py -i /pyxray/packages_final.csv -o bloat_sbs.json
python3 gen_final_bloat_samples.py > combined_samples.json
python3 table.py
