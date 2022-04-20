# Stakepool Release Notes

## 0.21.0

- Compact leveldb every 5000 blocks
- Use rapidjson or ujson if available
- Abort after failure in processPoolBlock()
- NOTE: If upgrading from a core release <= 0.19.2.18 the Particl chain must be reindexed.
  - To update the csindex to use the changed address typeids.


## 0.20.0

- Added Voting Settings page


## 0.0.18

- Pool reward withdrawal to weighted addresses.
- Track 20byte p2sh addresses.
- rpchost and rpcauth can be specified in stakepool.json
- Added noprepare_binaries, noprepare_daemon, rpcauth and rescan_from options to coldstakepool-prepare
