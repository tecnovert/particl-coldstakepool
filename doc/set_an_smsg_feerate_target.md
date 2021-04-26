# Setting an SMSG fee rate target.


Shut down the pool and daemon (second line only applies if you're running testnet):

    sudo systemctl stop stakepool_live.service particld_live.service
    sudo systemctl stop stakepool_test.service particld_test.service


Edit the height based parameters in stakepool.json

    vi ~/stakepoolDemoLive/stakepool/stakepool.json


For example, change:

    "parameters": [
        {
            "height": 0,
            "minoutputvalue": 0.1,
            "minblocksbetweenpayments": 100,
            "payoutthreshold": 0.5,
            "stakebonuspercent": 5,
            "poolfeepercent": 3
        }
    ],


To:

    "parameters": [
        {
            "height": 0,
            "smsgfeeratetarget": 0.0003,
            "minoutputvalue": 0.1,
            "minblocksbetweenpayments": 100,
            "payoutthreshold": 0.5,
            "stakebonuspercent": 5,
            "poolfeepercent": 3
        }
    ],


You could also add a new object to parameters, that would apply from height:

    "parameters": [
        {
            "height": 0,
            "minoutputvalue": 0.1,
            "minblocksbetweenpayments": 100,
            "payoutthreshold": 0.5,
            "stakebonuspercent": 5,
            "poolfeepercent": 3
        },
        {
            "height": 100000,
            "smsgfeeratetarget": 0.0003,
        }
    ],


Start the pool/s back up (second line only applies if you're running testnet):

    sudo systemctl start stakepool_live.service
    sudo systemctl start stakepool_test.service


Test the fee rate target is set:

    ~/particl-binaries/particl-cli -datadir=${HOME}/stakepoolDemoLive -rpcwallet=pool_stake walletsettings stakingoptions


You should see smsgfeeratetarget in the output.
