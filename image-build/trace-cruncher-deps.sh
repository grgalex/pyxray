mkdir -p /tmp/rq1-build/trace-cruncher
cd /tmp/rq1-build/trace-cruncher

sudo apt-get update
sudo apt-get install -y \
  build-essential git cmake pkg-config valgrind flex bison \
  libjson-c-dev libpython3-dev cython3 python3-numpy python3-pip \
  libgl1-mesa-dev freeglut3-dev libxmu-dev libxi-dev fonts-freefont-ttf \
  qt6-base-dev qt6-base-dev-tools qt6-declarative-dev qt6-tools-dev qt6-scxml-dev \
  libvulkan-dev libxkbcommon-dev \
  libtraceevent-dev libtracefs-dev libtracecmd-dev trace-cmd doxygen binutils-dev

sudo pip3 install pkgconfig GitPython

# libtraceevent
cd /tmp/rq1-build/trace-cruncher
git clone https://git.kernel.org/pub/scm/libs/libtrace/libtraceevent.git/
cd libtraceevent
# git checkout b3f5849527ae226b88342ef8
git checkout tags/libtraceevent-1.8.4
make
sudo make install
cd /tmp/rq1-build/trace-cruncher

# libtracefs
cd /tmp/rq1-build/trace-cruncher
git clone https://git.kernel.org/pub/scm/libs/libtrace/libtracefs.git/
cd libtracefs
git checkout tags/libtracefs-1.8.2
make
sudo make install
cd /tmp/rq1-build/trace-cruncher

cd /tmp/rq1-build/trace-cruncher
git clone https://git.kernel.org/pub/scm/utils/trace-cmd/trace-cmd.git/
cd trace-cmd
git checkout tags/libtracecmd-1.5.4
make
sudo make install_libs
cd ..
cd /tmp/rq1-build/trace-cruncher

# kernel-shark
cd /tmp/rq1-build/trace-cruncher
git clone https://git.kernel.org/pub/scm/utils/trace-cmd/kernel-shark.git/
cd kernel-shark
git checkout 590e6ac1b549acdde0882e7f3318dec09aef6fd3
cd build
cmake ..
make
sudo make install
