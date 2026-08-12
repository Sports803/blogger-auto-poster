import feedparser
import requests
import os
import json
import sys
import re

# === Environment variables (set in GitHub Secrets) ===
BLOGGER_RSS = os.environ.get("BLOGGER_RSS")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
STATE_FILE = "last_post.json"

# Patreon donation link (fixed)
DONATE_URL = "https://www.patreon.com/Alvinalexa?utm_campaign=creatorshare_creator"

def get_last_post_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            return data.get("last_id")
    return None

def save_last_post_id(post_id):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_id": post_id}, f)

def strip_html(html):
    """Remove HTML tags and decode common entities."""
    if not html:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Decode common HTML entities
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'")
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_description(raw_html, max_length=150):
    """Convert HTML to plain text and truncate to 120-150 characters."""
    plain = strip_html(raw_html)
    if len(plain) > max_length:
        # Cut at the last full word
        plain = plain[:max_length].rsplit(' ', 1)[0] + '…'
    return plain

def get_new_posts():
    if not BLOGGER_RSS:
        print("❌ Missing BLOGGER_RSS environment variable")
        sys.exit(1)
    feed = feedparser.parse(BLOGGER_RSS)
    if feed.bozo:
        print(f"⚠️  RSS parse warning: {feed.bozo_exception}")
    last_id = get_last_post_id()
    new_posts = []
    for entry in feed.entries:
        if entry.id == last_id:
            break
        new_posts.append(entry)
    return new_posts[::-1]  # oldest first

def post_to_telegram(title, url, description=""):
    try:
        # Clean description (120-150 chars, plain text)
        clean_desc = clean_description(description, max_length=150)
        
        # Format message: Bold title, normal description, link
        if clean_desc:
            text = f"*{title}*\n\n{clean_desc}\n\n🔗 {url}"
        else:
            text = f"*{title}*\n\n🔗 {url}"
        
        # Build inline keyboard buttons
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📺 Watch", "url": url}],
                [{"text": "❤️ Donate", "url": DONATE_URL}]
            ]
        }
        
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": json.dumps(reply_markup)  # Must be JSON string
        }
        
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data=payload
        )
        
        if resp.status_code == 200:
            print(f"✅ Telegram: {title}")
        else:
            print(f"❌ Telegram error: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram exception: {e}")

def main():
    print(f"🔍 Checking RSS: {BLOGGER_RSS}")
    posts = get_new_posts()
    if not posts:
        print("📭 No new posts.")
        return
    print(f"📨 Found {len(posts)} new post(s)")
    for p in posts:
        title = p.title
        url = p.link
        desc = getattr(p, "summary", "")
        print(f"\n📄 Processing: {title}")
        post_to_telegram(title, url, desc)
        save_last_post_id(p.id)
    print("✅ Done!")

if __name__ == "__main__":
    main()
