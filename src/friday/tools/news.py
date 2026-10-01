"""News tools — topic briefings from RSS feeds and keyword news search."""

import asyncio
import json
from urllib.parse import quote_plus

from ddgs import DDGS

from .feeds import clean_text, fetch_feeds

BRIEFING_FEEDS: dict[str, dict[str, str]] = {
    "world": {
        "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
        "The Guardian": "https://www.theguardian.com/world/rss",
        "NPR": "https://feeds.npr.org/1004/rss.xml",
    },
    "finance": {
        "CNBC": "https://www.cnbc.com/id/10000664/device/rss/rss.html",
        "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
        "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    },
    "tech": {
        "The Verge": "https://www.theverge.com/rss/index.xml",
        "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
        "TechCrunch": "https://techcrunch.com/feed/",
        "Wired": "https://www.wired.com/feed/rss",
    },
    "science": {
        "BBC Science": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "NASA": "https://www.nasa.gov/news-release/feed/",
        "ScienceDaily": "https://www.sciencedaily.com/rss/top/science.xml",
    },
    "india": {
        "The Hindu": "https://www.thehindu.com/news/national/feeder/default.rss",
        "NDTV": "https://feeds.feedburner.com/ndtvnews-top-stories",
        "Times of India": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    },
}


def _is_iso_date(value: str | None) -> bool:
    return bool(value) and value[:4].isdigit()


def register(mcp) -> None:
    @mcp.tool()
    async def get_briefing(topic: str = "world") -> str:
        """Fetch the latest headlines for a spoken briefing.

        Use when the user asks what's happening, wants to be caught up, or asks
        for news in one of these areas.

        Args:
            topic: One of "world", "finance", "tech", "science", "india".
        """
        key = topic.strip().lower()
        if key not in BRIEFING_FEEDS:
            return json.dumps(
                {"error": f"Unknown topic '{topic}'.", "topics": sorted(BRIEFING_FEEDS)}
            )
        articles = await fetch_feeds(BRIEFING_FEEDS[key], per_feed=3)
        if not articles:
            return json.dumps({"error": f"No {key} feeds responded. Try again shortly."})
        return json.dumps({"kind": "news", "title": f"{key} briefing", "items": articles[:10]})

    @mcp.tool()
    async def search_news(query: str) -> str:
        """Search recent news coverage about a specific subject, person or company.

        Use for "any news about X" questions. For general facts use search_web.

        Args:
            query: What to look for, e.g. "SpaceX Starship launch".
        """
        try:
            results = await asyncio.to_thread(lambda: DDGS().news(query, max_results=8))
        except Exception:  # ddgs raises its own errors on rate limits / no results
            results = []
        articles = [
            {
                "source": r.get("source", ""),
                "title": clean_text(r.get("title"), 200),
                "summary": clean_text(r.get("body")),
                "link": r.get("url", ""),
                "published": r.get("date"),
            }
            for r in results or []
        ]
        # Newest first; entries with a missing or free-text date go last.
        articles.sort(
            key=lambda a: a["published"] if _is_iso_date(a["published"]) else "", reverse=True
        )

        if not articles:
            # Fallback: headlines only. Google News links are redirects read_page cannot follow.
            url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
            articles = await fetch_feeds({"Google News": url}, per_feed=8)
            for article in articles:
                article["summary"] = ""
                article["link"] = ""
        if not articles:
            return json.dumps({"error": f"No news found for '{query}'."})
        return json.dumps({"kind": "news", "title": f"news: {query}", "items": articles})
