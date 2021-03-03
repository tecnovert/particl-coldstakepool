# Docker Config

Create the network and images:

    docker network create stakepool_network
    docker-compose build


Create the data directories and place particl.conf:

    sudo mkdir -p /var/data/{particl/wallets,stakepool}
    sudo cp particl_0.19.2.5/particl.conf /var/data/particl/particl.conf


Create RPC auth details:

    python rpcauth.py test_user test_password


Edit particl.conf:

    sudo echo "rpcauth=<output_from_rpcauth.py>" | sudo tee -a /var/data/particl/particl.conf
    sudo sed -i 's/207922/20792/g' /var/data/particl/particl.conf


Prepare stakepool config and wallets:

    docker-compose up -d particl_core
    docker run -t --name stakepool_prepare --env RPC_HOST=particl_core --network stakepool_network -v /var/data/stakepool:/data i_particl_stakepool coldstakepool-prepare --noprepare_binaries --noprepare_daemon --rpcauth=test_user:test_password --pooldir=/data --rescan_from=-1


Record the pool mnemonics from the output of the above command.

Remove stakepool_prepare container (and logs):

    docker rm stakepool_prepare


Edit stakepool.json:

    sudo sed -i 's/207922/20792/g' /var/data/stakepool/stakepool.json
    sudo sed -i 's/localhost/0.0.0.0/g' /var/data/stakepool/stakepool.json


Configure `/var/data/stakepool/stakepool.json` further as required.

Start core and stakepool:

    docker-compose stop
    docker-compose up -d


### With GUI

Write config once:

    cd doc/docker
    echo -e "STAKEPOOL_GUI_HOST=<DOMAIN_HERE>\nSTAKEPOOL_GUI_EMAIL=<EMAIL_HERE>\n" > .env


Start letsencrypt-proxy:

    cd letsencrypt
    docker-compose up -d


Start core, stakepool and gui:

    docker-compose -f docker-compose_with-gui.yml up -d


### Upgrade Core

    cd doc/docker
    docker-compose -f docker-compose_with-gui.yml stop
    cd ../..
    git pull
    cd doc/docker
    docker-compose -f docker-compose_with-gui.yml build --no-cache
    docker-compose -f docker-compose_with-gui.yml up -d

