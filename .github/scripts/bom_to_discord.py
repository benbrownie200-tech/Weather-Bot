import os
import json
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

# ===== CONFIG =====
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
# QLD storm / flood / cyclone warnings (CAP-AU)
QLD_CAP_URL = (
    "https://publiccontent-gis-psba-qld-gov-au.s3.ap-southeast-2.amazonaws.com/"
    "content/Feeds/StormFloodCycloneWarnings/StormWarnings_capau.xml"
)
STATE_FILE = Path("sent_warnings.json")

# if set to "1", we will POST whatever we find (for testing)
FORCE_SEND = os.getenv("FORCE_SEND", "0") == "1"


def load_sent_ids():
    if not STATE_FILE.exists():
        return set()
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_sent_ids(ids):
    STATE_FILE.write_text(json.dumps(list(ids), indent=2), encoding="utf-8")


def fetch_cap_feed():
    resp = requests.get(QLD_CAP_URL, timeout=20)
    resp.raise_for_status()
    return resp.content


def parse_cap_alerts(xml_bytes):
    root = ET.fromstring(xml_bytes)
    alerts = []

    for alert in root.findall(".//{*}alert"):
        identifier_el = alert.find("./{*}identifier")
        headline_el = alert.find(".//{*}headline")
        description_el = alert.find(".//{*}description")
        web_el = alert.find(".//{*}web")

        identifier = identifier_el.text.strip() if identifier_el is not None and identifier_el.text else None
        headline = headline_el.text.strip() if headline_el is not None and headline_el.text else "Weather Warning"
        description = description_el.text.strip() if description_el is not None and description_el.text else None
        link = web_el.text.strip() if web_el is not None and web_el.text else QLD_CAP_URL

        alerts.append(
            {
                "id": identifier or headline,
                "headline": headline,
                "description": description,
                "link": link,
            }
        )

    return alerts


def send_to_discord(alert):
    if not DISCORD_WEBHOOK_URL:
        raise SystemExit("DISCORD_WEBHOOK_URL not set.")

    desc = alert["description"] or "See source for details."

    payload = {
        "username": "QLD Warnings (BOM/QFES)",
        "embeds": [
            {
                "title": f"⚠️ {alert['headline']}",
                "description": desc[:3500],
                "url": alert["link"],
                "color": 0xFF6600,
                "footer": {"text": "Source: QLD Storm/Flood/Cyclone CAP feed"},
            }
        ],
    }

    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    r.raise_for_status()


def send_info_message(msg: str):
    if not DISCORD_WEBHOOK_URL:
        return
    payload = {
        "username": "QLD Warnings (BOM/QFES)",
        "content": msg,
    }
    requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)


def main():
    xml_bytes = fetch_cap_feed()
    alerts = parse_cap_alerts(xml_bytes)
    sent_ids = load_sent_ids()

    # if we want to force a Discord message (for testing)
    if FORCE_SEND:
        if alerts:
            for alert in alerts:
                send_to_discord(alert)
            # still update state
            new_ids = {a["id"] for a in alerts if a["id"]}
            save_sent_ids(new_ids)
        else:
            send_info_message("ℹ️ No current QLD storm/flood/cyclone warnings in CAP feed.")
        print("Force-sent current alerts.")
        return

    # normal mode below

    # first run: record what exists, don't spam
    if not sent_ids and alerts:
        new_ids = {a["id"] for a in alerts if a["id"]}
        save_sent_ids(new_ids)
        print("Initialised with current warnings (no Discord post).")
        return

    if not alerts:
        # send "no warnings" once per run
        print("No alerts in feed.")
        send_info_message("ℹ️ No current QLD storm/flood/cyclone warnings.")
        return

    new_alerts = [a for a in alerts if a["id"] not in sent_ids]

    if not new_alerts:
        print("No new warnings.")
        return

    for alert in new_alerts:
        print("Sending:", alert["headline"])
        send_to_discord(alert)
        if alert["id"]:
            sent_ids.add(alert["id"])

    save_sent_ids(sent_ids)
    print("Done.")


if __name__ == "__main__":
    main()
