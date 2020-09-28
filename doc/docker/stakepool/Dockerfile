FROM python:3

RUN groupadd -r stakepool_group && useradd -r -m -g stakepool_group stakepool_user

RUN set -ex \
    && apt-get update \
    && apt-get install -qq --no-install-recommends ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*

RUN wget https://github.com/tecnovert/particl-coldstakepool/archive/master.zip && \
    unzip master.zip && \
    cd particl-coldstakepool-master && \
    python setup.py install

ENV STAKEPOOL_DATA /data
VOLUME /data

COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

CMD ["coldstakepool-run", "--datadir=/data"]
