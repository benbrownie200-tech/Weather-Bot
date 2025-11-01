import os
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# CONFIG
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
BOM_WARNINGS_URL = "https://www.bom.gov.au/products/warn_qld.shtml"
STATE_FILE = Path("sent_warnings.json")

KEYWORDS = [
    "Warning",
    "Severe",
    "Thunderstorm",
    "Cyclone",
    "Flood",
    "Heatwave",
    "Tsunami",
    "Fire Weather",
]


def load_sent():
    if not STATE_FILE.exists():
        return set()
    try:
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_sent(sent_set):
    STATE_FILE.write_text(json.dumps(list(sent_set), indent=2), encoding="utf-8")


def fetch_bom_warnings():
    """
    Scrape current warnings from BOM QLD page.
    If BOM tweaks HTML, you may need to adjust selectors.
    """
    resp = requests.get(BOM_WARNINGS_URL, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    found = []

    # Try to be generous because BOM’s layout can move around during site changes.
    for tag in soup.find_all(["li", "p", "a", "div"]):
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        # Only keep likely warnings
        if any(k in text for k in KEYWORDS):
            # Avoid “Warnings current:” label itself
            if "Warnings current" in text:
                continue
            found.append(text)

    # Deduplicate but keep order
    seen = set()
    unique = []
    for w in found:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return unique


def send_discord(warning_text):
    if not DISCORD_WEBHOOK_URL:
        raise SystemExit("DISCORD_WEBHOOK_URL not set.")

    payload = {
        "username": "BOM Warnings (QLD)",
        "embeds": [
            {
                "title": "⚠️ New BOM Warning",
                "description": warning_text,
                "url": BOM_WARNINGS_URL,
                "color": 0xFF6600,
                "footer": {"text": "Source: Bureau of Meteorology – Queensland"},
            }
        ],
    }

    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    r.raise_for_status()


def main():
    current_warnings = fetch_bom_warnings()
    sent = load_sent()

    # First run: if we’ve never seen anything before, just record it
    if not sent and current_warnings:
        save_sent(set(current_warnings))
        print("Initialised with current BOM warnings.")
        return

    new_ones = [w for w in current_warnings if w not in sent]

    if not new_ones:
        print("No new warnings.")
        return

    for w in new_ones:
        print("Sending warning:", w)
        send_discord(w)
        sent.add(w)

    save_sent(sent)
    print("Done.")


if __name__ == "__main__":
    main()
