"""
AI Daily Digest — v2
====================
Multi-source AI news aggregator with scoring, enrichment, and multi-channel publishing.

Architecture:
  1. FETCH     — Pull from Hacker News, RSS feeds, Reddit (all free, no API cost)
  2. DEDUPLICATE — Merge items pointing to the same story
  3. SCORE     — AI rates each item 0-10 (cheap batch call)
  4. FILTER    — Keep top N above threshold
  5. ENRICH    — AI generates summary + "why it matters" + background (only for winners)
  6. PUBLISH   — Post to Slack + generate GitHub Pages markdown
  7. HISTORY   — Save to prevent repeats
"""

import os
import re
import json
import hashlib
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── Configuration ───────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"

HISTORY_FILE = Path("history.json")
DOCS_DIR = Path("docs")
PROMPT_HISTORY_DAYS = 30
SCORE_THRESHOLD = 6.0
TOP_N = 10
FETCH_HOURS = 48

# ─── Source Configuration ────────────────────────────────────────────────────

CONFIG = {
    "hackernews": {
        "enabled": True,
        "top_stories": 30,
        "min_score": 50,
    },
    "rss": [
        {"name": "Hacker News Best", "url": "https://hnrss.org/best?count=20"},
        {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
        {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/"},
        {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
        {"name": "Ars Technica AI", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab"},
        {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/"},
        {"name": "Anthropic Blog", "url": "https://www.anthropic.com/rss.xml"},
        {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml"},
        {"name": "Stripe Blog", "url": "https://stripe.com/blog/feed.rss"},
        {"name": "Netflix Tech", "url": "https://netflixtechblog.com/feed"},
        {"name": "Spotify Engineering", "url": "https://engineering.atspotify.com/feed/"},
        {"name": "GitHub Blog", "url": "https://github.blog/feed/"},
        {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/"},
    ],
    "reddit": {
        "enabled": True,
        "subreddits": [
            {"name": "MachineLearning", "sort": "hot", "limit": 15},
            {"name": "artificial", "sort": "hot", "limit": 10},
            {"name": "LocalLLaMA", "sort": "hot", "limit": 10},
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1: FETCH
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_hackernews(config: dict) -> list[dict]:
    """Fetch top stories from Hacker News API (free, no auth)."""
    items = []
    try:
        print("  📡 Fetching Hacker News...")
        resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        )
        story_ids = resp.json()[: config["top_stories"]]

        def fetch_story(sid):
            try:
                r = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                    timeout=5,
                )
                return r.json()
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(fetch_story, sid): sid for sid in story_ids}
            for future in as_completed(futures):
                story = future.result()
                if story and story.get("score", 0) >= config["min_score"]:
                    items.append(
                        {
                            "title": story.get("title", ""),
                            "url": story.get("url", f"https://news.ycombinator.com/item?id={story['id']}"),
                            "source": "Hacker News",
                            "score_hint": story.get("score", 0),
                            "comments_url": f"https://news.ycombinator.com/item?id={story['id']}",
                            "timestamp": datetime.fromtimestamp(
                                story.get("time", 0), tz=timezone.utc
                            ).isoformat(),
                        }
                    )
        print(f"     Found {len(items)} stories (score >= {config['min_score']})")
    except Exception as e:
        print(f"  ⚠️ Hacker News fetch failed: {e}")
    return items


def fetch_rss(feeds: list[dict]) -> list[dict]:
    """Fetch items from RSS/Atom feeds (free, no auth)."""
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)

    def fetch_one_feed(feed):
        feed_items = []
        try:
            parsed = feedparser.parse(feed["url"])
            for entry in parsed.entries[:10]:
                # Parse published date
                published = None
                for date_field in ["published_parsed", "updated_parsed"]:
                    if hasattr(entry, date_field) and getattr(entry, date_field):
                        from calendar import timegm
                        published = datetime.fromtimestamp(
                            timegm(getattr(entry, date_field)), tz=timezone.utc
                        )
                        break

                # Skip old entries
                if published and published < cutoff:
                    continue

                title = entry.get("title", "").strip()
                url = entry.get("link", "").strip()
                if title and url:
                    feed_items.append(
                        {
                            "title": title,
                            "url": url,
                            "source": feed["name"],
                            "score_hint": 0,
                            "timestamp": published.isoformat() if published else "",
                        }
                    )
        except Exception as e:
            print(f"     ⚠️ RSS feed '{feed['name']}' failed: {e}")
        return feed_items

    print(f"  📡 Fetching {len(feeds)} RSS feeds...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch_one_feed, f) for f in feeds]
        for future in as_completed(futures):
            items.extend(future.result())

    print(f"     Found {len(items)} items from RSS")
    return items


def fetch_reddit(config: dict) -> list[dict]:
    """Fetch from Reddit JSON API (free, no auth for public subreddits)."""
    items = []
    headers = {"User-Agent": "AI-Digest-Bot/2.0"}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FETCH_HOURS)

    for sub in config["subreddits"]:
        try:
            url = f"https://www.reddit.com/r/{sub['name']}/{sub['sort']}.json?limit={sub['limit']}"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                print(f"     ⚠️ Reddit r/{sub['name']} returned {resp.status_code}")
                continue

            data = resp.json()
            for post in data.get("data", {}).get("children", []):
                d = post["data"]
                created = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
                if created < cutoff:
                    continue

                # Prefer the linked URL, fall back to reddit post
                post_url = d.get("url", "")
                if post_url.startswith("/r/") or "reddit.com" in post_url:
                    post_url = f"https://www.reddit.com{d.get('permalink', '')}"

                items.append(
                    {
                        "title": d.get("title", "").strip(),
                        "url": post_url,
                        "source": f"r/{sub['name']}",
                        "score_hint": d.get("score", 0),
                        "comments_url": f"https://www.reddit.com{d.get('permalink', '')}",
                        "timestamp": created.isoformat(),
                    }
                )
        except Exception as e:
            print(f"     ⚠️ Reddit r/{sub['name']} failed: {e}")

    print(f"  📡 Fetching Reddit... Found {len(items)} posts")
    return items


def fetch_all_sources() -> list[dict]:
    """Fetch from all configured sources."""
    print("\n📡 PHASE 1: Fetching from all sources...")
    all_items = []

    if CONFIG["hackernews"]["enabled"]:
        all_items.extend(fetch_hackernews(CONFIG["hackernews"]))

    all_items.extend(fetch_rss(CONFIG["rss"]))

    if CONFIG["reddit"]["enabled"]:
        all_items.extend(fetch_reddit(CONFIG["reddit"]))

    print(f"   Total raw items: {len(all_items)}")
    return all_items


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2: DEDUPLICATE
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_url(url: str) -> str:
    """Normalize URL for dedup comparison."""
    parsed = urlparse(url)
    # Strip tracking params, www prefix, trailing slashes
    clean = f"{parsed.netloc.replace('www.', '')}{parsed.path.rstrip('/')}"
    return clean.lower()


def normalize_title(title: str) -> str:
    """Normalize title for fuzzy dedup."""
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def deduplicate(items: list[dict]) -> list[dict]:
    """Remove duplicate items based on URL and title similarity."""
    print("\n🔗 PHASE 2: Deduplicating...")
    seen_urls = {}
    seen_titles = {}
    unique = []

    for item in items:
        url_key = normalize_url(item["url"])
        title_key = normalize_title(item["title"])

        # Skip if same URL already seen
        if url_key in seen_urls:
            # Keep the one with more info (higher score_hint)
            existing = seen_urls[url_key]
            if item.get("score_hint", 0) > existing.get("score_hint", 0):
                unique.remove(existing)
                unique.append(item)
                seen_urls[url_key] = item
            continue

        # Skip if very similar title (first 60 chars match)
        title_short = title_key[:60]
        if title_short and title_short in seen_titles:
            continue

        seen_urls[url_key] = item
        if title_short:
            seen_titles[title_short] = item
        unique.append(item)

    print(f"   {len(items)} → {len(unique)} after dedup")
    return unique


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3: AI SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def score_items(items: list[dict]) -> list[dict]:
    """Use AI to score each item 0-10 in a single batch call."""
    print(f"\n🧠 PHASE 3: AI scoring {len(items)} items...")

    # Build a compact list of titles for scoring
    items_text = "\n".join(
        f"{i+1}. [{item['source']}] {item['title']}"
        for i, item in enumerate(items)
    )

    prompt = f"""Score each news item 0-10 for relevance to AI/tech practitioners. 
Consider: technical depth, novelty, practical impact, industry significance.
Score 0 for spam, off-topic, or duplicates. Score 8+ for major breakthroughs or deeply useful posts.

Items:
{items_text}

Respond with ONLY a JSON array of scores, one per item, in order. Example: [7, 3, 9, ...]
No other text."""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": "You are a tech news curator. Respond with only JSON. No commentary.",
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        response = requests.post(CLAUDE_API_URL, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            print(f"   ❌ Scoring API error {response.status_code}: {response.text[:200]}")
            # Fallback: use source score hints
            for item in items:
                item["ai_score"] = min(item.get("score_hint", 0) / 50, 10)
            return items

        data = response.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        # Parse the JSON scores
        text = text.strip().strip("```json").strip("```").strip()
        scores = json.loads(text)

        for i, item in enumerate(items):
            if i < len(scores):
                item["ai_score"] = float(scores[i])
            else:
                item["ai_score"] = 0

        scored_count = sum(1 for item in items if item["ai_score"] >= SCORE_THRESHOLD)
        print(f"   Scored! {scored_count}/{len(items)} items above threshold ({SCORE_THRESHOLD})")

    except (json.JSONDecodeError, ValueError) as e:
        print(f"   ⚠️ Score parsing failed: {e}. Using source hints as fallback.")
        for item in items:
            item["ai_score"] = min(item.get("score_hint", 0) / 50, 10)

    return items


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: FILTER
# ═══════════════════════════════════════════════════════════════════════════════

def filter_top_stories(items: list[dict], history_titles: list[str]) -> list[dict]:
    """Filter to top N items above threshold, excluding history."""
    print(f"\n🎯 PHASE 4: Filtering top {TOP_N}...")

    # Remove items that match history
    history_normalized = {normalize_title(t) for t in history_titles}
    fresh = []
    for item in items:
        item_norm = normalize_title(item["title"])
        # Check if any history title is a close match (first 50 chars)
        if item_norm[:50] in {h[:50] for h in history_normalized}:
            continue
        fresh.append(item)

    print(f"   {len(items)} → {len(fresh)} after history check")

    # Sort by AI score descending, take top N
    fresh.sort(key=lambda x: x.get("ai_score", 0), reverse=True)
    top = [item for item in fresh if item.get("ai_score", 0) >= SCORE_THRESHOLD][:TOP_N]

    print(f"   Selected {len(top)} stories")
    for i, item in enumerate(top):
        print(f"     {i+1}. [{item['ai_score']:.0f}] {item['title'][:70]}")

    return top


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 5: ENRICH
# ═══════════════════════════════════════════════════════════════════════════════

def enrich_stories(stories: list[dict]) -> list[dict]:
    """Use AI to generate summaries, 'why it matters', and background context."""
    print(f"\n✨ PHASE 5: Enriching {len(stories)} stories...")

    stories_text = "\n\n".join(
        f"ITEM {i+1}:\n  Title: {s['title']}\n  URL: {s['url']}\n  Source: {s['source']}"
        for i, s in enumerate(stories)
    )

    prompt = f"""For each news item below, generate a brief enrichment. Use your knowledge and the titles/URLs to provide context.

{stories_text}

For each item, respond in EXACTLY this format:

===ITEM 1===
SUMMARY: [2-3 sentence summary of what this is about]
WHY_IT_MATTERS: [1-2 sentences on practical impact for AI/tech practitioners]
BACKGROUND: [1 sentence of context for anyone unfamiliar with the topic]
CATEGORY: [One of: Model Release, Company Engineering, Research, Infrastructure, Regulation, Funding, Open Source, Product Launch]
===END===

===ITEM 2===
...and so on for all items. Use real facts only — do not invent details."""

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": MODEL,
        "max_tokens": 4096,
        "system": (
            "You are a concise tech news enricher. "
            "No narration or commentary — just the structured output requested."
        ),
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        response = requests.post(CLAUDE_API_URL, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            print(f"   ❌ Enrichment API error {response.status_code}: {response.text[:200]}")
            return stories

        data = response.json()
        text = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text += block["text"]

        # Parse enrichments
        for i, story in enumerate(stories):
            marker = f"===ITEM {i+1}==="
            if marker in text:
                chunk = text.split(marker)[1]
                if "===END===" in chunk:
                    chunk = chunk.split("===END===")[0]
                elif f"===ITEM {i+2}===" in chunk:
                    chunk = chunk.split(f"===ITEM {i+2}===")[0]

                for field in ["SUMMARY", "WHY_IT_MATTERS", "BACKGROUND", "CATEGORY"]:
                    for line in chunk.split("\n"):
                        line = line.strip()
                        if line.startswith(f"{field}:"):
                            story[field.lower()] = line[len(field) + 1:].strip()

        enriched = sum(1 for s in stories if s.get("summary"))
        print(f"   Enriched {enriched}/{len(stories)} stories")

    except Exception as e:
        print(f"   ⚠️ Enrichment failed: {e}")

    return stories


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 6: PUBLISH — SLACK
# ═══════════════════════════════════════════════════════════════════════════════

CATEGORY_EMOJI = {
    "model release": "🧠",
    "company engineering": "🏢",
    "research": "🔬",
    "infrastructure": "🏗️",
    "regulation": "⚖️",
    "funding": "💰",
    "open source": "🔓",
    "product launch": "🚀",
}


def publish_to_slack(stories: list[dict]):
    """Build and post Slack Block Kit message."""
    if not SLACK_WEBHOOK_URL:
        print("   ⚠️ No SLACK_WEBHOOK_URL set, skipping Slack")
        return

    print(f"\n📤 PHASE 6a: Posting to Slack...")
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
                "text": (
                    f"Today's top *{len(stories)} AI stories* from "
                    f"Hacker News, Reddit, RSS, and engineering blogs 👇"
                ),
            },
        },
        {"type": "divider"},
    ]

    for i, story in enumerate(stories, 1):
        cat = story.get("category", "").lower()
        emoji = CATEGORY_EMOJI.get(cat, "📰")
        title = story.get("title", "Untitled")
        url = story.get("url", "")
        summary = story.get("summary", "")
        why = story.get("why_it_matters", "")
        background = story.get("background", "")
        source = story.get("source", "")
        score = story.get("ai_score", 0)

        title_text = f"<{url}|{title}>" if url else title
        text = f"{emoji} *#{i} — {title_text}*"
        text += f"\n_{source} · Score: {score:.0f}/10_"

        if summary:
            text += f"\n\n{summary}"
        if why:
            text += f"\n\n💡 *Why it matters:* {why}"
        if background:
            text += f"\n\n📚 _{background}_"

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "🛠️ Powered by AI Daily Digest v2 "
                        "| Sources: HN + Reddit + RSS + Engineering Blogs "
                        "| Scored & enriched by Claude"
                    ),
                }
            ],
        }
    )

    message = {"blocks": blocks}
    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json=message,
        headers={"Content-Type": "application/json"},
    )
    if resp.status_code != 200:
        print(f"   ❌ Slack webhook failed ({resp.status_code}): {resp.text}")
    else:
        print("   ✅ Posted to Slack!")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 6: PUBLISH — GITHUB PAGES
