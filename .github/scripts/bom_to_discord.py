#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

# BOM QLD warnings RSS (real one)
BOM_RSS_URL = "https://api.allorigins.win/raw?url=http://www.bom.gov.au/fwo/IDZ00056.warnings_qld.xml"
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
    # BOM sometimes 403s scripts with a blank UA, so fake a browser UA
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; GitHubActions-BOM-to-Discord/1.0; "
            "+https://github.com/benbrownie200-tech/Weather-Bot)"
        )
    }
    resp = requests.get(BOM_RSS_URL, headers=headers, timeout=20)
    # if this errors, we want the workflow to fail loudly
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "xml")

    items = []
    for item in soup.find_all("item"):
        title = (item.title or "").text.strip()
        description = (item.description or "").text.strip()
        link = (item.link or "").text.strip()
        guid_tag = item.find("guid")
        guid = (guid_tag.text.strip() if guid_tag else "") or link or title

        pubdate = (item.pubDate or "").text.strip()
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
        return f"⚠️ **{title}**\n{link}"
    else:
        desc = item["description"] or ""
        return f"⚠️ **{title}**\n{desc[:1800]}"  # discord 2k char limit


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
            send_to_discord("ℹ️ No current QLD BOM warnings.")
            sent_ids.add("NO_WARNINGS")
            save_sent_ids(STATE_FILE, sent_ids)
        else:
            print("No warnings, already told Discord.")
        return

    # we have real warnings → clear the placeholder id
    if "NO_WARNINGS" in sent_ids:
        sent_ids.remove("NO_WARNINGS")

    new_count = 0
    for item in items:
        warn_id = item["id"]
        if warn_id in sent_ids:
            continue
        # new warning!
        send_to_discord(format_item(item))
        sent_ids.add(warn_id)
        new_count += 1

    save_sent_ids(STATE_FILE, sent_ids)
    print(f"Done. Found {len(items)} warning(s), posted {new_count} new one(s).")


if __name__ == "__main__":
    main()
