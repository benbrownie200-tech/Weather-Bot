#!/usr/bin/env python3
import json
import os
import sys
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

# ---- MAIN BOM SOURCE (machine-friendly mirror) ----
BOM_RSS_PRIMARY = "https://reg.bom.gov.au/fwo/IDZ00056.warnings_qld.xml"
# Fallback 1: original (might 403 from GitHub)
BOM_RSS_FALLBACK = "http://www.bom.gov.au/fwo/IDZ00056.warnings_qld.xml"
# Fallback 2: QLD CAP feed (not always 1:1 with BOM site, but reachable)
QLD_CAP_FALLBACK = (
    "https://publiccontent-gis-psba-qld-gov-au.s3.ap-southeast-2.amazonaws.com/"
    "content/Feeds/StormFloodCycloneWarnings/StormWarnings_capau.xml"
)

STATE_FILE = "sent_warnings.json"
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")


def send_to_discord_content(content: str) -> None:
    """Simple content message."""
    if not WEBHOOK:
        print("[WARN] webhook not set, would send:")
        print(content)
        return
    r = requests.post(WEBHOOK, json={"content": content}, timeout=20)
    r.raise_for_status()


def send_to_discord_warning(title: str, link: str = "", desc: str = "") -> None:
    """Nicer warning message with bold title."""
    if not WEBHOOK:
        print("[WARN] webhook not set, would send warning:", title)
        return
    text = f"⚠️ **{title}**"
    if link:
        text += f"\n{link}"
    elif desc:
        text += f"\n{desc[:1800]}"
    r = requests.post(WEBHOOK, json={"content": text}, timeout=20)
    r.raise_for_status()


def load_sent_ids(path: str) -> set:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("sent_ids", []))
        except Exception:
            return set()
    return set()


def save_sent_ids(path: str, ids: set) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"sent_ids": sorted(ids)}, f, indent=2)


def fetch_bom_rss(url: str) -> str:
    # Spoof UA so even the fallback has a chance
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; GitHubActions-BOM-to-Discord/1.0; "
            "+https://github.com/benbrownie200-tech/Weather-Bot)"
        )
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_bom_rss(xml_text: str) -> List[Dict]:
    soup = BeautifulSoup(xml_text, "xml")
    items = []
    for item in soup.find_all("item"):
        title = (item.title or "").text.strip()
        description = (item.description or "").text.strip()
        link = (item.link or "").text.strip()
        guid_tag = item.find("guid")
        guid = (guid_tag.text.strip() if guid_tag else "") or link or title
        items.append(
            {
                "id": guid,
                "title": title or "BOM warning",
                "description": description,
                "link": link,
            }
        )
    return items


def fetch_cap_fallback() -> List[Dict]:
    """Fallback to QLD CAP feed (not perfect but reachable)."""
    resp = requests.get(QLD_CAP_FALLBACK, timeout=20)
    resp.raise_for_status()
    from xml.etree import ElementTree as ET

    root = ET.fromstring(resp.content)
    alerts = []
    for alert in root.findall(".//{*}alert"):
        identifier_el = alert.find("./{*}identifier")
        headline_el = alert.find(".//{*}headline")
        desc_el = alert.find(".//{*}description")
        web_el = alert.find(".//{*}web")

        identifier = identifier_el.text.strip() if identifier_el is not None and identifier_el.text else None
        headline = headline_el.text.strip() if headline_el is not None and headline_el.text else "Weather Warning"
        desc = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
        link = web_el.text.strip() if web_el is not None and web_el.text else QLD_CAP_FALLBACK

        alerts.append(
            {
                "id": identifier or headline,
                "title": headline,
                "description": desc,
                "link": link,
            }
        )
    return alerts


def main() -> None:
    sent_ids = load_sent_ids(STATE_FILE)
    warnings_list: List[Dict] = []

    # 1) try reg.bom.gov.au first
    err_primary = None
    try:
        xml_text = fetch_bom_rss(BOM_RSS_PRIMARY)
        warnings_list = parse_bom_rss(xml_text)
        print(f"Fetched {len(warnings_list)} warnings from primary BOM (reg).")
    except Exception as e:
        err_primary = e
        print(f"[WARN] primary BOM (reg) failed: {e}")

    # 2) if primary failed, try www (may 403)
    if not warnings_list:
        try:
            xml_text = fetch_bom_rss(BOM_RSS_FALLBACK)
            warnings_list = parse_bom_rss(xml_text)
            print(f"Fetched {len(warnings_list)} warnings from fallback www.bom.gov.au.")
        except Exception as e:
            print(f"[WARN] www.bom.gov.au fallback failed: {e}")

    # 3) if still nothing, hit QLD CAP feed
    if not warnings_list:
        try:
            warnings_list = fetch_cap_fallback()
            print(f"Fetched {len(warnings_list)} warnings from QLD CAP fallback.")
        except Exception as e:
            # everything failed: tell Discord and stop
            msg = (
                f"❌ Couldn't fetch ANY QLD warnings.\n"
                f"Primary error: {err_primary}\n"
                f"CAP also failed: {e}"
            )
            send_to_discord_content(msg)
            raise

    # ---- now we have *some* warnings ----
    if not warnings_list:
        # feed genuinely empty
        if "NO_WARNINGS" not in sent_ids:
            send_to_discord_content("ℹ️ No current QLD BOM warnings.")
            sent_ids.add("NO_WARNINGS")
            save_sent_ids(STATE_FILE, sent_ids)
        else:
            print("No warnings, already announced.")
        return

    # we do have warnings → remove placeholder
    if "NO_WARNINGS" in sent_ids:
        sent_ids.remove("NO_WARNINGS")

    new_count = 0
    for w in warnings_list:
        wid = w["id"]
        if wid in sent_ids:
            continue

        send_to_discord_warning(w["title"], link=w["link"], desc=w["description"])
        sent_ids.add(wid)
        new_count += 1

    save_sent_ids(STATE_FILE, sent_ids)
    print(f"Posted {new_count} new warning(s).")


if __name__ == "__main__":
    main()
