"""Tools called end to end with the network replaced by canned responses."""

import httpx
import pytest

from friday.tools import news, web
from friday.tools.news import BRIEFING_FEEDS

from .conftest import call_tool


def rss(*titles: str) -> httpx.Response:
    items = "".join(
        f"<item><title>{t}</title><description>About {t}</description>"
        f"<link>https://example.com/{i}</link></item>"
        for i, t in enumerate(titles)
    )
    return httpx.Response(200, text=f"<rss><channel>{items}</channel></rss>")


def html(body: str, title: str = "Title") -> httpx.Response:
    return httpx.Response(
        200,
        text=f"<html><head><title>{title}</title></head><body>{body}</body></html>",
        headers={"content-type": "text/html; charset=utf-8"},
    )


# A public IP literal, so is_public_url passes without a DNS lookup.
PUBLIC = "https://93.184.216.34"


# ---------- get_briefing ----------


async def test_briefing_interleaves_sources_and_survives_a_dead_feed(fake_web):
    feeds = BRIEFING_FEEDS["world"]
    fake_web[feeds["BBC"]] = rss("BBC one", "BBC two")
    fake_web[feeds["Al Jazeera"]] = rss("AJ one", "BBC one")  # duplicate headline
    fake_web[feeds["The Guardian"]] = httpx.Response(500)
    fake_web[feeds["NPR"]] = httpx.Response(200, text="<html>not a feed")

    result = await call_tool("get_briefing", topic="world")

    assert result["kind"] == "news"
    assert [(i["source"], i["title"]) for i in result["items"]] == [
        ("BBC", "BBC one"),
        ("Al Jazeera", "AJ one"),
        ("BBC", "BBC two"),
    ]
    assert result["items"][0]["summary"] == "About BBC one"


async def test_briefing_topic_is_case_insensitive(fake_web):
    fake_web[BRIEFING_FEEDS["tech"]["The Verge"]] = rss("Chip news")
    result = await call_tool("get_briefing", topic=" Tech ")
    assert result["items"][0]["title"] == "Chip news"


async def test_briefing_reports_when_every_feed_is_down(fake_web):
    result = await call_tool("get_briefing", topic="science")
    assert "error" in result


async def test_briefing_rejects_unknown_topic(fake_web):
    result = await call_tool("get_briefing", topic="sports")
    assert "Unknown topic" in result["error"]
    assert result["topics"] == sorted(BRIEFING_FEEDS)
    assert fake_web.requests == []


async def test_briefing_caps_the_number_of_items(fake_web):
    for url in BRIEFING_FEEDS["world"].values():
        fake_web[url] = rss(*(f"{url} story {n}" for n in range(8)))
    result = await call_tool("get_briefing", topic="world")
    assert len(result["items"]) == 10


# ---------- read_page ----------


async def test_read_page_returns_article_text(fake_web):
    fake_web[f"{PUBLIC}/story"] = html("<nav>Menu</nav><p>The actual story.</p>", "Big Story")
    result = await call_tool("read_page", url=f"{PUBLIC}/story")
    assert result == {
        "kind": "page",
        "title": "Big Story",
        "link": f"{PUBLIC}/story",
        "text": "The actual story.",
    }


async def test_read_page_follows_public_redirects(fake_web):
    fake_web[f"{PUBLIC}/old"] = httpx.Response(301, headers={"location": f"{PUBLIC}/new"})
    fake_web[f"{PUBLIC}/new"] = html("<p>Moved here.</p>")
    result = await call_tool("read_page", url=f"{PUBLIC}/old")
    assert result["text"] == "Moved here."
    assert result["link"] == f"{PUBLIC}/new"


@pytest.mark.parametrize(
    "target",
    [
        "http://127.0.0.1:8000/api/token",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
    ],
)
async def test_read_page_refuses_redirects_into_private_addresses(fake_web, target):
    fake_web[f"{PUBLIC}/trap"] = httpx.Response(302, headers={"location": target})
    result = await call_tool("read_page", url=f"{PUBLIC}/trap")
    assert result == {"error": "That URL is not a public web address."}
    assert fake_web.requests == [f"{PUBLIC}/trap"]  # the private URL was never requested


async def test_read_page_gives_up_on_redirect_loops(fake_web):
    fake_web[f"{PUBLIC}/loop"] = httpx.Response(302, headers={"location": f"{PUBLIC}/loop"})
    result = await call_tool("read_page", url=f"{PUBLIC}/loop")
    assert result == {"error": "Too many redirects."}


async def test_read_page_reports_http_errors_briefly(fake_web):
    result = await call_tool("read_page", url=f"{PUBLIC}/missing")
    assert result == {"error": "The site returned HTTP 404."}


