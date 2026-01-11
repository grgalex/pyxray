mkdir -p /tmp/rq1-build/grpcio
cd /tmp/rq1-build/grpcio

git clone https://github.com/grpc/grpc.git
cd grpc
git checkout c4b0b6a4f605e743ebabb71008b2bee0a98b364a
git submodule update --init

pip install -t /pyxray/data/install/grpcio___RQ1 .
pip install --no-deps -t /pyxray/data/install/grpcio___RQ1___TOPLEVEL .

rm -rf /tmp/rq1-build/grpcio
