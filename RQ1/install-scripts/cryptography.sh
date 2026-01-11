mkdir -p /tmp/rq1-build/cryptography
cd /tmp/rq1-build/cryptography

curl https://sh.rustup.rs -sSf | sh -s -- -y
source ${HOME}/.cargo/env

git clone https://github.com/pyca/cryptography.git
cd cryptography

export CFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export CXXFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export LDFLAGS="-g"
export CMAKE_BUILD_TYPE=Debug

git checkout 7947620466b23a68ced1562a9de49adfd42582df

pip install -t /pyxray/data/install/cryptography___RQ1 .
pip install --no-deps -t /pyxray/data/install/cryptography___RQ1___TOPLEVEL .

rm -rf /tmp/rq1-build/cryptography
