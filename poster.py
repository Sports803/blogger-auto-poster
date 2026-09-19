import feedparser
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import escape, unescape

import requests

BLOGGER_RSS = os.environ.get("BLOGGER_RSS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
BUFFER_API_KEY = os.environ.get("BUFFER_API_KEY")
BUFFER_CHANNEL_IDS = [x.strip() for x in os.environ.get("BUFFER_CHANNEL_IDS", "").split(",") if x.strip()]
BUFFER_API_URL = os.environ.get("BUFFER_API_URL", "https://api.buffer.com")
BUFFER_MODE = os.environ.get("BUFFER_MODE", "addToQueue").strip()
BUFFER_DUE_AT = os.environ.get("BUFFER_DUE_AT", "").strip()
STATE_FILE = os.environ.get("STATE_FILE", "posted_items.json")
MAX_STATE_ITEMS = int(os.environ.get("MAX_STATE_ITEMS", "5000"))
MAX_ITEMS_PER_RUN = int(os.environ.get("MAX_ITEMS_PER_RUN", "50"))
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))
INTER_POST_DELAY = float(os.environ.get("INTER_POST_DELAY_SECONDS", "1.2"))
TELEGRAM_MAX_ATTEMPTS = int(os.environ.get("TELEGRAM_MAX_ATTEMPTS", "5"))
BUFFER_MAX_ATTEMPTS = int(os.environ.get("BUFFER_MAX_ATTEMPTS", "5"))
DESCRIPTION_MAX_LENGTH = int(os.environ.get("DESCRIPTION_MAX_LENGTH", "150"))
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}
DONATE_URL = "https://www.patreon.com/Alvinalexa?utm_campaign=creatorshare_creator"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"version": 2, "posted": {}}
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data.get("posted"), dict):
            return data
        old_id = data.get("last_id")
        return {"version": 2, "posted": {old_id: {"migrated": True}} if old_id else {}}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"⚠️ Could not read state file; starting safely with an empty index: {exc}")
        return {"version": 2, "posted": {}}


def save_state(state):
    state["version"] = 2
    posted = state.setdefault("posted", {})
    ordered = sorted(posted.items(), key=lambda item: item[1].get("posted_at", ""))[-MAX_STATE_ITEMS:]
    state["posted"] = dict(ordered)
    temporary = f"{STATE_FILE}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, STATE_FILE)