# ═══════════════════════════════════════════════════════════════════════════════

def publish_to_pages(stories: list[dict]):
    """Generate markdown files for GitHub Pages."""
    print(f"\n📄 PHASE 6b: Generating GitHub Pages...")

    DOCS_DIR.mkdir(exist_ok=True)
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    display_date = today.strftime("%A, %B %d, %Y")

    # Generate daily digest page
    md_lines = [
        "---",
        f"title: \"AI Digest — {display_date}\"",
        f"date: {date_str}",
        "layout: default",
        "---",
        "",
        f"# 🤖 AI Daily Digest — {display_date}",
        "",
        f"*{len(stories)} top stories from Hacker News, Reddit, RSS feeds, and engineering blogs.*",
        "",
        "---",
        "",
    ]

    for i, story in enumerate(stories, 1):
        cat = story.get("category", "")
        emoji = CATEGORY_EMOJI.get(cat.lower(), "📰")
        title = story.get("title", "Untitled")
        url = story.get("url", "")
        summary = story.get("summary", "")
        why = story.get("why_it_matters", "")
        background = story.get("background", "")
        source = story.get("source", "")
        score = story.get("ai_score", 0)

        md_lines.append(f"### {emoji} #{i} — [{title}]({url})")
        md_lines.append(f"*{source} · Score: {score:.0f}/10 · {cat}*")
        md_lines.append("")
        if summary:
            md_lines.append(summary)
            md_lines.append("")
        if why:
            md_lines.append(f"💡 **Why it matters:** {why}")
            md_lines.append("")
        if background:
            md_lines.append(f"📚 *{background}*")
            md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    md_lines.append("*Generated by [AI Daily Digest](https://github.com/tomekjam/ai-digest)*")

    # Write daily page
    daily_file = DOCS_DIR / f"{date_str}.md"
    daily_file.write_text("\n".join(md_lines))
    print(f"   Wrote {daily_file}")

    # Update index page with links to all daily digests
    digest_files = sorted(DOCS_DIR.glob("2*.md"), reverse=True)
    index_lines = [
        "---",
        "title: AI Daily Digest",
        "layout: default",
        "---",
        "",
        "# 🤖 AI Daily Digest Archive",
        "",
        "*AI-curated tech news, updated daily.*",
        "",
    ]
    for f in digest_files[:30]:  # Show last 30 days
        d = f.stem
        try:
            display = datetime.strptime(d, "%Y-%m-%d").strftime("%A, %B %d, %Y")
        except ValueError:
            display = d
        index_lines.append(f"- [{display}]({d})")

    index_file = DOCS_DIR / "index.md"
    index_file.write_text("\n".join(index_lines))
    print(f"   Updated {index_file}")

    # Ensure Jekyll config exists
    config_file = DOCS_DIR / "_config.yml"
    if not config_file.exists():
        config_file.write_text(
            "title: AI Daily Digest\n"
            "description: AI-curated tech news, updated daily\n"
            "theme: jekyll-theme-minimal\n"
            "baseurl: /ai-digest\n"
        )
        print(f"   Created {config_file}")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 7: HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

