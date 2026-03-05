# 🤖 AI Daily Digest v2

AI-curated tech news, delivered daily to Slack with a browsable archive on GitHub Pages.

## How It Works

```
Sources (free)        Score (cheap)       Enrich (cheap)      Publish
──────────────       ─────────────       ──────────────      ───────
Hacker News ─┐                                               Slack
RSS feeds   ─┼→ Deduplicate → AI Score → Top 10 → AI Enrich ─┤
Reddit      ─┘   (local)      0-10       filter   summaries  GitHub Pages
                               batch     history   context    history.json
```

1. **Fetch** — Pulls from Hacker News API, 13 RSS feeds, 3 Reddit subreddits (all free)
2. **Deduplicate** — Merges items with same URL or similar title (local, no API)
3. **Score** — AI rates each item 0-10 in one batch call (~$0.005)
4. **Filter** — Keeps top 10 above threshold, checks against 30-day history
5. **Enrich** — AI generates summary, "why it matters", and background context (~$0.01)
6. **Publish** — Posts to Slack + generates GitHub Pages markdown
7. **History** — Saves stories to prevent repeats (forever)

**Total cost: ~$0.02 per run / ~$0.60 per month**

## Setup

### 1. Create a Slack Webhook
1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch
2. Enable **Incoming Webhooks** → Add New Webhook to Workspace
3. Select your channel → Copy the webhook URL

### 2. Get an Anthropic API Key
1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key and add credits ($5 will last months)

### 3. Set Up the Repo
1. Fork or clone this repo
2. Go to **Settings → Secrets → Actions** and add:
   - `ANTHROPIC_API_KEY`
   - `SLACK_WEBHOOK_URL`
3. Go to **Settings → Pages** → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs`

### 4. Test It
Go to **Actions → AI Daily Digest → Run workflow**

## Sources

| Source | Items Fetched | Auth Required |
|--------|--------------|---------------|
| Hacker News API | Top 30 (score ≥ 50) | No |
| TechCrunch AI (RSS) | Latest 10 | No |
| MIT Tech Review (RSS) | Latest 10 | No |
| The Verge AI (RSS) | Latest 10 | No |
| Ars Technica (RSS) | Latest 10 | No |
| Simon Willison (RSS) | Latest 10 | No |
| Anthropic Blog (RSS) | Latest 10 | No |
| OpenAI Blog (RSS) | Latest 10 | No |
| Stripe Blog (RSS) | Latest 10 | No |
| Netflix Tech Blog (RSS) | Latest 10 | No |
| Spotify Engineering (RSS) | Latest 10 | No |
| GitHub Blog (RSS) | Latest 10 | No |
| Google AI Blog (RSS) | Latest 10 | No |
| r/MachineLearning | Hot 15 | No |
| r/artificial | Hot 10 | No |
| r/LocalLLaMA | Hot 10 | No |

## Customization

### Add/remove sources
Edit the `CONFIG` dict in `daily_digest.py`:
- Add RSS feeds to the `rss` list
- Add subreddits to `reddit.subreddits`
- Adjust `hackernews.min_score` to control HN quality threshold

### Change story count
Adjust `TOP_N = 10` and `SCORE_THRESHOLD = 6.0`

### Change schedule
Edit the cron in `.github/workflows/daily-digest.yml`

### Change AI model
Edit `MODEL` in `daily_digest.py` (default: `claude-haiku-4-5-20251001`)

## Cost Breakdown

| Component | Cost |
|-----------|------|
| Source fetching (HN, RSS, Reddit) | Free |
| AI scoring (~60 items, 1 batch call) | ~$0.005 |
| AI enrichment (10 stories) | ~$0.01 |
| GitHub Actions | Free |
| **Total per run** | **~$0.02** |
| **Monthly (daily runs)** | **~$0.60** |
