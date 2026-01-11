import numpy as np
import matplotlib.pyplot as plt
import os
import json

SAMPLES_FILE = 'combined_samples.json'

def generate_histogram(samples, use_log, histogram_filename):
    """Generate histogram and save it as a PDF without white space."""
    plt.figure(figsize=(4, 1))  # Fixed height (1 inch)

    if use_log:
        new_samples = []
        for s in samples:
            if s < 1:
                new_samples.append(s + 1)
            else:
                new_samples.append(s)
        samples = new_samples
        plt.xscale('log')
        bins = np.logspace(np.log10(min(samples)), np.log10(max(samples)), 13)
    else:
        bins = np.linspace(min(samples), max(samples), 13)

    # Create histogram
    # bins = optimal_bins(samples)

    plt.hist(samples, bins=bins, color='red', edgecolor='white', linewidth=0.8)

    # Remove all axis labels and ticks
    plt.xticks([])  # Remove xticks
    plt.yticks([])  # Remove yticks
    plt.gca().spines['top'].set_visible(False)  # Remove top spine
    plt.gca().spines['right'].set_visible(False)  # Remove right spine
    plt.gca().spines['left'].set_visible(False)  # Remove left spine
    plt.gca().spines['bottom'].set_visible(False)  # Remove bottom spine

    plt.gca().tick_params(axis='x', which='both', bottom=False, top=False)  # Hides all x ticks
    plt.gca().tick_params(axis='y', which='both', left=False, right=False)  # Hides all y ticks
    # Set the limits to be tight around the bars, no padding
    plt.xlim(min(samples), max(samples))  # Limit x-axis to the range of the samples
    plt.ylim(0, np.max(np.histogram(samples, bins=bins)[0]))  # Limit y-axis to the maximum frequency

    # Use tight_layout to remove extra space around the plot
    plt.tight_layout(pad=0)  # Ensure no padding around the plot

    # Save histogram as PDF with tight bounding box to remove white space around it
    plt.savefig(histogram_filename, dpi=300, bbox_inches='tight', transparent=True)
    plt.close()

def print_table(sample_data):
    """Print a nicely formatted summary table to stdout."""

    def clean_feature(s):
        # Strip LaTeX noise for readability
        return (
            s.replace('\\texttt{', '')
             .replace('}', '')
             .replace('\\_', '_')
             .removesuffix('_all')
        )

    cols = [
        ("Feature", 35),
        ("5%", 12),
        ("Mean", 12),
        ("Median", 12),
        ("95%", 12),
    ]

    header = " | ".join(f"{name:<{w}}" for name, w in cols)
    sep = "-+-".join("-" * w for _, w in cols)

    print(header)
    print(sep)

    for data in sample_data:
        samples = data["samples"]
        label = data["label"]
        feature = clean_feature(data["feature"])

        p5 = np.percentile(samples, 5)
        mean = np.mean(samples)
        median = np.median(samples)
        p95 = np.percentile(samples, 95)

        # Normalize sizes to MB
        if (
            label.startswith("bin_size")
            or label.startswith("python_size")
            or label.startswith("total_size")
        ):
            scale = 10**6
            p5 /= scale
            mean /= scale
            median /= scale
            p95 /= scale

        if 'size' in feature:
            unit = ' MB'
        else:
            unit = ' % '

        row = [
            f"{feature:<35}",
            f"{p5:>9.2f}{unit}",
            f"{mean:>9.2f}{unit}",
            f"{median:>9.2f}{unit}",
            f"{p95:>9.2f}{unit}",
        ]

        print(" | ".join(row))



