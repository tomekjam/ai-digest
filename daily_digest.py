"""
AI Daily Digest
================
Fetches the 10 coolest AI news stories — both industry news and engineering blog posts 
from top tech companies — using Claude's web search, then posts a detailed digest to Slack.
"""

import os
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"

HISTORY_FILE = Path("history.json")
HISTORY_DAYS = 3  # How many days of history to keep


def load_history() -> dict:
    """Load story history from file. Returns dict with dates as keys and story lists as values."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_history(history: dict):
    """Save story history to file, pruning entries older than HISTORY_DAYS."""
    cutoff = (datetime.now() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    pruned = {date: stories for date, stories in history.items() if date >= cutoff}
    HISTORY_FILE.write_text(json.dumps(pruned, indent=2))


def get_recent_titles(history: dict) -> list[str]:
    """Get all story titles from recent history for deduplication."""
    titles = []
    for stories in history.values():
        for story in stories:
            titles.append(story.get("title", ""))
    return [t for t in titles if t]


def fetch_news_digest(recent_titles: list[str]) -> str:
    """Use Claude with web search to find and rank today's top AI news."""

    today = datetime.now().strftime("%B %d, %Y")

    # Build the deduplication block
    dedup_block = ""
    if recent_titles:
        titles_list = "\n".join(f"- {t}" for t in recent_titles)
        dedup_block = f"""
CRITICAL — DO NOT REPEAT THESE STORIES. They were already covered in previous days:
{titles_list}

If a story is an UPDATE or SIGNIFICANT NEW DEVELOPMENT on a previous topic, you may include 
it but you MUST frame it as new information (e.g., "Update: ..." or "New development: ..."). 
Do NOT include the same announcement, launch, or event just reworded.
"""

    prompt = f"""Today is {today}. Search the web thoroughly for the most interesting and impactful 
AI news from the last 24-48 hours. Cover BOTH major industry news AND how leading tech companies 
are applying AI in practice.

Search for at least 8-10 different queries to get broad coverage. Include:

INDUSTRY NEWS (search for these):
- Latest AI news today
- AI breakthroughs announcements this week
- AI tools and product launches
- LLM and generative AI updates
- AI startup funding news
- AI regulation policy news

TECH COMPANY AI BLOGS (search for recent posts from these sources):
- Stripe engineering blog AI
- Spotify engineering blog AI machine learning
- Netflix tech blog AI
- Airbnb engineering AI
- Uber engineering blog AI ML
- Shopify engineering AI
- LinkedIn engineering blog AI
- Duolingo AI blog
- Figma AI blog
- Notion AI blog
- GitHub blog AI
- Vercel AI blog
- Datadog engineering AI
- Cloudflare blog AI
- Slack engineering blog AI
- Monzo engineering blog AI
- Klarna AI blog
- Meta engineering AI blog
- Google DeepMind blog
- OpenAI blog

Prioritize stories from the company blogs that describe REAL implementations, 
lessons learned, architectures, or case studies — not just marketing announcements.

After gathering results, select the TOP 15 most "cool" stories. Rank by:
1. **Novelty** — Is this genuinely new or surprising?
2. **Impact** — Will this affect practitioners, businesses, or the industry?
3. **Practical relevance** — Can someone act on or learn from this?
4. **Buzz** — Is the community talking about it?

IMPORTANT RULES FOR DIVERSITY:
- NEVER include more than 2 stories about the same event, conference, or summit. Consolidate 
  related announcements from the same event into a single story.
- NEVER include more than 2 stories about the same company. Pick only the most impactful one.
- Maximize TOPIC diversity: spread across model releases, company use cases, research, 
  regulation, infrastructure, funding, open source, and practical applications.
- If a major event (like a summit or conference) produced many announcements, pick the 
  1-2 most impactful and move on to other topics.
{dedup_block}
Aim for a MIX: roughly 8-9 industry news stories and 6-7 company engineering blog posts.

For each of the 15 stories, provide EXACTLY this format (this will be parsed):

===STORY===
TITLE: [Headline]
URL: [Source URL]
CATEGORY: [Industry or Company]
SUMMARY: [2-3 sentence summary of what happened]
WHY_IT_MATTERS: [1-2 sentences on why a practitioner should care]
===END===

Be specific. Use real URLs from your search results. Do not invent or hallucinate stories."""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": MODEL,
        "max_tokens": 6144,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}],
    }

    response = requests.post(CLAUDE_API_URL, headers=headers, json=payload)
    response.raise_for_status()
    data = response.json()

    # Extract all text blocks from the response
    text_parts = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block["text"])

    return "\n".join(text_parts)


