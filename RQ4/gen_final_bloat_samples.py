import json
from collections import defaultdict

FILE_SBS = 'bloat_sbs.json'
FILE_SCALES = 'scales_final.json'

final_samples = {}

with open(FILE_SBS, 'r') as infile:
    sbs_stats = json.loads(infile.read())

with open(FILE_SCALES, 'r') as infile:
    scales_data = json.loads(infile.read())

aux = defaultdict(dict)

#------------------------------------------------------------------------------
# XXX: Total size of Python files (per app)
direct_python_size_samples = []
transitive_python_size_samples = []
all_python_size_samples = []


for app, stat in sbs_stats['data'].items():
    dps = stat['dependency_python_sizes']
    direct_python_size_samples.append(dps['direct'])
    transitive_python_size_samples.append(dps['transitive'])
    all_python_size_samples.append(dps['all'])
    aux[app]['python_size'] = dps['all']


final_samples['python_size'] = {'direct': direct_python_size_samples,
                             'transitive': transitive_python_size_samples,
                             'all': all_python_size_samples}
#------------------------------------------------------------------------------
#------------------------------------------------------------------------------
# XXX: Bloated dependencies, per app (percent)
all_deps_percent_bloat_samples = []
direct_deps_percent_bloat_samples = []
transitive_deps_percent_bloat_samples = []

for app in sbs_stats['data'].keys():
    try:
        sd = scales_data[app]
    except KeyError as e:
        continue
    # Dependencies
    num_direct_used = int(sd['used_direct_deps_count_1'])
    num_direct_bloat = int(sd['bloated_deps_count_1'])
    num_direct_total = num_direct_used + num_direct_bloat

    num_transitive_used = int(sd['transitive_used_dependencies_count'])
    num_transitive_bloat = int(sd['transitive_bloated_dependencies_count'])
    num_transitive_total = num_transitive_used + num_transitive_bloat

    num_total_bloat = num_direct_bloat + num_transitive_bloat
    num_total = num_direct_total + num_transitive_total

    if num_total > 0:
        all_deps_percent_bloat_samples.append(100 * (num_total_bloat / num_total))
        aux[app]['dep_bloat'] = num_total_bloat / num_total
    if num_direct_total > 0:
        direct_deps_percent_bloat_samples.append(100 * (num_direct_bloat / num_direct_total))
    if num_transitive_total > 0:
        transitive_deps_percent_bloat_samples.append(100 * (num_transitive_bloat / num_transitive_total))

final_samples['bloated_dependency_percent'] = {'direct': direct_deps_percent_bloat_samples,
                              'transitive': transitive_deps_percent_bloat_samples,
                              'all': all_deps_percent_bloat_samples}
#------------------------------------------------------------------------------
# XXX: Python files, per app, bloated percent
all_python_file_percent_bloat_samples = []
direct_python_file_percent_bloat_samples = []
transitive_python_file_percent_bloat_samples = []

for app in sbs_stats['data'].keys():
    try:
        sd = scales_data[app]
    except KeyError as e:
        continue
    # Dependencies
    num_direct_used = int(sd['used_direct_files_count_1'])
    num_direct_bloat = int(sd['bloated_files_count_1'])
    num_direct_total = num_direct_used + num_direct_bloat

    num_transitive_used = int(sd['transitive_used_files_count'])
    num_transitive_bloat = int(sd['transitive_bloated_files_count'])
    num_transitive_total = num_transitive_used + num_transitive_bloat

    num_total_bloat = num_direct_bloat + num_transitive_bloat
    num_total = num_direct_total + num_transitive_total

    if num_total > 0:
        all_python_file_percent_bloat_samples.append(100 * (num_total_bloat / num_total))
        aux[app]['python_file_bloat'] = num_total_bloat / num_total
    if num_direct_total > 0:
        direct_python_file_percent_bloat_samples.append(100 * (num_direct_bloat / num_direct_total))
    if num_transitive_total > 0:
        transitive_python_file_percent_bloat_samples.append(100 * (num_transitive_bloat / num_transitive_total))

final_samples['bloated_python_file_percent'] = {'direct': direct_python_file_percent_bloat_samples,
                              'transitive': transitive_python_file_percent_bloat_samples,
                              'all': all_python_file_percent_bloat_samples}

