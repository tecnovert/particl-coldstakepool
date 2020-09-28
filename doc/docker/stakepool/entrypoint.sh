#!/bin/bash
set -e

chown -R stakepool_user "$STAKEPOOL_DATA"
exec gosu stakepool_user "$@"

