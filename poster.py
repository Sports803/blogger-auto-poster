import feedparser
import requests
import os
import json
import sys
import re
import time                                                       # NEW
import hashlib
from html import unescape, escape                                 # CHANGED (added escape)

BLOGGER_RSS = os.environ.get("BLOGGER_RSS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
STATE_FILE = os.environ.get("STATE_FILE", "posted_items.json")
MAX_STATE_ITEMS = int(os.environ.get("MAX_STATE_ITEMS", "5000"))
MAX_ITEMS_PER_RUN = int(os.environ.get("MAX_ITEMS_PER_RUN", "50"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))
DONATE_URL = "https://www.patreon.com/Alvinalexa?utm_campaign=creatorshare_creator"

# NEW: behavioural knobs
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")
INTER_POST_DELAY = float(os.environ.get("INTER_POST_DELAY_SECONDS", "1.2"))
TELEGRAM_MAX_ATTEMPTS = int(os.environ.get("TELEGRAM_MAX_ATTEMPTS", "5"))
DESCRIPTION_MAX_LENGTH = int(os.environ.get("DESCRIPTION_MAX_LENGTH", "150"))


# --------------------------------------------------------------------------- state
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"version": 2, "posted": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "posted" in data and isinstance(data["posted"], dict):
            return data
        old_id = data.get("last_id")
        return {"version": 2, "posted": {old_id: {"migrated": True}} if old_id else {}}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ Could not read state file; starting safely with an empty index: {exc}")
        return {"version": 2, "posted": {}}


def save_state(state):
    state["version"] = 2
    posted = state.get("posted", {})
    ordered = sorted(posted.items(), key=lambda item: item[1].get("posted_at", ""))[-MAX_STATE_ITEMS:]
    state["posted"] = dict(ordered)
    temporary = f"{STATE_FILE}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, STATE_FILE)


# --------------------------------------------------------------------------- text helpers
def strip_html(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def clean_description(raw_html, max_length=DESCRIPTION_MAX_LENGTH):
    plain = strip_html(raw_html)
    if len(plain) > max_length:
        plain = plain[:max_length].rsplit(" ", 1)[0] + "…"
    return plain


def escape_html(text):                                            # NEW
    """Escape text for Telegram's HTML parse mode (bold, links, etc.)."""
    return escape(text or "", quote=False)


# --------------------------------------------------------------------------- feed helpers
def value(entry, name, default=""):
    return getattr(entry, name, default) or default


def item_key(entry):
    """Return a stable identity across feed refreshes and minor metadata changes."""
    for candidate in (value(entry, "id"), value(entry, "guid"), value(entry, "link")):
        if candidate:
            return candidate.strip()
    basis = "|".join(
        (value(entry, "title"), value(entry, "published"), value(entry, "updated"), value(entry, "summary"))
    )
    return "sha256:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()


def entry_timestamp(entry):
    parsed = value(entry, "published_parsed") or value(entry, "updated_parsed")
    if parsed:
        try:
            from datetime import datetime, timezone  # local import keeps top clean
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

    # FIX: undated entries used to sort *first* (ts=0). Now they sink to the end
    # while preserving feed order (stable sort).
    candidates.sort(key=lambda e: (entry_timestamp(e) == 0, entry_timestamp(e)))
    return candidates[:MAX_ITEMS_PER_RUN]


# --------------------------------------------------------------------------- telegram
def telegram_send(payload, max_attempts=TELEGRAM_MAX_ATTEMPTS):   # NEW
    """POST to sendMessage with retry/backoff for 429s, 5xx, and network errors."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc
            wait = min(2 ** attempt, 30)
            print(f"⚠️ Telegram network error ({exc}); retry {attempt}/{max_attempts} in {wait}s")
            time.sleep(wait)
            continue

        if response.status_code == 200:
            return response

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "5") or "5")
            last_error = RuntimeError(f"429: {response.text[:200]}")
            if attempt == max_attempts:
                break
            print(f"⚠️ Telegram rate limit; sleeping {retry_after}s (attempt {attempt})")
            time.sleep(retry_after)
            continue

        if 500 <= response.status_code < 600:
            last_error = RuntimeError(f"{response.status_code}: {response.text[:200]}")
            if attempt == max_attempts:
                break
            wait = min(2 ** attempt, 30)
            print(f"⚠️ Telegram {response.status_code}; retry {attempt}/{max_attempts} in {wait}s")
            time.sleep(wait)
            continue

        # 4xx (other than 429) is not retryable — bail immediately.
        raise RuntimeError(f"Telegram HTTP {response.status_code}: {response.text[:300]}")

    raise RuntimeError(f"Telegram send failed after {max_attempts} attempts: {last_error}")


def post_to_telegram(title, url, description=""):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    clean_desc = clean_description(description)
    safe_title = escape_html(title)
    safe_desc = escape_html(clean_desc)
    safe_url = escape_html(url, quote=True)

    # CHANGED: HTML parse mode instead of legacy Markdown. Legacy Markdown breaks
    # on titles containing _, *, `, [ — HTML with escaping does not.
    if safe_desc:
        text = f"<b>{safe_title}</b>\n\n{safe_desc}\n\n🔗 <a href=\"{safe_url}\">{safe_url}</a>"
    else:
        text = f"<b>{safe_title}</b>\n\n🔗 <a href=\"{safe_url}\">{safe_url}</a>"

    reply_markup = {
        "inline_keyboard": [
            [{"text": "📺 Watch", "url": url}],
            [{"text": "❤️ Donate", "url": DONATE_URL}],
        ]
    }

    if DRY_RUN:
        print(f"🧪 DRY RUN — would post: {title}  ({url})")
        print(f"   text: {text[:200]}{'…' if len(text) > 200 else ''}")
        return

    telegram_send({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
        "reply_markup": json.dumps(reply_markup),
    })
    print(f"✅ Telegram: {title}")


# --------------------------------------------------------------------------- main
def main():
    if not BLOGGER_RSS:
        raise RuntimeError("Missing BLOGGER_RSS environment variable")

    if DRY_RUN:
        print("🧪 DRY RUN mode: nothing will be sent and state will not be modified.")

    print(f"🔍 Checking RSS: {BLOGGER_RSS}")
    state = load_state()
    posts = get_new_posts(state)

    if not posts:
        print("📭 No new feed items.")
        # NEW: always write state so the workflow's git step has a file to commit.
        save_state(state)
        return

    print(f"📨 Found {len(posts)} new feed item(s)")
    posted_count = 0
    failed_count = 0

    for index, entry in enumerate(posts):
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
            failed_count += 1
            print(f"❌ Publish failed for {title}: {exc}")
            continue

        if not DRY_RUN:                                            # NEW
            from datetime import datetime, timezone
            state["posted"][key] = {
                "title": title,
                "url": url,
                "posted_at": datetime.now(timezone.utc).isoformat(),
            }
            save_state(state)                                      # crash-safe per item

        posted_count += 1

        # NEW: throttle between sends to stay under Telegram's per-chat limit.
        if index < len(posts) - 1:
            time.sleep(INTER_POST_DELAY)

    if not DRY_RUN:
        save_state(state)

    print(f"✅ Done: {posted_count} item(s) published; {failed_count} failed. "
          f"Failed items remain eligible for retry.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ Fatal error: {exc}")
        sys.exit(1)