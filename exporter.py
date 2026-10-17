import logging
import os
import time

import httpx
from prometheus_client import CollectorRegistry, Gauge, start_http_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pdu-exporter")

PDU_HOST = os.environ["PDU_HOST"]
PDU_USER = os.environ["PDU_USER"]
PDU_PASSWORD = os.environ["PDU_PASSWORD"]
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "30"))
PORT = 9877

registry = CollectorRegistry()

outlet_watts = Gauge("pdu_outlet_watts", "Outlet power in watts", ["outlet"], registry=registry)
outlet_amps = Gauge("pdu_outlet_amps", "Outlet current in amps", ["outlet"], registry=registry)
outlet_volts = Gauge("pdu_outlet_volts", "Outlet voltage in volts", ["outlet"], registry=registry)
outlet_watt_hours = Gauge("pdu_outlet_watt_hours_total", "Outlet energy in watt-hours", ["outlet"], registry=registry)
outlet_status = Gauge("pdu_outlet_status", "Outlet switch status (1=on, 0=off)", ["outlet"], registry=registry)

infeed_watts = Gauge("pdu_infeed_watts", "Infeed power in watts", ["infeed"], registry=registry)
infeed_amps = Gauge("pdu_infeed_amps", "Infeed current in amps", ["infeed"], registry=registry)
infeed_volts = Gauge("pdu_infeed_volts", "Infeed voltage in volts", ["infeed"], registry=registry)
infeed_hz = Gauge("pdu_infeed_hz", "Infeed frequency in Hz", ["infeed"], registry=registry)
infeed_pf = Gauge("pdu_infeed_power_factor", "Infeed power factor", ["infeed"], registry=registry)

temp_celsius = Gauge("pdu_internal_temp_celsius", "Internal temperature in Celsius", registry=registry)
scrape_success = Gauge("pdu_scrape_success", "Whether the last scrape succeeded", registry=registry)

def make_client() -> httpx.Client:
    return httpx.Client(base_url=f"http://{PDU_HOST}", timeout=10)


def login(client: httpx.Client) -> None:
    resp = client.post("/login_auth.csp", data={"auth_user": PDU_USER, "auth_passwd": PDU_PASSWORD})
    resp.raise_for_status()


def is_session_expired(data: dict) -> bool:
    return "Login" in data


def fetch_json(client: httpx.Client, path: str) -> dict:
    resp = client.get(path)
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception as exc:
        raise ValueError(f"Non-JSON response from {path}") from exc
    if is_session_expired(data):
        raise PermissionError("Session expired")
    return data


def scrape(client: httpx.Client) -> None:
    params = fetch_json(client, "/dev_param.csp")
    status = fetch_json(client, "/dev_status.csp")

    outlet_names: dict[int, str] = {o["Id"]: o["Name"] for o in params.get("OutConf", [])}

    switch_map: dict[int, int] = {s["Id"]: s["OutStat"] for s in status.get("OutSwitch", [])}

    for meter in status.get("OutMeter", []):
        oid = meter["Id"]
        name = outlet_names.get(oid, str(oid))
        outlet_watts.labels(outlet=name).set(meter["Watt"])
        outlet_amps.labels(outlet=name).set(meter["Amp"])
        outlet_volts.labels(outlet=name).set(meter["Voltage"])
        outlet_watt_hours.labels(outlet=name).set(meter["WattHour"])
        outlet_status.labels(outlet=name).set(switch_map.get(oid, 0))

    for feed in status.get("Infeed", []):
        fid = str(feed["Id"])
        infeed_watts.labels(infeed=fid).set(feed["Watt"])
        infeed_amps.labels(infeed=fid).set(feed["Amp"])
        infeed_volts.labels(infeed=fid).set(feed["Voltage"])
        infeed_hz.labels(infeed=fid).set(feed["Hz"])
        infeed_pf.labels(infeed=fid).set(feed["PF"])

    for sensor in status.get("InTemp", []):
        temp_celsius.set(sensor["Temp"])
        break


def run() -> None:
    # Serve metrics before the first login. Logging in first meant a PDU that
    # was unreachable at pod start killed the process with an uncaught
    # exception, so pdu_scrape_success never existed and an alert on it could
    # not fire. Only an absent-metrics alert covered that case.
    start_http_server(PORT, registry=registry)

    client: httpx.Client | None = None
    failures = 0

    while True:
        try:
            if client is None:
                client = make_client()
                login(client)
                log.info("logged in to PDU at %s", PDU_HOST)
            scrape(client)
            if failures:
                log.info("PDU scrape recovered after %d failed attempts", failures)
            failures = 0
            scrape_success.set(1)
        except Exception as exc:
            # Every failure discards the client, so the next iteration logs in
            # again. Only PermissionError used to do that, and PermissionError
            # requires a parsed JSON body carrying a "Login" key: a session that
            # expired into an HTML login page raised ValueError instead, which
            # this loop swallowed without re-authenticating. The exporter then
            # reported 0 forever with no log line explaining why, until someone
            # restarted the pod.
            failures += 1
            # Traceback on the first failure only; after that the loop would
            # repeat it every SCRAPE_INTERVAL for as long as the PDU is down.
            log.warning(
                "PDU scrape failed (attempt %d): %s: %s",
                failures,
                type(exc).__name__,
                exc,
                exc_info=failures == 1,
            )
            scrape_success.set(0)
            # Drop the reference before closing, and swallow a failing close:
            # an exception escaping this handler would kill the loop and leave
            # the pod in exactly the stuck state this change removes.
            stale, client = client, None
            if stale is not None:
                try:
                    stale.close()
                except Exception:
                    log.debug("closing the stale PDU client raised", exc_info=True)
        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    run()
