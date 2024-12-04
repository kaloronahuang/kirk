FROM debian:bullseye-slim
RUN apt update && apt install git autoconf automake make gcc m4 pkgconf -y

WORKDIR /opt/ltp-build
COPY ./build-ltp.sh /opt/ltp-build/build-ltp.sh

CMD ./build-ltp.sh
