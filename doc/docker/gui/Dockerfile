FROM debian:bookworm-slim

RUN set -ex && \
    apt-get update && \
    apt-get install -qq --no-install-recommends ca-certificates dirmngr gnupg gosu git build-essential curl nginx xz-utils apt-transport-https python3 && \
    rm -rf /var/lib/apt/lists/*

ENV ARCH="x64"
ENV NODE_VERSION="11.15.0"

# Install NodeJS:
RUN cd / && \
    curl -fsSLO --compressed "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$ARCH.tar.xz" && \
    tar -xJf "node-v$NODE_VERSION-linux-$ARCH.tar.xz" -C /usr/local --strip-components=1 --no-same-owner && \
    rm "node-v$NODE_VERSION-linux-$ARCH.tar.xz" && \
    ln -s /usr/local/bin/node /usr/local/bin/nodejs && \
    node -v

# Install Yarn:
RUN curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add - && \
    echo "deb https://dl.yarnpkg.com/debian/ stable main" | tee /etc/apt/sources.list.d/yarn.list && \
    apt update && apt install --no-install-recommends -y yarn

RUN git clone https://github.com/gerlofvanek/particl-coldstakepool-front && \
    cd particl-coldstakepool-front && \
    sed -i "s/''/'api'/g" src/environments/environment.prod.ts && \
    sed -i "s/''/'api'/g" src/environments/environment.ts && \
    yarn install && \
    yarn run build && \
    cp -R dist /var/www/html/pool

RUN rm /etc/nginx/sites-enabled/*

COPY ./nginx.conf /etc/nginx/conf.d/

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

