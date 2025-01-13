#!/bin/bash
git clone --recurse-submodules $LTP_REPO ltp
cd ltp
git checkout $LTP_BRANCH
make autotools
LINUX_VERSION=$(make -C /opt/ltp-build/linux -s kernelversion)
./configure --with-linux-version=$LINUX_VERSION --with-linux-dir=/opt/ltp-build/linux
make -j$(nproc)
make DESTDIR=/opt/ltp-build/ltp-deliverable install