def strip_html(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def clean_description(raw_html, max_length=DESCRIPTION_MAX_LENGTH):
    plain = strip_html(raw_html)
    if len(plain) > max_length:
        plain = plain[:max_length].rsplit(" ", 1)[0] + "…"
    return plain


def value(entry, name, default=""):
    return getattr(entry, name, default) or default


def item_key(entry):
    for candidate in (value(entry, "id"), value(entry, "guid"), value(entry, "link")):
        if candidate:
            return candidate.strip()
    basis = "|".join((value(entry, "title"), value(entry, "published"), value(entry, "updated"), value(entry, "summary")))
    return "sha256:" + hashlib.sha256(basis.encode()).hexdigest()


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
    candidates.sort(key=lambda entry: (entry_timestamp(entry) == 0, entry_timestamp(entry)))
    return candidates[:MAX_ITEMS_PER_RUN]


def telegram_send(payload):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    last_error = None
    for attempt in range(1, TELEGRAM_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc
            if attempt == TELEGRAM_MAX_ATTEMPTS:
                break
            time.sleep(min(2**attempt, 30))
            continue
        if response.status_code == 200:
            return
        if response.status_code == 429:
            last_error = RuntimeError(f"429: {response.text[:200]}")
            if attempt == TELEGRAM_MAX_ATTEMPTS:
                break
            time.sleep(int(response.headers.get("Retry-After", "5") or "5"))
            continue
        if 500 <= response.status_code < 600:
            last_error = RuntimeError(f"{response.status_code}: {response.text[:200]}")
            if attempt == TELEGRAM_MAX_ATTEMPTS:
                break
            time.sleep(min(2**attempt, 30))
            continue
        raise RuntimeError(f"Telegram HTTP {response.status_code}: {response.text[:300]}")
    raise RuntimeError(f"Telegram send failed after {TELEGRAM_MAX_ATTEMPTS} attempts: {last_error}")


def post_to_telegram(title, url, description):
    safe_title = escape(title or "Untitled post")
    safe_description = escape(clean_description(description))
    safe_url = escape(url, quote=True)
    body = f"<b>{safe_title}</b>"
    if safe_description:
        body += f"\n\n{safe_description}"
    body += f"\n\n🔗 <a href=\"{safe_url}\">{safe_url}</a>"
    if DRY_RUN:
        print(f"🧪 DRY RUN — would post to Telegram: {title} ({url})")
        return
    telegram_send({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": body,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
        "reply_markup": json.dumps({"inline_keyboard": [[{"text": "📺 Watch", "url": url}], [{"text": "❤️ Donate", "url": DONATE_URL}]]}),
    })
    print(f"✅ Telegram: {title}")


def buffer_text(title, url, description):
    parts = [title.strip() or "Untitled post"]
    clean = clean_description(description)
    if clean:
        parts.append(clean)
    parts.append(url.strip())
    return "\n\n".join(parts)


def buffer_create_post(text, channel_id):
    if not BUFFER_API_KEY:
        raise RuntimeError("Missing BUFFER_API_KEY environment variable")
    if BUFFER_MODE not in {"addToQueue", "shareNow", "shareNext", "customScheduled"}:
        raise RuntimeError("BUFFER_MODE must be addToQueue, shareNow, shareNext, or customScheduled")
    if BUFFER_MODE == "customScheduled" and not BUFFER_DUE_AT:
        raise RuntimeError("BUFFER_DUE_AT is required when BUFFER_MODE=customScheduled")

    fields = [f"text: {json.dumps(text)}", f"channelId: {json.dumps(channel_id)}", "schedulingType: automatic", f"mode: {BUFFER_MODE}"]
    if BUFFER_MODE == "customScheduled":
        fields.append(f"dueAt: {json.dumps(BUFFER_DUE_AT)}")
    query = f"""mutation CreatePost {{
  createPost(input: {{{', '.join(fields)}}}) {{
    ... on PostActionSuccess {{ post {{ id text dueAt }} }}
    ... on MutationError {{ message }}
  }}
}}"""

    last_error = None
    for attempt in range(1, BUFFER_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(BUFFER_API_URL, headers={"Authorization": f"Bearer {BUFFER_API_KEY}", "Content-Type": "application/json"}, json={"query": query}, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc
            if attempt == BUFFER_MAX_ATTEMPTS:
                break
            time.sleep(min(2**attempt, 30))
            continue
        if response.status_code == 429 or 500 <= response.status_code < 600:
            last_error = RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            if attempt == BUFFER_MAX_ATTEMPTS:
                break
            retry_after = int(response.headers.get("Retry-After", "0") or "0")
            time.sleep(retry_after or min(2**attempt, 30))
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Buffer HTTP {response.status_code}: {response.text[:500]}")
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(f"Buffer GraphQL error: {payload['errors']}")
        result = payload.get("data", {}).get("createPost", {})
        if result.get("message"):
            raise RuntimeError(f"Buffer rejected post: {result['message']}")
        post = result.get("post")
        if not post or not post.get("id"):
            raise RuntimeError(f"Unexpected Buffer response: {payload}")
        return post
    raise RuntimeError(f"Buffer post failed after {BUFFER_MAX_ATTEMPTS} attempts: {last_error}")


def post_to_buffer(title, url, description):
    text = buffer_text(title, url, description)
    if DRY_RUN:
        for channel_id in BUFFER_CHANNEL_IDS:
            print(f"🧪 DRY RUN — would queue Buffer post for {channel_id}: {title} ({url})")
        return
    for channel_id in BUFFER_CHANNEL_IDS:
        post = buffer_create_post(text, channel_id)
        print(f"✅ Buffer ({channel_id}): {title} queued for {post.get('dueAt', 'next available slot')}")


def main():
    if not BLOGGER_RSS:
        raise RuntimeError("Missing BLOGGER_RSS environment variable")
    has_telegram = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    has_buffer = bool(BUFFER_API_KEY and BUFFER_CHANNEL_IDS)
    if not has_telegram and not has_buffer:
        raise RuntimeError("Configure Telegram or Buffer credentials and destination settings")
    if DRY_RUN:
        print("🧪 DRY RUN mode: nothing will be sent and state will not be modified.")

    state = load_state()
    posts = get_new_posts(state)
    if not posts:
        print("📭 No new feed items.")
        save_state(state)
        return
    print(f"📨 Found {len(posts)} new feed item(s)")
    posted_count = failed_count = 0
    for index, entry in enumerate(posts):
        key, title, url, description = item_key(entry), value(entry, "title", "Untitled post"), value(entry, "link"), value(entry, "summary")
        if not url:
            print(f"⚠️ Skipping {title}: feed item has no link")
            continue
        print(f"\n📄 Processing: {title}")
        try:
            if has_telegram:
                post_to_telegram(title, url, description)
            if has_buffer:
                post_to_buffer(title, url, description)
        except Exception as exc:
            failed_count += 1
            print(f"❌ Publish failed for {title}: {exc}")
            continue
        if not DRY_RUN:
            state["posted"][key] = {"title": title, "url": url, "posted_at": datetime.now(timezone.utc).isoformat()}
            save_state(state)
        posted_count += 1
        if index < len(posts) - 1:
            time.sleep(INTER_POST_DELAY)
    if not DRY_RUN:
        save_state(state)
    print(f"✅ Done: {posted_count} item(s) published; {failed_count} failed. Failed items remain eligible for retry.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ Fatal error: {exc}")
        sys.exit(1)
