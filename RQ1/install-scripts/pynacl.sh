mkdir -p /tmp/rq1-build/pynacl
cd /tmp/rq1-build/pynacl

git clone https://github.com/pyca/pynacl.git
cd pynacl

export CFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export CXXFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export LDFLAGS="-g"
export CMAKE_BUILD_TYPE=Debug

git checkout 9ffa598e47242bf783aae23c20c31e876c438f1a

pip install -t /pyxray/data/install/pynacl___RQ1 .
pip install --no-deps -t /pyxray/data/install/pynacl___RQ1___TOPLEVEL .

rm -rf /tmp/rq1-build/pynacl
