"""Offline tests for the tool helpers (no network, no API keys)."""

import dataclasses

from friday.config import settings
from friday.server import mcp
from friday.tools.feeds import clean_text, parse_feed
from friday.tools.web import MSN_ARTICLE_RE, extract_text, is_public_url

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Feed</title>
  <item>
    <title>First &amp; foremost</title>
    <description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description>
    <link>https://example.com/1</link>
    <pubDate>Thu, 01 Oct 2026 10:00:00 GMT</pubDate>
  </item>
  <item><title></title><link>https://example.com/empty</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom story</title>
    <link href="https://example.com/atom"/>
    <summary>Short summary</summary>
    <updated>2026-10-01T10:00:00Z</updated>
  </entry>
</feed>"""


def test_parse_rss_strips_markup_and_skips_untitled_items():
    articles = parse_feed(RSS, "Test")
    assert len(articles) == 1
    assert articles[0] == {
        "source": "Test",
        "title": "First & foremost",
        "summary": "Hello world",
        "link": "https://example.com/1",
        "published": "2026-10-01T10:00:00+00:00",
    }


def test_parse_atom():
    (article,) = parse_feed(ATOM, "Test")
    assert article["title"] == "Atom story"
    assert article["link"] == "https://example.com/atom"
    assert article["summary"] == "Short summary"
    assert article["published"] == "2026-10-01T10:00:00+00:00"


def test_parse_feed_tolerates_garbage():
    assert parse_feed("<html>not a feed", "Test") == []


def test_clean_text_truncates_on_a_word_boundary():
    text = clean_text("word " * 100, limit=22)
    assert text == "word word word word…"


def test_extract_text_skips_scripts_and_navigation():
    title, text = extract_text(
        "<html><head><title>Page</title><script>var x = 1;</script></head>"
        "<body><nav>Menu</nav><p>Real content</p><style>p{}</style></body></html>"
    )
    assert title == "Page"
    assert text == "Real content"


async def test_is_public_url_rejects_local_and_non_http_targets():
    assert not await is_public_url("http://127.0.0.1:8000/")
    assert not await is_public_url("http://localhost/")
    assert not await is_public_url("http://192.168.1.10/admin")
    assert not await is_public_url("http://[::1]/")
    assert not await is_public_url("file:///etc/passwd")
    assert not await is_public_url("not a url")


async def test_is_public_url_accepts_public_address():
    assert await is_public_url("https://8.8.8.8/")


async def test_all_tools_are_registered():
    names = {tool.name for tool in await mcp.list_tools()}
    assert names == {"get_briefing", "search_news", "search_web", "read_page", "get_datetime"}


def test_msn_article_urls_are_recognised():
    match = MSN_ARTICLE_RE.search(
        "https://www.msn.com/en-in/news/other/some-headline/ar-AA2cPxee?ocid=BingNewsVerp"
    )
    assert match.groups() == ("en-in", "AA2cPxee")
    assert MSN_ARTICLE_RE.search("https://example.com/en-in/news/ar-AA2cPxee") is None


def test_extract_text_prefers_article_content():
    body = "Story sentence. " * 20
    _, text = extract_text(
        "<body><div>HOME WORLD SPORTS</div>"
        f"<article><p>{body}</p></article><div>Related</div></body>"
    )
    assert text == body.strip()


def test_llm_models_setting_is_a_comma_separated_fallback_list():
    custom = dataclasses.replace(settings, llm_model=" model-a , model-b,,")
    assert custom.llm_models == ["model-a", "model-b"]
    assert len(settings.llm_models) >= 1
