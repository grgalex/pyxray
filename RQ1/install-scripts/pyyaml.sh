mkdir -p /tmp/rq1-build/pyyaml
cd /tmp/rq1-build/pyyaml

git clone https://github.com/yaml/pyyaml.git
cd pyyaml

apt update
# Install libyaml development headers.
# Note: According to the PyYAML package documentation,
# setup.py automatically checks for the presence of LibYAML.
# If libyaml (and its headers) are installed, PyYAML builds
# the fast C-based bindings instead of the pure Python fallback.
apt install libyaml-dev -y

git checkout 69c141adcf805c5ebdc9ba519927642ee5c7f639

pip install --force-reinstall Cython==0.29.37

PYYAML_FORCE_CYTHON=1 pip install -t /pyxray/data/install/pyyaml___RQ1 .
PYYAML_FORCE_CYTHON=1 pip install --no-deps -t /pyxray/data/install/pyyaml___RQ1___TOPLEVEL .

rm -rf /tmp/rq1-build/pyyaml
