import feedparser
import requests
import os
import json
import sys

BLOGGER_RSS = os.environ.get("BLOGGER_RSS")
STATE_FILE = "last_post.json"

import tweepy
TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY")
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET")

FACEBOOK_PAGE_ID = os.environ.get("FACEBOOK_PAGE_ID")
FACEBOOK_ACCESS_TOKEN = os.environ.get("FACEBOOK_ACCESS_TOKEN")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

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
        print("❌ Missing BLOGGER_RSS")
        sys.exit(1)
    feed = feedparser.parse(BLOGGER_RSS)
    last_id = get_last_post_id()
    new_posts = []
    for entry in feed.entries:
        if entry.id == last_id:
            break
        new_posts.append(entry)
    return new_posts[::-1]

def post_to_twitter(title, url):
    try:
        client = tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_SECRET
        )
        max_len = 280 - len(url) - 1
        tweet = f"{title[:max_len]}… {url}" if len(title) > max_len else f"{title} {url}"
        client.create_tweet(text=tweet)
        print(f"✅ Twitter: {title}")
    except Exception as e:
        print(f"❌ Twitter: {e}")

def post_to_facebook(title, url, description=""):
    try:
        msg = f"{title}\n\n{description[:300]}\n\n{url}" if description else f"{title}\n\n{url}"
        payload = {"message": msg, "access_token": FACEBOOK_ACCESS_TOKEN}
        resp = requests.post(f"https://graph.facebook.com/{FACEBOOK_PAGE_ID}/feed", data=payload)
        if resp.status_code == 200:
            print(f"✅ Facebook: {title}")
        else:
            print(f"❌ Facebook: {resp.text}")
    except Exception as e:
        print(f"❌ Facebook: {e}")

def post_to_telegram(title, url, description=""):
    try:
        text = f"📝 *{title}*\n\n{description[:300]}\n\n🔗 {url}" if description else f"📝 *{title}*\n\n🔗 {url}"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
        resp = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", data=payload)
        if resp.status_code == 200:
            print(f"✅ Telegram: {title}")
        else:
            print(f"❌ Telegram: {resp.text}")
    except Exception as e:
        print(f"❌ Telegram: {e}")

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
        desc = getattr(p, "summary", "")[:500]
        print(f"\n📄 Processing: {title}")
        post_to_twitter(title, url)
        post_to_facebook(title, url, desc)
        post_to_telegram(title, url, desc)
        save_last_post_id(p.id)
    print("✅ Done!")

if __name__ == "__main__":
    main()
