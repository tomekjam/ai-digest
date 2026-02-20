# 🤖 AI Daily Digest

A fully automated daily Slack digest that curates the **15 coolest AI stories** — combining industry news with engineering blog posts from top tech companies. Runs for free on GitHub Actions.

## 📋 How It Works

1. **GitHub Actions** triggers the script every morning
2. **Claude API** (with web search) searches both AI news sources AND tech company engineering blogs
3. Stories are scored on novelty, impact, practical relevance, and buzz
4. A beautifully formatted digest is posted to your **Slack channel**

## 📰 Sources

The digest pulls from two categories:

**Industry News** — Major AI announcements, model launches, funding rounds, regulation updates from sources like TechCrunch, The Verge, Ars Technica, Bloomberg, etc.

**Tech Company Engineering Blogs** — Real-world AI implementations from:
Stripe, Spotify, Netflix, Airbnb, Uber, Shopify, LinkedIn, Duolingo, Figma, Notion, GitHub, Vercel, Datadog, Cloudflare, Slack, Monzo, Klarna, Meta, Google DeepMind, OpenAI

You can easily add or remove companies by editing the prompt in `daily_digest.py`.

## 🛠️ Setup Guide

### Step 1: Create the Slack Webhook

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name: `AI & Agile Daily Digest`, select your workspace
3. Sidebar → **Incoming Webhooks** → Toggle **On**
4. Click **Add New Webhook to Workspace**
5. Select the target channel (e.g., `#ai-agile-news`)
6. Copy the webhook URL

### Step 2: Get an Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Make sure you have some credits (this costs ~$0.02-0.05 per run)

### Step 3: Create the GitHub Repository

1. Create a new GitHub repo (can be private)
2. Push these files to the repo:
   ```
   your-repo/
   ├── .github/
   │   └── workflows/
   │       └── daily-digest.yml
   ├── daily_digest.py
   ├── requirements.txt
   └── README.md
   ```

### Step 4: Add GitHub Secrets

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** and add:
   - `ANTHROPIC_API_KEY` → your Anthropic API key
   - `SLACK_WEBHOOK_URL` → your Slack webhook URL

### Step 5: Test It!

1. Go to **Actions** tab in your repo
2. Select **AI Daily Digest** workflow
3. Click **Run workflow** → **Run workflow**
4. Check your Slack channel! 🎉

## ⏰ Adjusting the Schedule

Edit the cron expression in `.github/workflows/daily-digest.yml`:

```yaml
schedule:
  - cron: '0 7 * * *'  # Every day at 7:00 AM UTC (including weekends)
```

Common timezone adjustments:
| Desired Time | UTC Cron |
|---|---|
| 9:00 AM CET (Europe) | `0 8 * * 1-5` |
| 9:00 AM EET (Romania) | `0 7 * * 1-5` |
| 9:00 AM EST (US East) | `0 14 * * 1-5` |
| 9:00 AM PST (US West) | `0 17 * * 1-5` |

Remove `*` at the end to limit to weekdays: `'0 7 * * 1-5'`

## 💰 Cost

- **GitHub Actions**: Free (runs ~2-3 minutes per day, well within free tier)
- **Claude API**: ~$0.08–0.20 per run (Sonnet with web search, 8-10 searches), roughly **$3–6/month**

## 🎨 Customization

### Add or remove company blogs
Edit the "TECH COMPANY AI BLOGS" list in `daily_digest.py` in the `fetch_news_digest()` function prompt.

### Change ranking criteria
Edit the scoring criteria in the same prompt (novelty, impact, relevance, buzz).

### Adjust the industry vs company blog mix
Edit the "Aim for a MIX" instruction in the prompt (default: ~8-9 industry + 6-7 company blogs).

### Change the number of stories
Adjust the "TOP 15" in the prompt and the `[:15]` slice in `parse_stories()`.

## 📸 Example Output

```
🤖 AI Daily Digest — Wednesday, February 18, 2026
Here are today's 10 coolest AI stories — industry news + how top tech companies are using AI 👇
────────────────────────────────
📰 #1 — Anthropic Releases Claude Sonnet 4.6 with 1M Token Context
Summary of the story...
💡 Why it matters: Impact on practitioners...
────────────────────────────────
🏢 #2 — Stripe Engineering: How We Built AI-Powered Fraud Detection at Scale
Summary of the story...
💡 Why it matters: Impact on practitioners...
────────────────────────────────
📰 #3 — Global Memory Chip Shortage Hits as AI Demand Soars
...
────────────────────────────────
🏢 #4 — Spotify's ML Team Shares Lessons from Scaling Recommendation Models
...
```
