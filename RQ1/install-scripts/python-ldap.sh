mkdir -p /tmp/rq1-build/python-ldap
cd /tmp/rq1-build/python-ldap

git clone https://github.com/python-ldap/python-ldap.git
cd python-ldap

apt update
apt install build-essential ldap-utils \
    libldap2-dev libsasl2-dev -y

export CFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export CXXFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export LDFLAGS="-g"
export CMAKE_BUILD_TYPE=Debug

git checkout aca9cb5fdbab78918fe6905cfe1cff8549039c03

pip install -t /pyxray/data/install/python-ldap___RQ1 .
pip install --no-deps -t /pyxray/data/install/python-ldap___RQ1___TOPLEVEL .

rm -rf /tmp/rq1-build/python-ldap