#------------------------------------------------------------------------------
# XXX: Python Functions, per app, bloated percent
all_python_function_percent_bloat_samples = []
direct_python_function_percent_bloat_samples = []
transitive_python_function_percent_bloat_samples = []

for app in sbs_stats['data'].keys():
    try:
        sd = scales_data[app]
    except KeyError as e:
        continue
    # Dependencies
    num_direct_used = int(sd['used_direct_functions_count_1'])
    num_direct_bloat = int(sd['bloated_functions_count_1'])
    num_direct_total = num_direct_used + num_direct_bloat

    num_transitive_used = int(sd['transitive_used_functions_count'])
    num_transitive_bloat = int(sd['transitive_bloated_functions_count'])
    num_transitive_total = num_transitive_used + num_transitive_bloat

    num_total_bloat = num_direct_bloat + num_transitive_bloat
    num_total = num_direct_total + num_transitive_total

    if num_total > 0:
        all_python_function_percent_bloat_samples.append(100 * (num_total_bloat / num_total))
        aux[app]['python_function_bloat'] = num_total_bloat / num_total
    if num_direct_total > 0:
        direct_python_function_percent_bloat_samples.append(100 * (num_direct_bloat / num_direct_total))
    if num_transitive_total > 0:
        transitive_python_function_percent_bloat_samples.append(100 * (num_transitive_bloat / num_transitive_total))

final_samples['bloated_python_function_percent'] = {'direct': direct_python_function_percent_bloat_samples,
                              'transitive': transitive_python_function_percent_bloat_samples,
                              'all': all_python_function_percent_bloat_samples}
#------------------------------------------------------------------------------
# XXX: Total size of binaries (per app)
direct_bin_size_samples = []
transitive_bin_size_samples = []
all_bin_size_samples = []


for app, stat in sbs_stats['data'].items():
    dbs = 0
    tbs = 0
    for dep, ls in stat['direct'].items():
        for l in ls.values():
            binary_size = l['binary_size']
            dbs += binary_size

    dbs = dbs
    direct_bin_size_samples.append(dbs)

    for dep, ls in stat['transitive'].items():
        for l in ls.values():
            binary_size = l['binary_size']
            tbs += binary_size

    tbs = tbs
    transitive_bin_size_samples.append(tbs)
    all_bin_size_samples.append(dbs + tbs)
    aux[app]['binary_size'] = dbs + tbs


final_samples['bin_size'] = {'direct': direct_bin_size_samples,
                             'transitive': transitive_bin_size_samples,
                             'all': all_bin_size_samples}
#------------------------------------------------------------------------------
# XXX: Whole Libraries, per app, % bloat
all_whole_bin_percent_samples = []
direct_whole_bin_percent_samples = []
transitive_whole_bin_percent_samples = []

for app, stat in sbs_stats['data'].items():
    ndu = 0
    ndb = 0
    for dep, ls in stat['direct'].items():
        for l in ls.values():
            pct = l['reached_percent']
            if pct > 0:
                ndu += 1
            else:
                ndb += 1

    # XXX: At least one direct dependency binary
    if ndu > 0 or ndb > 0:
        direct_whole_bin_percent_samples.append(100 * ndb / (ndu + ndb))

    ntu = 0
    ntb = 0
    for dep, ls in stat['transitive'].items():
        for l in ls.values():
            pct = l['reached_percent']
            if pct > 0:
               ntu += 1
            else:
               ntb += 1

    # XXX: At least one direct dependency binary
    if ntu > 0 or ntb > 0:
        transitive_whole_bin_percent_samples.append(100 * ntb / (ntu + ntb))
    n_total_bloat = ndb + ntb
    n_total = (ndu + ndb) + (ntu + ntb)
    if n_total > 0:
        all_whole_bin_percent_samples.append(100 * n_total_bloat / n_total)
        aux[app]['binary_file_bloat'] = n_total_bloat / n_total


final_samples['bloat_whole_bin_percent'] = {'direct': direct_whole_bin_percent_samples,
                                           'transitive': transitive_whole_bin_percent_samples,
                                           'all': all_whole_bin_percent_samples}
