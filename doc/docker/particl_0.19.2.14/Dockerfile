# https://github.com/NicolasDorier/docker-bitcoin/blob/master/README.md

FROM debian:stretch-slim

RUN groupadd -r particl && useradd -r -m -g particl particl

RUN set -ex \
    && apt-get update \
    && apt-get install -qq --no-install-recommends ca-certificates dirmngr gosu gpg wget \
    && rm -rf /var/lib/apt/lists/*

ENV PARTICL_VERSION 0.19.2.14
ENV PARTICL_REPO particl
ENV PARTICL_FILE particl-${PARTICL_VERSION}-x86_64-linux-gnu_nousb.tar.gz
ENV PARTICL_URL https://github.com/${PARTICL_REPO}/particl-core/releases/download/v${PARTICL_VERSION}/
ENV PARTICL_SHA256 36a21b1af3dc83f4314ab0a14ae0c31f1944e411210b2a3864527700c977b944
ENV PARTICL_ASC_URL https://raw.githubusercontent.com/${PARTICL_REPO}/gitian.sigs/master/${PARTICL_VERSION}-linux/tecnovert/particl-linux-${PARTICL_VERSION}-build.assert
ENV PARTICL_SIG_URL https://raw.githubusercontent.com/${PARTICL_REPO}/gitian.sigs/master/${PARTICL_VERSION}-linux/tecnovert/particl-linux-${PARTICL_VERSION}-build.assert.sig
ENV PARTICL_PGP_KEY 8E517DC12EC1CC37F6423A8A13F13651C9CF0D6B

# install particl binaries
RUN set -ex \
    && cd /tmp \
    && wget -qO "$PARTICL_FILE" "$PARTICL_URL$PARTICL_FILE" \
    && echo "$PARTICL_SHA256 $PARTICL_FILE" | sha256sum -c - \
    && for key in \
        $PARTICL_PGP_KEY \
    ; do \
        gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "$key" || \
        gpg --batch --keyserver pgp.mit.edu --recv-keys "$key" || \
        gpg --batch --keyserver keyserver.pgp.com --recv-keys "$key" || \
        gpg --batch --keyserver ha.pool.sks-keyservers.net --recv-keys "$key" || \
        gpg --batch --keyserver hkp://p80.pool.sks-keyservers.net:80 --recv-keys "$key" ; \
    done \
    && wget -qO particl.asc "$PARTICL_ASC_URL" \
    && wget -qO particl.sig "$PARTICL_SIG_URL" \
    && sha256sum --ignore-missing --check particl.asc \
    && gpg --verify particl.sig particl.asc \
    && tar -xzvf "$PARTICL_FILE" -C /usr/local --strip-components=1 --exclude=*-qt \
    && rm -rf /tmp/*

ENV PARTICL_DATA /data
RUN mkdir -p "$PARTICL_DATA" \
    && chown -R particl:particl "$PARTICL_DATA" \
    && ln -sfn "$PARTICL_DATA" /home/particl/.particl \
    && chown -h particl:particl /home/particl/.particl
COPY particl.conf "$PARTICL_DATA/particl.conf"
VOLUME /data

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

EXPOSE 51735 20792 51738
CMD ["particld"]
