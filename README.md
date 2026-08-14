# Blogger Feed Auto-Poster

This repository checks a Blogger RSS feed on a schedule and sends only newly discovered feed items to Telegram. An item is considered published only after Telegram confirms a successful response. Failed items are not marked as published and remain eligible for retry on the next run.

## Setup

Add these GitHub Actions repository secrets under **Settings → Secrets and variables → Actions**:

- `BLOGGER_RSS`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The workflow runs every 30 minutes and can also be started manually from the **Actions** tab. Runs are serialized so two executions cannot update the deduplication state simultaneously.

## Duplicate prevention

The poster stores a persistent index in `posted_items.json`. It uses the feed entry ID first, then GUID, then link, and finally a SHA-256 fallback derived from the item’s title and timestamps. Therefore, a feed refresh, changed ordering, or an older item appearing again will not cause a duplicate Telegram post.

The GitHub Actions workflow restores the newest rolling state cache before each run and saves a new cache after the run. The state is capped at 5,000 entries by default. The `MAX_ITEMS_PER_RUN` environment variable limits the number of new items processed in one execution and defaults to 50 in the workflow.

## Local test

```bash
python -m py_compile poster.py
BLOGGER_RSS=https://example.com/feed.xml \
TELEGRAM_BOT_TOKEN=redacted \
TELEGRAM_CHAT_ID=redacted \
python poster.py
```

Never commit bot tokens or other credentials. Existing items are skipped according to the persistent state index; to intentionally reprocess an item, remove only its key from `posted_items.json` during a controlled manual run.
