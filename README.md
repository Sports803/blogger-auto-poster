# Blogger Feed Auto-Poster

This repository checks a Blogger RSS feed every 30 minutes and publishes newly discovered items to Telegram and/or Buffer. An item is marked as published only after every configured destination confirms success; failed items remain eligible for retry.

## Buffer support

The poster uses Buffer’s documented GraphQL API at `https://api.buffer.com` with a Bearer API key and the `createPost` mutation. This is the reliable server-side automation path for the same Buffer account that can also be connected through Buffer’s remote MCP server at `https://mcp.buffer.com/mcp`.

Buffer’s MCP server is intended for MCP-compatible assistants. This scheduled GitHub Actions job calls the GraphQL API directly so it can run unattended without an MCP client process. The API key works across the Buffer account, so keep it private and never commit it.

## Setup in GitHub Actions

Add these repository secrets under **Settings → Secrets and variables → Actions**:

- `BLOGGER_RSS`
- `BUFFER_API_KEY`
- `BUFFER_CHANNEL_IDS` — comma-separated channel IDs
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` if Telegram is also desired

Optional repository variables:

- `BUFFER_MODE`: `addToQueue` (default), `shareNow`, `shareNext`, or `customScheduled`
- `BUFFER_DUE_AT`: future ISO-8601 timestamp, required only for `customScheduled`

Find channel IDs with Buffer’s API Explorer or by querying the organization’s channels. The current account used during setup has these text-compatible channels:

| Channel | Service | Channel ID |
| --- | --- | --- |
| SportsDelir3n2 | Twitter | `6a7fd0dab2d9d577437e1234` |
| Alvin Alexa | Facebook | `6a7fd04db2d9d577437e1095` |
| Alvin Alexa | YouTube | `69a229104be271803d763ad8` |

The RSS poster sends text and a link, so the Twitter and Facebook channels are ready for this payload. YouTube posts require media and service-specific metadata and should not be enabled until those inputs are implemented.

The workflow is still manually runnable from the **Actions** tab. Use the `dry_run` input to verify feed selection and generated destinations without sending posts.

## Duplicate prevention

The poster stores a persistent index in `posted_items.json`. It uses the feed entry ID first, then GUID, then link, and finally a SHA-256 fallback derived from the item’s title and timestamps. The workflow stores this rolling state on a dedicated `state` branch and caps it at 5,000 entries by default.

## Local test

```bash
python -m py_compile poster.py
BLOGGER_RSS=https://example.com/feed.xml \
BUFFER_API_KEY=redacted \
BUFFER_CHANNEL_IDS=channel_id \
DRY_RUN=true \
python poster.py
```

Use `.env.example` as a configuration reference. Never commit API keys, bot tokens, or other credentials. Because an API key was shared during setup, rotate it in Buffer if it has been exposed outside the intended private setup, then update the GitHub secret.

## References

- [Buffer Quick Start](https://developers.buffer.com/guides/getting-started.html)
- [Buffer Authentication](https://developers.buffer.com/guides/authentication.html)
- [Buffer Your First Post](https://developers.buffer.com/guides/your-first-post.html)
- [Buffer MCP Server](https://developers.buffer.com/guides/integrations/mcp.html)
