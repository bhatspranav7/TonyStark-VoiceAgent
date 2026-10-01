"""Live tests: real news feeds, real search, real Gemini.

Skipped by default. Run with:  uv run pytest -m live
The agent test needs GOOGLE_API_KEY in .env and uses a little free-tier quota.
"""

import os

import pytest

from friday.tools.feeds import fetch_feeds
from friday.tools.news import BRIEFING_FEEDS

from .conftest import call_tool

pytestmark = pytest.mark.live


@pytest.mark.parametrize("topic", sorted(BRIEFING_FEEDS))
async def test_every_briefing_topic_has_working_feeds(topic):
    feeds = BRIEFING_FEEDS[topic]
    articles = await fetch_feeds(feeds, per_feed=2)
    sources = {a["source"] for a in articles}
    # One outlet being down is normal; most of them failing means the feed list has rotted.
    assert len(sources) >= max(2, len(feeds) - 1), f"only {sources} responded for {topic}"
    assert all(a["title"] and a["link"].startswith("http") for a in articles)


async def test_search_web_returns_results():
    result = await call_tool("search_web", query="Python programming language")
    assert result["kind"] == "search" and len(result["items"]) >= 3


async def test_search_news_returns_readable_links():
    result = await call_tool("search_news", query="technology")
    assert result["items"] and all(i["link"].startswith("http") for i in result["items"])


async def test_read_page_reads_a_real_page():
    result = await call_tool("read_page", url="https://example.com")
    assert result["title"] == "Example Domain" and "documentation" in result["text"]


@pytest.mark.skipif(not os.getenv("GOOGLE_API_KEY"), reason="GOOGLE_API_KEY not set")
async def test_friday_uses_the_briefing_tool_and_stays_in_character(live_server):
    from livekit.agents import AgentSession, mcp

    from friday.agent import Friday, build_llm

    tools = mcp.MCPServerHTTP(
        url=f"{live_server}/mcp",
        transport_type="streamable_http",
        client_session_timeout_seconds=30,
    )
    model = build_llm()
    async with AgentSession(llm=model, mcp_servers=[tools], max_tool_steps=5) as session:
        await session.start(Friday())

        result = await session.run(user_input="What's happening in tech today?")
        result.expect.contains_function_call(name="get_briefing", arguments={"topic": "tech"})
        await result.expect.contains_message(role="assistant").judge(
            model,
            intent="Summarises a few technology news stories in plain spoken sentences, "
            "without markdown, bullet points or URLs.",
        )

        result = await session.run(user_input="What is 12 times 12?")
        await result.expect.contains_message(role="assistant").judge(
            model, intent="Says the answer is 144, briefly."
        )
