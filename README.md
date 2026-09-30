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
an HTTP proxy on `127.0.0.1:8888`. Any provider gluetun supports works if it has
servers in Peru; check the
[gluetun provider list](https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers)
for the provider name and which credentials it needs. The examples use NordVPN.

In `.env`, set `VPN_SERVICE_PROVIDER` and the credentials for your provider, then:

```
docker compose --profile vpn up -d --wait vpn
```

Only OpenVPN has been tested. `VPN_TYPE=wireguard` with `WIREGUARD_PRIVATE_KEY`
is passed to gluetun but untested here.

If the container stays unhealthy, read `docker compose logs vpn`:

- `TLS key negotiation failed`: no server answered. gluetun's built-in server
  list is probably out of date. Refresh it for your provider and start again:

  ```
  docker compose --profile vpn run --rm vpn update -enduser -providers <provider>
  # e.g. -providers nordvpn
  ```

- `AUTH_FAILED`: the server answered and rejected the credentials. Check `.env`;
  for NordVPN these are the service credentials, not the account login.

`[network] proxy` in `config.toml` switches between the proxy and a direct
connection. In Peru, leave it empty and skip the `vpn` service.

## Run

```
.venv/Scripts/python -m seace_monitor
.venv/Scripts/python -m pytest
```
