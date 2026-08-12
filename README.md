# Blogger Auto-Poster

Posts new Blogger entries to Twitter, Facebook Page, and Telegram via GitHub Actions.

## Setup
1. Add these secrets in your repo Settings → Secrets and variables → Actions:
   - `BLOGGER_RSS`, `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`, `FACEBOOK_PAGE_ID`, `FACEBOOK_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
2. Go to the Actions tab and manually run the workflow to test.
3. The cron runs every hour (edit `.github/workflows/post-schedule.yml` to change).
