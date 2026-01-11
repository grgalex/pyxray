import json
from collections import defaultdict

ORIG = 'bloat_orig.json'
NEW = 'binsizes.json'

with open(ORIG, 'r') as infile:
    raw = json.loads(infile.read())

data = raw["data"]

sizes = defaultdict(dict)

for k in data.keys():
    a = data[k]["all"]
    for kk in a.keys():
        for kkk in a[kk].keys():
            v = a[kk][kkk]["binary_size"]
            sizes[k][kkk] = v
with open(NEW, 'w') as outfile:
    outfile.write(json.dumps(sizes, indent=2))
