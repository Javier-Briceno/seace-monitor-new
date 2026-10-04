# seace-monitor

Daily monitor for public works tenders (obras) on SEACE, Peru's public procurement portal.

Work in progress: the monitor searches SEACE, stores new licitaciones with their location and offer deadline, downloads their documents and sends a daily report by email: a short summary of the new obras, most urgent first, and a CSV with all of them. Fields from the bases are extracted by hand for now (see below).

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

## Daily report

Set the `SMTP_*` and `REPORT_TO` values in `.env` (see `.env.example`). Any SMTP account works;
for Gmail use `smtp.gmail.com` and an app password. `REPORT_TO` takes several addresses separated by commas.

An obra is marked as reported only after the mail server accepted the report, so a failed send
puts the same obras into the next report. A day without new obras still sends a report, so a
missing mail means something failed.

## Run

```
.venv/Scripts/python -m seace_monitor             # search, download, report, send
.venv/Scripts/python -m seace_monitor --no-mail   # write the report to data/informes without sending or marking
.venv/Scripts/python -m pytest
```

## Manual extraction

Until automatic extraction exists, a person reads the bases of the obras they pick from the report:

```
.venv/Scripts/python -m seace_monitor --plantilla <nid_proceso>
```

writes `data/extracciones/<nid_proceso>.toml` with every field and the section of the bases to look in
(the list lives in `src/seace_monitor/fields.py`). Fill `valor` and `pagina`, set `listo = true`, and the next
run imports it and lists it in the report, with all fields in a second CSV. Editing the file later replaces
the extraction and reports it again as a correction.

Database changes go into numbered files in `db/migrations/`, applied once each at startup.
