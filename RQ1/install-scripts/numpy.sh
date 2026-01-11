mkdir -p /tmp/rq1-build/numpy
cd /tmp/rq1-build/numpy

git clone https://github.com/numpy/numpy.git
cd numpy
git checkout tags/v2.0.2
# git checkout tags/v1.24.4
git submodule update --init

export CFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export CXXFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export LDFLAGS="-g"
export CMAKE_BUILD_TYPE=Debug

pip install -t /pyxray/data/install/numpy___RQ1 .
pip install --no-deps -t /pyxray/data/install/numpy___RQ1___TOPLEVEL .

rm -rf /tmp/rq1-build/numpy
