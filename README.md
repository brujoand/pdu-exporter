# pdu-exporter

A Prometheus exporter for the Planet IPM-8220 switched PDU. It logs in to the
PDU's web interface, polls `/dev_param.csp` and `/dev_status.csp`, and serves
per-outlet and per-infeed readings on port 9877.

## Run

```bash
docker run --rm -p 9877:9877 \
  -e PDU_HOST=pdu.example.com \
  -e PDU_USER=admin \
  -e PDU_PASSWORD=... \
  ghcr.io/brujoand/pdu-exporter:latest
```

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `PDU_HOST` | yes | | Host or address of the PDU's web interface (plain HTTP) |
| `PDU_USER` | yes | | Web login user |
| `PDU_PASSWORD` | yes | | Web login password |
| `SCRAPE_INTERVAL` | no | `30` | Seconds between polls |

## Metrics

- Per outlet (label `outlet`): `pdu_outlet_watts`, `pdu_outlet_amps`,
  `pdu_outlet_volts`, `pdu_outlet_watt_hours_total`, `pdu_outlet_status`
  (1 on, 0 off).
- Per infeed (label `infeed`): `pdu_infeed_watts`, `pdu_infeed_amps`,
  `pdu_infeed_volts`, `pdu_infeed_hz`, `pdu_infeed_power_factor`.
- `pdu_internal_temp_celsius`.
- `pdu_scrape_success`: 1 when the last poll succeeded. It is served from
  startup, so an unreachable PDU shows up as 0 instead of a missing target.

Any failed poll drops the session and logs in again on the next one.

## Image

Every push to `main` builds `ghcr.io/brujoand/pdu-exporter` and tags it
`latest` and `sha-<commit>`.
