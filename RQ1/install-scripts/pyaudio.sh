mkdir -p /tmp/rq1-build/pyaudio
cd /tmp/rq1-build/pyaudio

git clone https://github.com/CristiFati/pyaudio.git
cd pyaudio

apt update
apt install portaudio19-dev -y

export CFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export CXXFLAGS="-g3 -O0 -fno-inline -fno-omit-frame-pointer"
export LDFLAGS="-g"
export CMAKE_BUILD_TYPE=Debug

git checkout 69ac9e71a2007567a8d7fc5fd537b42c9c699bd3

pip install -t /pyxray/data/install/pyaudio___RQ1 .
pip install --no-deps -t /pyxray/data/install/pyaudio___RQ1___TOPLEVEL .

rm -rf /tmp/rq1-build/pyaudio
