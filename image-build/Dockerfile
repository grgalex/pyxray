FROM gradle:jdk21 as builder

RUN apt-get update && apt-get install -y curl git bison flex build-essential unzip

ENV VERSION 11.2.1_PUBLIC
ENV GHIDRA_SHA ce4db5117da0fbaf8f33863fec4f40902f754f06b68945a59fb1c0f9b1bc461c
ENV GHIDRA_URL https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_11.2.1_build/ghidra_11.2.1_PUBLIC_20241105.zip

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

RUN apt-get update && apt-get install -y fontconfig libxrender1 libxtst6 libxi6 wget unzip python3-requests --no-install-recommends \
    && wget --progress=bar:force -O /tmp/ghidra.zip ${GHIDRA_URL} \
    && echo "$GHIDRA_SHA /tmp/ghidra.zip" | sha256sum -c - \
    && unzip /tmp/ghidra.zip \
    && mv ghidra_${VERSION} /ghidra \
    && chmod +x /ghidra/ghidraRun \
    && echo "===> Clean up unnecessary files..." \
    && apt-get purge -y --auto-remove wget unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives /tmp/* /var/tmp/* /ghidra/docs /ghidra/Extensions/Eclipse /ghidra/licenses

WORKDIR /ghidra/support/gradle

RUN gradle buildNatives

##########################################################################################
FROM ubuntu:22.04 
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=UTC

RUN apt-get update && apt-get install -y sudo gdb libffi-dev software-properties-common gnupg2 jq
RUN apt-get update && apt-get install -y gcc g++ gfortran libopenblas-dev liblapack-dev pkg-config build-essential git
RUN apt-get update && apt-get install -y fontconfig libxrender1 libxtst6 libxi6 --no-install-recommends \
    && echo "===> Clean up unnecessary files..." \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives /tmp/* /var/tmp/*

RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update
RUN apt-get install -y python3.10 python3.10-distutils python3.10-dbg python3.10-dev python3.10-venv

RUN apt-get install -y libtiff5-dev libjpeg8-dev libopenjp2-7-dev zlib1g-dev \
    libfreetype6-dev liblcms2-dev libwebp-dev tcl8.6-dev tk8.6-dev python3-tk \
    libharfbuzz-dev libfribidi-dev libxcb1-dev \
    build-essential \
    cmake ninja-build git pkg-config curl wget unzip zip \
    libssl-dev libffi-dev libxml2-dev libxslt1-dev zlib1g-dev \
    libbz2-dev libreadline-dev libsqlite3-dev liblzma-dev \
    libjpeg-dev libpng-dev libfreetype6-dev \
    libblas-dev liblapack-dev gfortran \
    libopenblas-dev \
    libhdf5-dev libprotobuf-dev protobuf-compiler \
    libcurl4-openssl-dev rustc

RUN apt-get install -y openjdk-21-jdk vim

RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core build toolchain
    build-essential \
    pkg-config \
    cmake \
    ninja-build \
    autoconf \
    automake \
    libtool \
    m4 \
    gfortran \
    swig \
    git \
    curl \
    ca-certificates \
    patchelf \
    unzip \
    xz-utils \
    zlib1g-dev \

    # Common C/C++/system headers
    libffi-dev \
    libssl-dev \
    libbz2-dev \
    liblzma-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncursesw5-dev \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libfreetype6-dev \
    libblas-dev \
    liblapack-dev \
    libopenblas-dev \
    libgmp-dev \
    libmpdec-dev \
    libzstd-dev \
    libcurl4-openssl-dev \
    libexpat1-dev \

    # Language toolchains
    rustc \
    cargo \
    python3 \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
RUN python3.10 get-pip.py
RUN echo $(python3 --version)
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1

RUN pip install --break-system-packages pyhidra ghidra-stubs
RUN pip install networkx pipdeptree pypi_simple levenshtein configparser toml stdlib-list numpy matplotlib --ignore-installed
RUN pip install -U \
    pip \
    setuptools \
    wheel \
    build \
    setuptools_scm \
    virtualenv \
    packaging \
    tomli \
    cython \
    pybind11 \
    cmake \
    ninja \
    maturin \
    meson-python \
    scikit-build-core \
    setuptools-rust \
    auditwheel
COPY PyCG/ /PyCG
COPY prv-pyhidra-cg/ /prv-pyhidra-cg
COPY install-pycg.sh /install-pycg.sh
COPY trace-cruncher-deps.sh /trace-cruncher-deps.sh
RUN /install-pycg.sh
RUN /trace-cruncher-deps.sh

RUN apt update
RUN apt install -y portaudio19-dev
RUN rm -rf /var/lib/apt/lists/*

COPY --from=builder /ghidra /ghidra

ENTRYPOINT ["/bin/bash"]
