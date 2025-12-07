#!/usr/bin/env python3
import json
import os

import requests
from bs4 import BeautifulSoup

BOM_RSS_URL = "https://reg.bom.gov.au/fwo/IDZ00056.warnings_qld.xml"
STATE_FILE = "sent_warnings.json"

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")

GC_BNE_KEYWORDS = [
    "southeast queensland",
    "south east queensland",
    "south-east queensland",
    "southeast coast",
    "southeast coast district",
    "gold coast",
    "city of gold coast",
    "brisbane",
    "brisbane city",
    "scenic rim",
    "queensland east coast",
    "wide bay"
]


def send_to_discord(text: str) -> None:
    if not WEBHOOK:
        print("[WARN] DISCORD_WEBHOOK_URL not set. Would have sent:")
        print(text)
        return
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


def fetch_bom_items() -> list[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; GitHubActions-BOM-to-Discord/1.0; "
            "+https://github.com/benbrownie200-tech/Weather-Bot)"
        )
    }
    resp = requests.get(BOM_RSS_URL, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "xml")

    items: list[dict] = []
    for item in soup.find_all("item"):
        title_tag = item.find("title")
        if title_tag is not None:
            title = title_tag.get_text(strip=True)
        else:
            t = getattr(item, "title", "")
            title = t.strip() if isinstance(t, str) else "BOM warning"

        desc_tag = item.find("description")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        link = "https://www.bom.gov.au/weather-and-climate/warnings-and-alerts?stateName=Queensland"

        guid_tag = item.find("guid")
        guid = guid_tag.get_text(strip=True) if guid_tag else ""
        if not guid:
            guid = link or title

        items.append(
            {
                "id": guid,
                "title": title,
                "description": description,
                "link": link,
            }
        )
    return items


def is_gold_coast_or_brisbane(item: dict) -> bool:
    text = (item["title"] + " " + item["description"]).lower()
    return any(k in text for k in GC_BNE_KEYWORDS)


def format_item(item: dict) -> str:
    title = item["title"] or "BOM warning"
    link = item.get("link") or ""
    if link:
        return f"⚠️ **{title}**\n{link}"
    desc = item.get("description") or ""
    return f"⚠️ **{title}**\n{desc[:1800]}"


def main() -> None:
    try:
        all_items = fetch_bom_items()
    except Exception as e:
        msg = f"❌ Couldn't fetch BOM QLD warnings from {BOM_RSS_URL}: {e}"
        print(msg)
        send_to_discord(msg)
        raise

    # filter GC/BNE only
    items = [it for it in all_items if is_gold_coast_or_brisbane(it)]
    sent_ids = load_sent_ids(STATE_FILE)

    # Global flag logic – if BOM has warnings but our region filter got nothing
    if all_items and not items:
        text = (
            "⚠️ No GC/BNE warnings detected (but BOM shows other warnings). "
            "This may be a BOM feed problem or missing region text – global flag triggered."
        )
        print(text)
        send_to_discord(text)
        return

    # no GC/BNE warnings
    if not items:
        current_ids = set()
        if current_ids != sent_ids:
            send_to_discord(
                "ℹ️ Warnings cleared – no current Gold Coast / Brisbane BOM warnings."
            )
            save_sent_ids(STATE_FILE, current_ids)
        else:
            print("No GC/BNE warnings, no change.")
        return

    current_ids = {i["id"] for i in items}

    if current_ids == sent_ids:
        print("No change in GC/BNE warnings. Not posting.")
        return

    new_ids = current_ids - sent_ids
    print("Change detected in GC/BNE warnings → posting full GC/BNE list.")

    if new_ids:
        send_to_discord(f"🚨 **New Gold Coast / Brisbane BOM warnings detected ({len(new_ids)})!**")
    else:
        send_to_discord("⚠️ **GC/BNE warnings updated — reposting current list.**")

    for item in items:
        wid = item["id"]
        msg = format_item(item)
        if wid in new_ids:
            msg = f"🆕 **NEW** {msg}"
        send_to_discord(msg)

    save_sent_ids(STATE_FILE, current_ids)
    print(f"Posted {len(items)} GC/BNE warning(s).")


if __name__ == "__main__":
    main()
