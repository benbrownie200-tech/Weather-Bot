#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# BOM QLD warnings RSS (real one)
BOM_RSS_URL = "https://reg.bom.gov.au/fwo/IDZ00056.warnings_qld.xml"
STATE_FILE = "sent_warnings.json"

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")


def load_sent_ids(path: str) -> set:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                return set(data.get("sent_ids", []))
            except json.JSONDecodeError:
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
    resp = requests.get("https://reg.bom.gov.au/fwo/IDZ00056.warnings_qld.xml", headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "xml")

    items: list[dict] = []
    for item in soup.find_all("item"):
        # title
        title_tag = item.find("title")
        if title_tag is not None:
            title = title_tag.get_text(strip=True)
        else:
            # sometimes BS gives you item.title == "some string"
            t = getattr(item, "title", "")
            title = t.strip() if isinstance(t, str) else "BOM warning"

        # description
        desc_tag = item.find("description")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # link
        link_tag = item.find("link")
        link = link_tag.get_text(strip=True) if link_tag else ""

        # guid / id
        guid_tag = item.find("guid")
        guid = guid_tag.get_text(strip=True) if guid_tag else ""
        if not guid:
            guid = link or title

        # pubDate (optional)
        pubdate_tag = item.find("pubDate")
        pubdate = pubdate_tag.get_text(strip=True) if pubdate_tag else ""

        items.append(
            {
                "id": guid,
                "title": title,
                "description": description,
                "link": link,
                "pubDate": pubdate,
            }
        )

    return items



def send_to_discord(text: str) -> None:
    if not WEBHOOK:
        print("[WARN] DISCORD_WEBHOOK_URL not set. Would have sent:")
        print(text)
        return

    r = requests.post(WEBHOOK, json={"content": text}, timeout=20)
    if r.status_code >= 400:
        raise SystemExit(
            f"Discord webhook failed: {r.status_code} {r.text[:200]}"
        )


def format_item(item: dict) -> str:
    # produce a nice one-liner
    title = item["title"] or "BOM warning"
    link = item["link"]
    if link:
        return f"⚠️ \n **{title}**\n{link}"
    else:
        desc = item["description"] or ""
        return f"⚠️ \n **{title}**{desc[:1800]}\n"  # discord 2k char limit


def main() -> None:
    try:
        items = fetch_bom_items()
    except Exception as e:
        # tell discord we failed so you see it straight away
        msg = f"❌ Couldn't fetch BOM QLD warnings from {BOM_RSS_URL}: {e}"
        print(msg)
        send_to_discord(msg)
        raise

    sent_ids = load_sent_ids(STATE_FILE)

    if not items:
        # RSS really is empty → announce once
        if "NO_WARNINGS" not in sent_ids:
            send_to_discord("ℹ️ There are no current weather warnings for Queensland \n New warnings will be messaged within 10 minutes of appearing on the BOM")
            sent_ids.add("NO_WARNINGS")
            save_sent_ids(STATE_FILE, sent_ids)
        else:
            print("No warnings, already told Discord.")
        return

# we have items
    current_ids = {i["id"] for i in items}

    # 🔴 this is the new part:
    # if the CURRENT set of warnings is exactly what we posted last time → do nothing
    if current_ids == sent_ids:
        print("No change in warnings. Not posting.")
        return

    # otherwise, something changed (added / removed / updated) → post ALL current warnings
print("Change detected in warnings → posting full list.")

# Figure out which warnings are new
new_ids = current_ids - sent_ids
if new_ids:
    send_to_discord(f"🚨 **New QLD BOM warnings detected ({len(new_ids)})!**")
else:
    send_to_discord("⚠️ **Warnings have changed or cleared — reposting current list.**")

# Send all current warnings, highlighting new ones
for item in items:
    warn_id = item["id"]
    msg = format_item(item)
    if warn_id in new_ids:
        msg = f"🆕 **NEW** {msg}"
    send_to_discord(msg)


    # and now remember THIS exact set
    save_sent_ids(STATE_FILE, current_ids)
    print(f"Posted {len(items)} warning(s).")


if __name__ == "__main__":
    main()
