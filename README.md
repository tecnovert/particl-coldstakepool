
# Particl Cold-Staking Pool - Proof of concept

## Overview

Pool participants send their coin to a coldstake script with a stake
address owned by the pool and a spend address owned by the participant.

The pool can only stake such outputs, participants can withdraw their
coin without interacting with the pool.


A pool-fee is deducted from each block staked by the pool. This fee
should cover the costs of running the pool as well as the transaction
fees of the payouts.

An optional stake bonus can be deducted from the block reward to be
assigned to the spend script of the staked output.

The remaining block reward is accumulated to the pool participants
spend scripts in proportion to the amount of coin each spend script has
in the pool.


Participants are incentivised to split their pooled coin to few spend
scripts to increase the frequency of the payouts and increase their
chances of claiming stake bonuses.

The pool can split or join outputs on the same scripts.  If a
participant starts with an output of 200 part and sends a further 1
part output to the pool on the same script the pool will join the
outputs when either output stakes. Both outputs must be below the
'stakecombinethreshold' setting to join.


Coin sent to the pool must be stakeable before it starts to accrue
rewards. Outputs must be 225 blocks deep in the chain they can stake.





The pool must run at least 100 blocks behind the main chain.  At this
depth all stake rewards should be matured and forks resolved.


Participants can verify a pool is operating correctly by running the
pool script in 'observer' mode.


The pool should isolate the accumulated reward coin in a non-staking
wallet. Change from payout transactions should go back to the pool
reward address for easier tracking by observers.


## Notes

Amount accumulation is done at 16 decimal places.

The staking wallet and the reward wallet don't need to be in the same
node.

The stake bonus could be attributed to the output in the coinstake txn,
adding it to the spend script's accumulated coin will cause the lot to
be paid out sooner.


When reloading a pool, run the script in observer mode until synced
then switchover to master. If reloading in master mode the script will
attempt to make payments that have already been paid.


## Further Work:

- Track extaddress stake address

- Email payout info to pool operator for offline signing.

- SMSG announcements