def generate_latex_table(sample_data):
    """Generate LaTeX code for the table with histograms."""
    latex_code = """
\\documentclass{article}
\\usepackage{graphicx}
\\usepackage{booktabs}
\\usepackage{array}
\\usepackage{lscape}

\\begin{document}

\\begin{table}[h]
    \\centering
    \\renewcommand{\\arraystretch}{0.8}  % Reduce row height by scaling to 80% of the default
    \\begin{tabular}{rccccc}
        \\hline
        Feature & 5\\% & Mean & Median & 95\\% & Histogram \\\\
        \\hline
    """

    for i, data in enumerate(sample_data):
        samples, label, feature,  use_log = data['samples'], data['label'], data['feature'],  data['use_log']

        # Calculate statistics
        percentile_5 = np.percentile(samples, 5)
        mean = np.mean(samples)
        median = np.median(samples)
        percentile_95 = np.percentile(samples, 95)

        # if label.startswith('bin_size') or label.startswith('python_size') or label.startswith('total'):
        if label.startswith('bin_size') or label.startswith('python_size') or label.startswith('total_size'):
            percentile_5 = percentile_5 / (10 ** 6)
            mean = mean / (10 ** 6)
            median = median / (10 ** 6)
            percentile_95 = percentile_95 / (10 ** 6)

        # Generate histogram file name
        histogram_filename = f"histogram_{label}.pdf"

        # Ensure the directory exists to save the histograms
        if not os.path.exists('histograms'):
            os.makedirs('histograms')

        # Generate histogram and save it in the 'histograms' directory
        histogram_path = os.path.join('histograms', histogram_filename)
        generate_histogram(samples, use_log, histogram_path)

        # Add row to the LaTeX table with fixed-width histogram
        latex_code += f"""
        {feature}  & {percentile_5:.2f} & {mean:.2f} & {median:.2f} & {percentile_95:.2f} & \\includegraphics[width=0.15\\textwidth]{{histograms/{histogram_filename}}} \\\\
    """

    latex_code += """
    \\end{tabular}
    \\caption{Summary statistics with histograms for multiple variables}
    \\label{tab:stats}
\\end{table}

\\end{document}
"""
    return latex_code

