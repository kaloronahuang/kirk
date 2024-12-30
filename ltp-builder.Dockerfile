FROM debian:bullseye-slim
RUN apt update && apt install autoconf automake build-essential debhelper devscripts clang gcc git iproute2 libc6-dev libtirpc-dev linux-libc-dev lsb-release pkg-config acl-dev asciidoc-base asciidoc-dblatex asciidoctor libacl1-dev libaio-dev libcap-dev libjson-perl libkeyutils-dev libnuma-dev libmnl-dev libselinux1-dev libsepol-dev libssl-dev -y

WORKDIR /opt/ltp-build
COPY ./build-ltp.sh /opt/ltp-build/build-ltp.sh

CMD ./build-ltp.sh
