FROM debian:bullseye-slim
RUN apt update && apt install git autoconf automake make gcc m4 pkgconf -y

WORKDIR /opt/ltp-build
COPY ./build-ltp.sh /opt/ltp-build/build-ltp.sh

RUN git clone --recurse-submodules https://github.com/linux-test-project/ltp.git ltp
WORKDIR /opt/ltp-build/ltp

CMD ../build-ltp.sh
