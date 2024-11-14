#!/bin/bash
make autotools
LINUX_VERSION=$(make -C ../linux -s kernelversion)
./configure --with-linux-version=$LINUX_VERSION --with-linux-dir=../linux
make -j$(nproc)
make DESTDIR=/opt/ltp-build/ltp-deliverable install
