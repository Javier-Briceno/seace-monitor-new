# seace-monitor

Daily monitor for public works tenders (obras) on SEACE, Peru's public procurement portal.

Work in progress: the search step runs, nothing is stored or reported yet.

## Setup

```
cp .env.example .env              # database settings, VPN credentials if needed
cp config.example.toml config.toml
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"   # .venv/bin/pip on Linux/macOS
docker compose up -d --wait             # Postgres
```

## Access from outside Peru

SEACE answers `403 Forbidden` to IPs outside Peru. The `vpn` service runs
[gluetun](https://github.com/qdm12/gluetun) with your own VPN account and exposes
an HTTP proxy on `127.0.0.1:8888`:

```
docker compose --profile vpn up -d --wait vpn
```

`[network] proxy` in `config.toml` switches between the proxy and a direct
connection. In Peru, leave it empty and skip the `vpn` service.

## Run

```
.venv/Scripts/python -m seace_monitor
.venv/Scripts/python -m pytest
```
