"""RSS / Atom fetching and parsing shared by the news tools."""

import asyncio
import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import ParseError

import httpx
from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

USER_AGENT = "Mozilla/5.0 (compatible; FridayVoiceAgent/0.1)"
ATOM = "{http://www.w3.org/2005/Atom}"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str | None, limit: int = 220) -> str:
    """Strip markup and collapse whitespace; cut at `limit` characters."""
    if not raw:
        return ""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", html.unescape(raw)))).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def parse_feed(xml_text: str, source: str) -> list[dict]:
    """Parse an RSS 2.0 or Atom document into a list of article dicts."""
    try:
        # Feeds are untrusted input: defusedxml rejects entity-expansion attacks.
        root = fromstring(xml_text)
    except (ParseError, DefusedXmlException):
        return []

    articles: list[dict] = []
    for item in root.iter("item"):
        published = _parse_date(item.findtext("pubDate"))
        articles.append(
            {
                "source": clean_text(item.findtext("source")) or source,
                "title": clean_text(item.findtext("title"), 200),
                "summary": clean_text(item.findtext("description")),
                "link": (item.findtext("link") or "").strip(),
                "published": published.isoformat() if published else None,
            }
        )
    for entry in root.iter(f"{ATOM}entry"):
        link_el = entry.find(f"{ATOM}link")
        published = _parse_date(
            entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")
        )
        articles.append(
            {
                "source": source,
                "title": clean_text(entry.findtext(f"{ATOM}title"), 200),
                "summary": clean_text(
                    entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content")
                ),
                "link": link_el.get("href", "") if link_el is not None else "",
                "published": published.isoformat() if published else None,
            }
        )
    return [a for a in articles if a["title"]]


async def fetch_feed(client: httpx.AsyncClient, source: str, url: str) -> list[dict]:
    """Fetch one feed; a feed that is down or malformed yields no articles."""
    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return []
    return parse_feed(response.text, source)


async def fetch_feeds(feeds: dict[str, str], per_feed: int = 4) -> list[dict]:
    """Fetch several feeds at once and interleave them, newest first per source."""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=10, headers={"User-Agent": USER_AGENT}
    ) as client:
        results = await asyncio.gather(
            *(fetch_feed(client, source, url) for source, url in feeds.items())
        )

    # Round-robin across sources so one prolific outlet doesn't crowd out the rest.
    merged: list[dict] = []
    seen: set[str] = set()
    for rank in range(per_feed):
        for articles in results:
            if rank < len(articles):
                key = articles[rank]["title"].lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(articles[rank])
    return merged
