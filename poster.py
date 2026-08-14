import feedparser
import requests
import os
import json
import sys
import re
import hashlib
from html import unescape
from datetime import datetime, timezone

BLOGGER_RSS = os.environ.get("BLOGGER_RSS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
STATE_FILE = os.environ.get("STATE_FILE", "posted_items.json")
MAX_STATE_ITEMS = int(os.environ.get("MAX_STATE_ITEMS", "5000"))
MAX_ITEMS_PER_RUN = int(os.environ.get("MAX_ITEMS_PER_RUN", "50"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))
DONATE_URL = "https://www.patreon.com/Alvinalexa?utm_campaign=creatorshare_creator"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"version": 2, "posted": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "posted" in data and isinstance(data["posted"], dict):
            return data
        # Migrate the old single-cursor state without treating it as a complete history.
        old_id = data.get("last_id")
        return {"version": 2, "posted": {old_id: {"migrated": True}} if old_id else {}}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ Could not read state file; starting safely with an empty index: {exc}")
        return {"version": 2, "posted": {}}


def save_state(state):
    state["version"] = 2
    posted = state.get("posted", {})
    # Keep the newest entries by recorded publication time so state stays small.
    ordered = sorted(posted.items(), key=lambda item: item[1].get("posted_at", ""))[-MAX_STATE_ITEMS:]
    state["posted"] = dict(ordered)
    temporary = f"{STATE_FILE}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, STATE_FILE)


def strip_html(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def clean_description(raw_html, max_length=150):
    plain = strip_html(raw_html)
    if len(plain) > max_length:
        plain = plain[:max_length].rsplit(" ", 1)[0] + "…"
    return plain


def value(entry, name, default=""):
    return getattr(entry, name, default) or default


def item_key(entry):
    """Return a stable identity across feed refreshes and minor metadata changes."""
    for candidate in (value(entry, "id"), value(entry, "guid"), value(entry, "link")):
        if candidate:
            return candidate.strip()
    basis = "|".join((value(entry, "title"), value(entry, "published"), value(entry, "updated"), value(entry, "summary")))
    return "sha256:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()


def entry_timestamp(entry):
    parsed = value(entry, "published_parsed") or value(entry, "updated_parsed")
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError):
            pass
    return 0


def get_new_posts(state):
    if not BLOGGER_RSS:
        raise RuntimeError("Missing BLOGGER_RSS environment variable")
    feed = feedparser.parse(BLOGGER_RSS)
    if feed.bozo:
        print(f"⚠️ RSS parse warning: {feed.bozo_exception}")
    posted = state.setdefault("posted", {})
    candidates = [entry for entry in feed.entries if item_key(entry) not in posted]
    # Oldest first; entries with no parsed date retain feed order after dated entries.
    candidates.sort(key=entry_timestamp)
    return candidates[:MAX_ITEMS_PER_RUN]


def post_to_telegram(title, url, description=""):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    clean_desc = clean_description(description, max_length=150)
    text = f"*{title}*\n\n{clean_desc}\n\n🔗 {url}" if clean_desc else f"*{title}*\n\n🔗 {url}"
    reply_markup = {"inline_keyboard": [[{"text": "📺 Watch", "url": url}], [{"text": "❤️ Donate", "url": DONATE_URL}]]}
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown", "reply_markup": json.dumps(reply_markup)},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Telegram HTTP {response.status_code}: {response.text[:300]}")
    print(f"✅ Telegram: {title}")


def main():
    print(f"🔍 Checking RSS: {BLOGGER_RSS}")
    state = load_state()
    posts = get_new_posts(state)
    if not posts:
        print("📭 No new feed items.")
        return
    print(f"📨 Found {len(posts)} new feed item(s)")
    posted_count = 0
    for entry in posts:
        key = item_key(entry)
        title = value(entry, "title", "Untitled post")
        url = value(entry, "link")
        if not url:
            print(f"⚠️ Skipping {title}: feed item has no link")
            continue
        print(f"\n📄 Processing: {title}")
        try:
            post_to_telegram(title, url, value(entry, "summary"))
        except Exception as exc:
            # Do not mark failures as posted; the next run can retry them.
            print(f"❌ Publish failed for {title}: {exc}")
            continue
        state["posted"][key] = {"title": title, "url": url, "posted_at": datetime.now(timezone.utc).isoformat()}
        save_state(state)
        posted_count += 1
    print(f"✅ Done: {posted_count} item(s) published; failed items remain eligible for retry.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ Fatal error: {exc}")
        sys.exit(1)