async def test_read_page_reports_pages_with_no_text(fake_web):
    fake_web[f"{PUBLIC}/app"] = html("<script>render()</script>")
    result = await call_tool("read_page", url=f"{PUBLIC}/app")
    assert "no readable text" in result["error"]


async def test_read_page_reports_network_failures(fake_web):
    def boom(request):
        raise httpx.ConnectTimeout("timed out")

    fake_web[f"{PUBLIC}/slow"] = boom
    result = await call_tool("read_page", url=f"{PUBLIC}/slow")
    assert result == {"error": "Could not load the page: ConnectTimeout"}


async def test_read_page_truncates_long_pages(fake_web):
    fake_web[f"{PUBLIC}/long"] = html(f"<p>{'word ' * 5000}</p>")
    result = await call_tool("read_page", url=f"{PUBLIC}/long")
    assert len(result["text"]) <= web.MAX_PAGE_CHARS + 1
    assert result["text"].endswith("…")


async def test_read_page_uses_the_msn_content_api(fake_web):
    article = "https://www.msn.com/en-in/news/other/some-headline/ar-AA2cPxee?ocid=x"
    fake_web["https://assets.msn.com/content/view/v2/Detail/en-in/AA2cPxee"] = httpx.Response(
        200, json={"title": "MSN headline", "body": "<p>Full article body.</p>"}
    )
    result = await call_tool("read_page", url=article)
    assert result == {
        "kind": "page",
        "title": "MSN headline",
        "link": article,
        "text": "Full article body.",
    }


# ---------- search_web / search_news ----------


class FakeDDGS:
    text_results: list = []
    news_results: list = []
    error: Exception | None = None

    def text(self, query, max_results):
        if self.error:
            raise self.error
        return self.text_results

    def news(self, query, max_results):
        if self.error:
            raise self.error
        return self.news_results


@pytest.fixture
def fake_search(monkeypatch):
    FakeDDGS.text_results, FakeDDGS.news_results, FakeDDGS.error = [], [], None
    monkeypatch.setattr(web, "DDGS", FakeDDGS)
    monkeypatch.setattr(news, "DDGS", FakeDDGS)
    return FakeDDGS


async def test_search_web_shapes_results(fake_search):
    fake_search.text_results = [
        {
            "title": "Python 3.14",
            "body": "Released <b>today</b>",
            "href": "https://www.python.org/x",
        }
    ]
    result = await call_tool("search_web", query="python release")
    assert result == {
        "kind": "search",
        "title": "python release",
        "items": [
            {
                "title": "Python 3.14",
                "summary": "Released today",
                "link": "https://www.python.org/x",
                "source": "python.org",
            }
        ],
    }


async def test_search_web_reports_no_results_and_failures(fake_search):
    assert "No results" in (await call_tool("search_web", query="zzz"))["error"]
    fake_search.error = RuntimeError("rate limited")
    assert "rate limited" in (await call_tool("search_web", query="zzz"))["error"]


async def test_search_news_sorts_newest_first_with_undated_last(fake_search):
    fake_search.news_results = [
        {
            "title": "Old",
            "body": "b",
            "url": "https://a/1",
            "source": "A",
            "date": "2026-09-01T00:00:00+00:00",
        },
        {
            "title": "Undated",
            "body": "b",
            "url": "https://a/2",
            "source": "A",
            "date": "Opinion8 d",
        },
        {
            "title": "New",
            "body": "b",
            "url": "https://a/3",
            "source": "A",
            "date": "2026-09-30T00:00:00+00:00",
        },
    ]
    result = await call_tool("search_news", query="x")
    assert [i["title"] for i in result["items"]] == ["New", "Old", "Undated"]


async def test_search_news_falls_back_to_headlines_when_search_fails(fake_search, fake_web):
    fake_search.error = RuntimeError("blocked")
    fake_web["https://news.google.com/rss/search?q=space+launch&hl=en-IN&gl=IN&ceid=IN:en"] = rss(
        "Rocket goes up"
    )
    result = await call_tool("search_news", query="space launch")
    (item,) = result["items"]
    assert item["title"] == "Rocket goes up"
    assert item["link"] == ""  # Google News links are unreadable redirects, so none is offered


async def test_search_news_reports_nothing_found(fake_search, fake_web):
    result = await call_tool("search_news", query="nothing")
    assert "No news found" in result["error"]


# ---------- get_datetime ----------


async def test_get_datetime_is_human_readable():
    text = await call_tool("get_datetime")
    assert isinstance(text, str) and any(
        day in text
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    )
