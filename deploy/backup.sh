#!/bin/sh
# Daily dump of the monitor's database into backups/, keeping the last 14.
set -eu
cd /opt/seace-monitor-new
mkdir -p backups
out="backups/seace-$(date +%Y-%m-%d).dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$out.part"
mv "$out.part" "$out"
ls -1t backups/seace-*.dump | tail -n +15 | xargs -r rm --

# Downloads grow a few GB a week; failing here mails the warning through seace-fallo@ before the disk is full.
free_gb=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
if [ "$free_gb" -lt 8 ]; then
    echo "only ${free_gb} GB free on the server disk; closed obras' files can move off it"
    exit 1
fi
