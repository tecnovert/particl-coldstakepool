# Upgrading to packaged code

This guide covers transition from an old install on Ubuntu Xenial to using the new packaged code.

## 1. Upgrade and verify installation

Login to your machine, replace `stakepoolvps` with the correct IP address of your server:

    $ ssh stakepooluser@stakepoolvps

Install the required packages:

    $ sudo apt-get install python3-pip python3-setuptools

Clone the new code and install package:

    $ git clone https://github.com/particl/coldstakepool particl_stakepool

```
$ cd particl_stakepool
$ sudo pip3 install .
```

Verify install worked:

    $ coldstakepool-run -v
    Particl coldstakepool version: 0.0.10

Update script path in service files:

    $ sudo sed -i -- 's^ExecStart=/usr/bin/python3 /home/stakepooluser/stakepool/stakepool.py^ExecStart=/usr/local/bin/coldstakepool-run^g' /etc/systemd/system/stakepool_*.service

Verify:

```
$ cat /etc/systemd/system/stakepool_live.service | grep coldstakepool-run
ExecStart=coldstakepool-run -datadir=~/stakepoolDemoLive/stakepool
```

```
$ cat /etc/systemd/system/stakepool_test.service | grep coldstakepool-run
ExecStart=coldstakepool-run -datadir=~/stakepoolDemoTest/stakepool -testnet
```

Reload service files:

    $ sudo systemctl daemon-reload

## 2. Restart pool(s)

Restart stakepools (second line applies to testnet pool, if you're running it):

    $ sudo systemctl restart stakepool_live.service
    $ sudo systemctl restart stakepool_test.service

Verify if all is running correctly:

```
$ systemctl status stakepool_live.service
(..)
Active: active (running)
```

Exit status via `Ctrl` + `C`

```
$ tail -n 100 ~/stakepoolDemoLive/stakepool/stakepool.log | grep coldstakepool
coldstakepool-run, version: 0.0.10
```
