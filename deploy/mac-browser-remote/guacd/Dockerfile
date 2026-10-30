FROM guacamole/guacd:1.6.0@sha256:8974eaa9ba32f713daf311e7cc8cd7e4cdfba1edea39eed75524e78ef4b08f4f AS upstream

FROM upstream AS builder
USER root
RUN apk add --no-cache build-base cairo-dev libjpeg-turbo-dev libpng-dev \
    libtool libvorbis-dev libwebp-dev openssl1.1-compat-dev pango-dev \
    pulseaudio-dev util-linux-dev
WORKDIR /build
RUN wget -q https://archive.apache.org/dist/guacamole/1.6.0/source/guacamole-server-1.6.0.tar.gz \
    && echo '8bc45675da96d7b6f39728160181e3d4ff3c08f460f6d26de5805b642bf13f2b  guacamole-server-1.6.0.tar.gz' | sha256sum -c - \
    && tar -xzf guacamole-server-1.6.0.tar.gz
COPY vnc-password-auth.patch /build/
WORKDIR /build/guacamole-server-1.6.0
RUN patch -p1 < /build/vnc-password-auth.patch
RUN PKG_CONFIG_PATH=/opt/guacamole/lib/pkgconfig \
    ./configure --prefix=/opt/guacamole --disable-guacd --disable-guaclog \
    --without-rdp --without-telnet \
    CPPFLAGS='-I/opt/guacamole/include -Wno-error=deprecated-declarations' \
    LDFLAGS='-L/opt/guacamole/lib' \
    && make -j2

FROM upstream
COPY --from=builder /build/guacamole-server-1.6.0/src/protocols/vnc/.libs/libguac-client-vnc.so.0.0.0 /opt/guacamole/lib/libguac-client-vnc.so.0.0.0
