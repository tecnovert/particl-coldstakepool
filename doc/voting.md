# Stakepool Voting Notes


### Set a vote

ssh into the server running the stakepool.

    ssh stakepoolvps

Set the `pool_stake` wallet to vote for option 2 on proposal 1 from block 10 to 20

    ~/particl-binaries/particl-cli -datadir=${HOME}/stakepoolDemoLive -rpcwallet=pool_stake setvote 1 2 10 20


If multiple vote settings are added with overlapping heights the last setting added will be applied.


#### Docker Example:

    cd particl-coldstakepool/doc/docker
    sudo docker-compose run --rm particl_core particl-cli -rpcconnect=particl_core -rpcwallet=pool_stake setvote 1 2 10 20

