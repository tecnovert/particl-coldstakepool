# Stakepool Setup on Ubuntu Xenial

This example should be run as a user named `stakepooluser`. To run as a different user replace all instances of `stakepooluser` with your username both in this guide and in the `.service` files in the config directory; eg:

    sed -i -- 's/stakepooluser/YOURUSERNAME/g' config/*.service

## 1. Preparation

First login to your VPS, replace `stakepoolvps` with the correct IP address of your server

    $ ssh stakepooluser@stakepoolvps

Update your packages, install all dependencies:

    sudo apt-get update
    sudo apt-get install gnupg wget python3 git nginx tmux python3-zmq python3-pip lynx htop vim libleveldb-dev

## 2. Installation

Clone `coldstakepool` git repository and install it:

    git clone https://github.com/particl/coldstakepool particl_stakepool
    cd particl_stakepool
    sudo pip3 install .

### Testnet Pool

```
$ coldstakepool-prepare -datadir=~/stakepoolDemoTest -testnet
NOTE: Save both recovery phrases:
Stake wallet recovery phrase: (...)
Reward wallet recovery phrase: (...)
Stake address: tpcs1mwk4e0z4ll8p6n6wl0hm8l9slyf2vcgjatzwxh
Reward address: poiXfkxxB5eeEgvL3MZN1pxPq9Bfwh7tEm
```

Adjust the startheight parameter to a block before the pool began operating.  Earlier blocks won't be scanned by the pool:

    vi ~/stakepoolDemoTest/stakepool/stakepool.json

Copy over `systemd` service files to your system:

    sudo cp ~/particl_stakepool/doc/config/*.service /etc/systemd/system
    sudo systemctl daemon-reload

Start and enable the services, so they start automatically at system boot:

    sudo systemctl start particld_test.service stakepool_test.service
    sudo systemctl enable particld_test.service stakepool_test.service

#### Verify all is running

    sudo tail -f /var/log/syslog
    ~/particl-binaries/particl-cli -datadir=${HOME}/stakepoolDemoTest getblockchaininfo
    lynx localhost:9001


### Mainnet Pool

Stop the testnet pool (if running):

    sudo systemctl stop particld_test.service stakepool_test.service

```
$ coldstakepool-prepare -datadir=~/stakepoolDemoLive
NOTE: Save both the recovery phrases:
Stake wallet recovery phrase: (...)
Reward wallet recovery phrase: (...)
Stake address: pcs14ch7w7ue2q8kadljsl42wehfw8tm99yxsez4kz
Reward address: PbXgDsRurjpCYXxNryin13h86ufks9zh6o
```

Adjust the startheight parameter.

    vi ~/stakepoolDemoLive/stakepool/stakepool.json

Copy over `systemd` service files to your system:

    sudo cp ~/particl_stakepool/doc/config/*.service /etc/systemd/system
    sudo systemctl daemon-reload

Start and enable the services, so they start automatically at system boot:

    sudo systemctl start particld_live.service stakepool_live.service
    sudo systemctl enable particld_live.service stakepool_live.service

#### Verify all is running

    sudo tail -f /var/log/syslog
    ~/particl-binaries/particl-cli -datadir=${HOME}/stakepoolDemoLive getblockchaininfo
    lynx localhost:9000

## 3. Set up webserver

    sudo rm /etc/nginx/sites-enabled/default
    sudo cp ~/particl_stakepool/doc/config/nginx_stakepool_forward.conf /etc/nginx/conf.d/

    sudo nginx -t

    sudo systemctl stop nginx
    sudo systemctl start nginx
    sudo systemctl enable nginx

To test, browse to:

  - http://vpsip:900/ (mainnet pool)
  - http://vpsip:901/ (testnet)

Check that it all starts back up:

    sudo reboot

### Production config

The production configuration enables:

  - caching (expires after 2 minutes)
  - uses port 80
  - HTTPS / TLS support

    mkdir /tmp/nginx
    sudo rm /etc/nginx/conf.d/nginx_stakepool_forward.conf
    sudo cp ~/particl_stakepool/doc/config/nginx_stakepool_production.conf /etc/nginx/conf.d/
    sudo systemctl restart nginx

To test, browse to:

  - http://vpsip/api/
  - http://vpsip/api/testnet/

### Fancy frontend

Install NodeJS:

    wget -qO- https://raw.githubusercontent.com/creationix/nvm/v0.33.11/install.sh | bash
    nvm install node

Install yarn:

    curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | sudo apt-key add -
    echo "deb https://dl.yarnpkg.com/debian/ stable main" | sudo tee /etc/apt/sources.list.d/yarn.list
    sudo apt-get update && sudo apt-get install yarn

Clone & install fancy frontend

    git clone https://github.com/gerlofvanek/particl-coldstakepool-front
    cd particl-coldstakepool-front
    yarn install
    yarn run build
    cp -R dist /var/www/html/pool

Setup a domain name: https://kerneltalks.com/howto/how-to-setup-domain-name-in-linux-server/

Setup TLS:

    sudo apt-get update
    sudo apt-get install software-properties-common
    sudo add-apt-repository ppa:certbot/certbot
    sudo apt-get update
    sudo apt-get install python-certbot-nginx

Create the certificates, enter your domain name in the interactive wizard:

    sudo certbot --nginx certonly

Edit the `/etc/nginx/conf.d/nginx_stakepool_production.conf`, uncomment the 4 settings from the configuration that related to SSL & replace `example.com` with your domain name:

    vi /etc/nginx/conf.d/nginx_stakepool_production.conf
    sudo systemctl restart nginx
