FROM debian:stretch-slim


RUN set -ex && \
    apt-get update && \
    apt-get install -qq --no-install-recommends ca-certificates dirmngr gnupg gosu wget git build-essential curl nginx xz-utils apt-transport-https python2.7 && \
    rm -rf /var/lib/apt/lists/*

ENV NODE_VERSION "11.4.0"

# Install NodeJS:
RUN cd / && \
    wget https://nodejs.org/download/release/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz && \
    tar xvf node-v${NODE_VERSION}-linux-x64.tar.xz --strip-components=1 && \
    ls /bin && \
    ln -s /bin/node /usr/bin/nodejs && \
    ln -s /usr/bin/python2.7 /usr/bin/python && \
    node -v

# Install Yarn:
RUN curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add - && \
    echo "deb https://dl.yarnpkg.com/debian/ stable main" | tee /etc/apt/sources.list.d/yarn.list && \
    apt update && apt install  --no-install-recommends -y yarn


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

