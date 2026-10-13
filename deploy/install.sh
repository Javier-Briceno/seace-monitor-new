#!/bin/sh
# Install the systemd units for the checkout this script sits in; run again after moving it.
set -eu
app_dir=$(cd "$(dirname "$0")/.." && pwd)
for unit in "$app_dir"/deploy/*.service "$app_dir"/deploy/*.timer; do
    sed "s#@APP_DIR@#$app_dir#g" "$unit" > "/etc/systemd/system/$(basename "$unit")"
done
systemctl daemon-reload