def parse_stories(raw_text: str) -> list[dict]:
    """Parse the structured story output from Claude."""
    stories = []
    chunks = raw_text.split("===STORY===")

    for chunk in chunks:
        if "===END===" not in chunk:
            continue
        content = chunk.split("===END===")[0].strip()

        story = {}
        for line in content.split("\n"):
            line = line.strip()
            for field in ["TITLE", "URL", "CATEGORY", "SUMMARY", "WHY_IT_MATTERS"]:
                if line.startswith(f"{field}:"):
                    story[field.lower()] = line[len(field) + 1 :].strip()
                    break

        if story.get("title"):
            stories.append(story)

    return stories[:15]


def build_slack_message(stories: list[dict]) -> dict:
    """Build a rich Slack Block Kit message from parsed stories."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🤖 AI Daily Digest — {today}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Here are today's *15 coolest AI stories* — industry news + how top tech companies are using AI 👇",
            },
        },
        {"type": "divider"},
    ]

    category_emoji = {"industry": "📰", "company": "🏢"}

    for i, story in enumerate(stories, 1):
        cat = story.get("category", "").lower()
        emoji = category_emoji.get(cat, "📰")
        title = story.get("title", "Untitled")
        url = story.get("url", "")
        summary = story.get("summary", "No summary available.")
        why = story.get("why_it_matters", "")

        title_text = f"<{url}|{title}>" if url else title

        text = f"{emoji} *#{i} — {title_text}*\n\n{summary}"
        if why:
            text += f"\n\n💡 *Why it matters:* {why}"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "🛠️ Powered by Claude AI | Industry news 📰 + Company engineering blogs 🏢",
                }
            ],
        }
    )

    return {"blocks": blocks}


def post_to_slack(message: dict):
    """Send the formatted message to Slack via webhook."""
    response = requests.post(
        SLACK_WEBHOOK_URL,
        json=message,
        headers={"Content-Type": "application/json"},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Slack webhook failed ({response.status_code}): {response.text}"
        )
    print("✅ Successfully posted digest to Slack!")


def main():
    print("📂 Loading story history...")
    history = load_history()
    recent_titles = get_recent_titles(history)
    print(f"   Found {len(recent_titles)} stories from the last {HISTORY_DAYS} days")

    print("🔍 Fetching today's AI news via Claude...")
    raw_digest = fetch_news_digest(recent_titles)

    print("📝 Parsing stories...")
    stories = parse_stories(raw_digest)
    print(f"   Found {len(stories)} stories")

    if not stories:
        print("⚠️ No stories parsed. Posting raw digest as fallback.")
        fallback_msg = {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*AI Daily Digest*\n\n{raw_digest[:3000]}",
                    },
                }
            ]
        }
        post_to_slack(fallback_msg)
        return

    # Save today's stories to history
    today_key = datetime.now().strftime("%Y-%m-%d")
    history[today_key] = [
        {"title": s.get("title", ""), "url": s.get("url", "")}
        for s in stories
    ]
    save_history(history)
    print(f"💾 Saved {len(stories)} stories to history")

    print("🎨 Building Slack message...")
    slack_message = build_slack_message(stories)

    print("📤 Posting to Slack...")
    post_to_slack(slack_message)


if __name__ == "__main__":
    main()
