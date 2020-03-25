# Upgrading particld daemon

This guide covers upgrading Particl daemon, when a new version is available.

## 1. Preparation

Login to your machine, replace `stakepoolvps` with the IP address or url of your pool:

    $ ssh stakepooluser@stakepoolvps

Shut down the pool and daemon (second line applies if you're running testnet version as well):

    $ sudo systemctl stop stakepool_live.service particld_live.service
    $ sudo systemctl stop stakepool_test.service particld_test.service

## 2. Update `coldstakepool` & `particld` to latest version

Update the coldstakepool code:

    $ cd ~/particl_stakepool
    $ git pull
    $ sudo pip3 install --upgrade .

Update Particl Core:

    $ coldstakepool-prepare --update_core

Output should end (if successful) with lines similar to:

    particld --version
    Particl Core Daemon version v0.18.1.3.2-ecea0356a

## 3. Restart the pool

Start the pool/s back up (second line applies if you're running testnet version as well):

    $ sudo systemctl start stakepool_live.service
    $ sudo systemctl start stakepool_test.service

Verify if everything is running correctly:

```
$ ~/particl-binaries/particl-cli -datadir=${HOME}/stakepoolDemoLive getnetworkinfo
{
  "version": 18010302,
  "subversion": "/Satoshi:0.18.1.3.2/",
(..)
```

```
$ tail -n 1000 ~/stakepoolDemoLive/stakepool/stakepool.log | grep version
20-03-25_13-58-46	coldstakepool-run, version: 0.0.15
20-03-25_13-58-56	Particl Core version 18010302
```

In your browser, open `http://stakepoolvpsip:900/json/version`, you should see this:

    {"core": "18010302", "pool": "0.0.15"}

----

## Notes

You can select specific versions of Particl Core and where to place them using the following environment variables:

    $ PARTICL_BINDIR=~/particl-alpha PARTICL_VERSION=0.18.0.1 PARTICL_VERSION_TAG=alpha coldstakepool-prepare --update_core