def main():
    # Example sample datasets (you can replace these with your own datasets)
    with open(SAMPLES_FILE, 'r') as infile:
        samples = json.loads(infile.read())

    xray_data = [
            # XXX: SCALES: Python_size
            {'label': 'python_size_all', 'samples': samples['python_size']['all'],
             'feature':'\\texttt{python\_size\_all}', 'description': 'Cumulative Python code size MB (all deps)',
             'use_log': True},
            # {'label': 'python_size_direct', 'samples': samples['python_size']['direct'],
            #  'feature':'\\texttt{python\_size\_direct}', 'description': 'Cumulative Python code size MB (direct deps)',
            #  'use_log': True},
            # {'label': 'python_size_transitive', 'samples': samples['python_size']['transitive'],
            #  'feature':'\\texttt{python\_size\_transitive}', 'description': 'Cumulative Python code size MB (transitive deps)',
            #  'use_log': True},

            # XXX: SCALES: Dependency bloat percent at package granurality
            {'label': 'bloated_dependency_percent_all', 'samples': samples['bloated_dependency_percent']['all'],
             'feature':'\\texttt{bloated\_dependency\_percent\_all}',
             'use_log': False},
            # {'label': 'bloated_dependency_percent_direct', 'samples': samples['bloated_dependency_percent']['direct'],
            #  'feature':'\\texttt{bloated\_dependency\_percent\_direct}',
            #  'use_log': False},
            # {'label': 'bloated_dependency_percent_transitive', 'samples': samples['bloated_dependency_percent']['transitive'],
            #  'feature':'\\texttt{bloated\_dependency\_percent\_transitive}',
            #  'use_log': False},

            # XXX: SCALES: Python file bloat percent
            {'label': 'python_file_bloat_percent_all', 'samples': samples['bloated_python_file_percent']['all'],
             'feature':'\\texttt{python\_file\_bloat\_percent\_all}',
             'use_log': False},
            # {'label': 'python_file_bloat_percent_direct', 'samples': samples['bloated_python_file_percent']['direct'],
            #  'feature':'\\texttt{python\_file\_bloat\_percent\_direct}',
            #  'use_log': False},
            # {'label': 'python_file_bloat_percent_transitive', 'samples': samples['bloated_python_file_percent']['transitive'],
            #  'feature':'\\texttt{python\_file\_bloat\_percent\_transitive}',
            #  'use_log': False},

            # XXX: SCALES: Python function bloat percent
            {'label': 'python_function_bloat_percent_all', 'samples': samples['bloated_python_function_percent']['all'],
             'feature':'\\texttt{python\_function\_bloat\_percent\_all}',
             'use_log': False},
            # {'label': 'python_function_bloat_percent_direct', 'samples': samples['bloated_python_function_percent']['direct'],
            #  'feature':'\\texttt{python\_function\_bloat\_percent\_direct}',
            #  'use_log': False},
            # {'label': 'python_function_bloat_percent_transitive', 'samples': samples['bloated_python_function_percent']['transitive'],
            #  'feature':'\\texttt{python\_function\_bloat\_percent\_transitive}',
            #  'use_log': False},

            # XXX: XRAY: Binary size
            {'label': 'bin_size_all', 'samples': samples['bin_size']['all'],
             'feature':'\\texttt{bin\_size\_all}',
             'use_log': True},
            # {'label': 'bin_size_direct', 'samples': samples['bin_size']['direct'],
            #  'feature':'\\texttt{bin\_size\_direct}',
            #  'use_log': True},
            # {'label': 'bin_size_transitive', 'samples': samples['bin_size']['transitive'],
            #  'feature':'\\texttt{bin\_size\_transitive}',
            #  'use_log': True},

            # XXX: XRAY: Binary file bloat %
            {'label': 'bloat_whole_bin_percent_all', 'samples': samples['bloat_whole_bin_percent']['all'],
             'feature':'\\texttt{bloat\_whole\_bin\_percent\_all}',
             'use_log': False},
            # {'label': 'bloat_whole_bin_percent_direct', 'samples': samples['bloat_whole_bin_percent']['direct'],
            #  'feature':'\\texttt{bloat\_whole\_bin\_percent\_direct}',
            #  'use_log': False},
            # {'label': 'bloat_whole_bin_percent_transitive', 'samples': samples['bloat_whole_bin_percent']['transitive'],
            #  'feature':'\\texttt{bloat\_whole\_bin\_percent\_transitive}',
            #  'use_log': False},

            # XXX: XRAY: Binary symbols bloat %
            {'label': 'bloat_symbols_percent_all', 'samples': samples['bloat_symbols_percent']['all'],
             'feature':'\\texttt{bloat\_symbols\_percent\_all}',
             'use_log': False},
            # {'label': 'bloat_symbols_percent_direct', 'samples': samples['bloat_symbols_percent']['direct'],
            #  'feature':'\\texttt{bloat\_symbols\_percent\_direct}',
            #  'use_log': False},
            # {'label': 'bloat_symbols_percent_transitive', 'samples': samples['bloat_symbols_percent']['transitive'],
            #  'feature':'\\texttt{bloat\_symbols\_percent\_transitive}',
            #  'use_log': False},

            # XXX: OVERALL: Total package size MB
            {'label': 'total_size_all', 'samples': samples['total_package_size'],
             'feature':'\\texttt{total\_size\_all}', 'description': 'Cumulative Python code size MB (all deps)',
             'use_log': True},

            # XXX: OVERALL: Total file bloat %
            {'label': 'total_file_bloat', 'samples': samples['total_file_bloat'],
             'feature':'\\texttt{total\_file\_bloat}',
             'use_log': True},

            # XXX: OVERALL: Total function bloat %
            {'label': 'total_function_bloat', 'samples': samples['total_function_bloat'],
             'feature':'\\texttt{total\_function\_bloat}',
             'use_log': True},
            ]

    # sample_data = [
    #     {'samples': np.random.normal(loc=50, scale=10, size=1000), 'label': 'Variable 1', 'feature': 'foo', 'description': 'bar'},
    #     {'samples': np.random.normal(loc=30, scale=5, size=1000), 'label': 'Variable 2'},
    #     {'samples': np.random.normal(loc=70, scale=20, size=1000), 'label': 'Variable 3'}
    # ]

    # Generate LaTeX code for the table
    latex_code = generate_latex_table(xray_data)
    # Save LaTeX code to a file
    with open("table_multiple_variables.tex", "w") as file:
        file.write(latex_code)

    print("LaTeX code saved to table_multiple_variables.tex. Histograms saved as PDFs.")
    print("---")

    print_table(xray_data)

if __name__ == "__main__":
    main()



