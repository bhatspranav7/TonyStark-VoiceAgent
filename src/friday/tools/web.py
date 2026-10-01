"""Web tools — live search and a readable-text page fetcher."""

import asyncio
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from ddgs import DDGS

from .feeds import USER_AGENT, clean_text

MAX_PAGE_CHARS = 5000
MAX_PAGE_BYTES = 2_000_000
MAX_REDIRECTS = 5
MIN_MAIN_CHARS = 200

MSN_ARTICLE_RE = re.compile(r"^https://www\.msn\.com/([a-z]{2}-[a-z]{2})/.+/ar-([A-Za-z0-9]+)")
MSN_CONTENT_API = "https://assets.msn.com/content/view/v2/Detail/{locale}/{id}"


class _TextExtractor(HTMLParser):
    """Collects visible text and the <title>, skipping non-content elements."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}
    MAIN = {"article", "main"}

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.parts: list[str] = []
        self.main_parts: list[str] = []
        self._skip_depth = 0
        self._main_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.MAIN:
            self._main_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.MAIN and self._main_depth:
            self._main_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth and data.strip():
            self.parts.append(data.strip())
            if self._main_depth:
                self.main_parts.append(data.strip())


def extract_text(html_text: str) -> tuple[str, str]:
    """Return (title, readable text) for an HTML document.

    Prefers the text inside <article>/<main> when the page has a meaningful amount
    there, which drops menus and sidebars that are built from plain <div>s.
    """
    parser = _TextExtractor()
    parser.feed(html_text)
    main_text = " ".join(parser.main_parts)
    text = main_text if len(main_text) >= MIN_MAIN_CHARS else " ".join(parser.parts)
    return parser.title.strip(), text


async def is_public_url(url: str) -> bool:
    """True for http(s) URLs whose host resolves only to public addresses.

    The model chooses which URLs to read, so this keeps it away from localhost
    and private-network services.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname, None, type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        return False
    return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


class PageError(Exception):
    """A page could not be read, with a message fit to hand back to the model."""


async def _read_html_page(client: httpx.AsyncClient, url: str) -> dict:
    # Follow redirects by hand so every hop gets the public-address check.
    for _ in range(MAX_REDIRECTS + 1):
        if not await is_public_url(url):
            raise PageError("That URL is not a public web address.")
        response = await client.get(url)
        if not response.is_redirect:
            break
        url = str(response.next_request.url)
    else:
        raise PageError("Too many redirects.")
    response.raise_for_status()

    body = response.text[:MAX_PAGE_BYTES]
    if "html" in response.headers.get("content-type", ""):
        title, text = extract_text(body)
    else:
        title, text = "", body
    return {
        "title": clean_text(title, 160) or url,
        "link": str(response.url),
        "text": clean_text(text, MAX_PAGE_CHARS),
    }


async def _read_msn_article(client: httpx.AsyncClient, url: str) -> dict | None:
    """MSN renders articles with JavaScript; its content API returns the text directly.

    News search results are mostly MSN links, so this is what makes them readable.
    Returns None for non-MSN URLs or if the API does not cooperate.
    """
    match = MSN_ARTICLE_RE.search(url)
    if not match:
        return None
    locale, article_id = match.groups()
    try:
        response = await client.get(MSN_CONTENT_API.format(locale=locale, id=article_id))
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    _, text = extract_text(data.get("body") or "")
    if not text:
        return None
    return {
        "title": clean_text(data.get("title"), 160) or url,
        "link": url,
        "text": clean_text(text, MAX_PAGE_CHARS),
    }


def register(mcp) -> None:
    @mcp.tool()
    async def search_web(query: str) -> str:
        """Search the web and return the top results with short snippets.

        Use for facts, current information, or anything you are not sure about.

        Args:
            query: The search query.
        """
        try:
            results = await asyncio.to_thread(lambda: DDGS().text(query, max_results=6))
        except Exception as exc:  # ddgs raises its own errors on rate limits / no results
            return json.dumps({"error": f"Search failed: {exc}"})
        items = [
            {
                "title": clean_text(r.get("title"), 160),
                "summary": clean_text(r.get("body"), 300),
                "link": r.get("href", ""),
                "source": urlparse(r.get("href", "")).netloc.removeprefix("www."),
            }
            for r in results or []
        ]
        if not items:
            return json.dumps({"error": f"No results for '{query}'."})
        return json.dumps({"kind": "search", "title": query, "items": items})

    @mcp.tool()
    async def read_page(url: str) -> str:
        """Fetch a web page and return its readable text.

        Use after search_web, search_news or a briefing when the user wants details
        from a specific article or link.

        Args:
            url: Full http(s) URL of the page.
        """
        try:
            async with httpx.AsyncClient(timeout=12, headers={"User-Agent": USER_AGENT}) as client:
                page = await _read_msn_article(client, url) or await _read_html_page(client, url)
        except PageError as exc:
            return json.dumps({"error": str(exc)})
        except httpx.HTTPStatusError as exc:
            return json.dumps({"error": f"The site returned HTTP {exc.response.status_code}."})
        except httpx.HTTPError as exc:
            return json.dumps({"error": f"Could not load the page: {type(exc).__name__}"})

        if not page["text"]:
            return json.dumps(
                {"error": "The page had no readable text. Try search_web for the headline instead."}
            )
        return json.dumps({"kind": "page", **page})
