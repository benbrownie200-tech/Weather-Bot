#!/usr/bin/env python3
import json
import os

import requests
from bs4 import BeautifulSoup

# You were using reg.bom.gov.au in the last run
BOM_RSS_URL = "https://reg.bom.gov.au/fwo/IDZ00056.warnings_qld.xml"
STATE_FILE = "sent_warnings.json"

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")


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
        # title
        title_tag = item.find("title")
        if title_tag is not None:
            title = title_tag.get_text(strip=True)
        else:
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

        items.append(
            {
                "id": guid,
                "title": title,
                "description": description,
                "link": link,
            }
        )
    return items


def format_item(item: dict) -> str:
    title = item["title"] or "BOM warning"
    link = item.get("link") or ""
    if link:
        return f"⚠️ **{title}**\n{link}"
    desc = item.get("description") or ""
    return f"⚠️ **{title}**\n{desc[:1800]}"


def main() -> None:
    try:
        items = fetch_bom_items()
    except Exception as e:
        msg = f"❌ Couldn't fetch BOM QLD warnings from {BOM_RSS_URL}: {e}"
        print(msg)
        send_to_discord(msg)
        raise

    sent_ids = load_sent_ids(STATE_FILE)

    # if feed is actually empty
    if not items:
        current_ids = set()
        if current_ids != sent_ids:
            send_to_discord("ℹ️ Warnings cleared - No current warnings in QLD.")
            save_sent_ids(STATE_FILE, current_ids)
        else:
            print("No warnings, no change.")
        return

    # build the CURRENT set of IDs first
    current_ids = {i["id"] for i in items}

    # if nothing changed, bail
    if current_ids == sent_ids:
        print("No change in warnings. Not posting.")
        return

    # something changed → figure out which ones are NEW compared to last run
    new_ids = current_ids - sent_ids
    print("Change detected in warnings → posting full list.")

    if new_ids:
        send_to_discord(f"🚨 **New QLD BOM warnings detected ({len(new_ids)})!**")
    else:
        # e.g. one warning disappeared, or same IDs but wording changed
        send_to_discord("⚠️ **Warnings updated — reposting current list.**")

    # post ALL current warnings, but highlight the new ones
    for item in items:
        wid = item["id"]
        msg = format_item(item)
        if wid in new_ids:
            msg = f"🆕 **NEW** {msg}"
        send_to_discord(msg)

    # finally, remember this exact set so we don't repost it next run
    save_sent_ids(STATE_FILE, current_ids)
    print(f"Posted {len(items)} warning(s).")


if __name__ == "__main__":
    main()