def load_history() -> dict:
    """Load story history from file."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_history(history: dict, stories: list[dict]):
    """Save today's stories to history."""
    today_key = datetime.now().strftime("%Y-%m-%d")
    history[today_key] = [
        {"title": s.get("title", ""), "url": s.get("url", "")}
        for s in stories
    ]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def get_recent_titles(history: dict) -> list[str]:
    """Get story titles from recent history for dedup."""
    cutoff = (datetime.now() - timedelta(days=PROMPT_HISTORY_DAYS)).strftime("%Y-%m-%d")
    titles = []
    for date, stories in history.items():
        if date >= cutoff:
            for story in stories:
                titles.append(story.get("title", ""))
    return [t for t in titles if t][:100]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("🤖 AI Daily Digest v2")
    print("=" * 60)

    # Load history
    history = load_history()
    recent_titles = get_recent_titles(history)
    print(f"📂 Loaded {len(recent_titles)} titles from history")

    # Phase 1: Fetch
    all_items = fetch_all_sources()
    if not all_items:
        print("❌ No items fetched from any source. Exiting.")
        return

    # Phase 2: Deduplicate
    unique_items = deduplicate(all_items)

    # Phase 3: Score
    scored_items = score_items(unique_items)

    # Phase 4: Filter
    top_stories = filter_top_stories(scored_items, recent_titles)
    if not top_stories:
        print("❌ No stories passed filtering. Exiting.")
        return

    # Phase 5: Enrich
    enriched_stories = enrich_stories(top_stories)

    # Phase 6: Publish
    publish_to_slack(enriched_stories)
    publish_to_pages(enriched_stories)

    # Phase 7: Save history
    save_history(history, enriched_stories)
    print(f"\n💾 Saved {len(enriched_stories)} stories to history")

    print("\n" + "=" * 60)
    print("✅ Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
