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

def clean_html(raw_html):
    """Remove HTML tags and clean up whitespace."""
    if not raw_html:
        return ""
    # Remove HTML tags
    clean_text = re.sub(r'<[^>]+>', '', raw_html)
    # Replace multiple spaces/newlines with a single space
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    return clean_text

def get_last_post_id():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            return data.get("last_id")
    return None

def save_last_post_id(post_id):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_id": post_id}, f)

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
        # Clean HTML and truncate description to ~150 chars
        plain_desc = clean_html(description)
        if len(plain_desc) > 150:
            plain_desc = plain_desc[:147] + "..."
            
        text = f"📝 *{title}*\n\n{plain_desc}\n\n🔗 {url}" if plain_desc else f"📝 *{title}*\n\n🔗 {url}"
        
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown"
        }
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data=payload)
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
        # Use 'summary' or 'description' from RSS entry
        desc = getattr(p, "summary", getattr(p, "description", ""))
        print(f"\n📄 Processing: {title}")
        post_to_telegram(title, url, desc)
        save_last_post_id(p.id)
    print("✅ Done!")

if __name__ == "__main__":
    main()