#------------------------------------------------------------------------------
# XXX: Symbols, per app, % bloat

all_bloat_symbols_percent_samples = []
direct_bloat_symbols_percent_samples = []
transitive_bloat_symbols_percent_samples = []

for app, stat in sbs_stats['data'].items():
    ndr = 0
    ndb = 0
    for dep, ls in stat['direct'].items():
        for l in ls.values():
            total_sbs_syms = l['total_sbs_symbols']
            reachable = l['reached_sbs_symbols']
            bloated = total_sbs_syms - reachable
            ndr += reachable
            ndb += bloated

    # XXX: At least one binary
    if ndr > 0 or ndb > 0:
        direct_bloat_symbols_percent_samples.append(100 * ndb / (ndr + ndb))

    ntr = 0
    ntb = 0
    for dep, ls in stat['transitive'].items():
        for l in ls.values():
            total_sbs_syms = l['total_sbs_symbols']
            reachable = l['reached_sbs_symbols']
            bloated = total_sbs_syms - reachable
            ntr += reachable
            ntb += bloated

    # XXX: At least one binary
    if ntr > 0 or ntb > 0:
        transitive_bloat_symbols_percent_samples.append(100 * ntb / (ntr + ntb))
    sym_total_bloat = ndb + ntb
    sym_total = ndr + ndb + ntr + ntb
    if sym_total > 0:
        all_bloat_symbols_percent_samples.append(100 * sym_total_bloat / sym_total)
        aux[app]['binary_function_bloat'] = sym_total_bloat / sym_total

final_samples['bloat_symbols_percent'] = {'direct': all_bloat_symbols_percent_samples,
                                           'transitive': direct_bloat_symbols_percent_samples,
                                           'all': transitive_bloat_symbols_percent_samples}
#------------------------------------------------------------------------------
# XXX: Total package-level bloat
total_package_bloat_samples = []

for app in aux.keys():
    if ('dep_bloat' in aux[app].keys() and  'python_size' in aux[app].keys() and 'binary_size' in aux[app].keys()):
        dep_bloat = aux[app]['dep_bloat']
        python_size = aux[app]['python_size']
        binary_size = aux[app]['binary_size']
        total_package_bloat_samples.append(python_size + binary_size)

final_samples['total_package_size'] = total_package_bloat_samples
#------------------------------------------------------------------------------
# XXX: Total file-level bloat
total_file_bloat_samples = []

for app in aux.keys():
    if ('python_file_bloat' in aux[app].keys() and 'python_size' in aux[app].keys()
        and 'binary_file_bloat' in aux[app].keys() and 'binary_size' in aux[app].keys()):
        python_file_bloat = aux[app]['python_file_bloat']
        python_size = aux[app]['python_size']
        binary_file_bloat = aux[app]['binary_file_bloat']
        binary_size = aux[app]['binary_size']
        total_file_bloat_1 = (python_file_bloat * python_size) + (binary_file_bloat * binary_size)
        total_file_bloat = total_file_bloat_1 / (python_size + binary_size)
        total_file_bloat_samples.append(100 * total_file_bloat)

final_samples['total_file_bloat'] = total_file_bloat_samples
#------------------------------------------------------------------------------
# XXX: Total function-level bloat
total_function_bloat_samples = []

for app in aux.keys():
    if ('python_function_bloat' in aux[app].keys() and 'python_size' in aux[app].keys()
        and 'binary_function_bloat' in aux[app].keys() and 'binary_size' in aux[app].keys()):
        python_function_bloat = aux[app]['python_function_bloat']
        python_size = aux[app]['python_size']
        binary_function_bloat = aux[app]['binary_function_bloat']
        binary_size = aux[app]['binary_size']
        total_function_bloat_1 = (python_function_bloat * python_size) + (binary_function_bloat * binary_size)
        total_function_bloat = total_function_bloat_1 / (python_size + binary_size)
        total_function_bloat_samples.append(100 * total_function_bloat)

final_samples['total_function_bloat'] = total_function_bloat_samples
#------------------------------------------------------------------------------

print(json.dumps(final_samples, indent=2))
