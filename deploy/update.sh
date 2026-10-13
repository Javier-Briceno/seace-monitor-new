#!/bin/sh
# Bring the server to the newest main and rebuild the image; the next timer run uses it.
set -eu
cd "$(dirname "$0")/.."
git fetch --quiet origin
git checkout --quiet main
git merge --quiet --ff-only origin/main
docker compose --profile monitor build monitor
sh deploy/install.sh
