mkdir -p /tmp/rq1-build/pandas
cd /tmp/rq1-build/pandas

git clone https://github.com/pandas-dev/pandas 
cd pandas
git checkout tags/v2.2.3

export CFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export CXXFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export LDFLAGS="-g"
export CMAKE_BUILD_TYPE=Debug

pip install -t /pyxray/data/install/pandas___RQ1 .
pip install --no-deps -t /pyxray/data/install/pandas___RQ1___TOPLEVEL .

rm -rf /tmp/rq1-build/pandas
