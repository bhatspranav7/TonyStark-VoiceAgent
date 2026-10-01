"""The real server over real HTTP: MCP protocol and the HUD on one port."""

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def test_mcp_client_can_list_and_call_tools(live_server):
    async with streamable_http_client(f"{live_server}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert set(tools) == {
                "get_briefing",
                "search_news",
                "search_web",
                "read_page",
                "get_datetime",
            }
            # The model only sees these descriptions and schemas, so they must exist.
            assert all(tool.description for tool in tools.values())
            assert tools["read_page"].inputSchema["required"] == ["url"]
            assert tools["get_briefing"].inputSchema["properties"]["topic"]["default"] == "world"

            result = await session.call_tool("get_datetime", {})
            assert not result.isError
            assert "20" in result.content[0].text

            refused = await session.call_tool("read_page", {"url": "http://127.0.0.1/"})
            assert "not a public web address" in refused.content[0].text


async def test_hud_is_served_next_to_mcp(live_server):
    async with httpx.AsyncClient(base_url=live_server) as http:
        assert "F.R.I.D.A.Y." in (await http.get("/")).text
        assert (await http.get("/static/hud.js")).status_code == 200


async def test_mcp_endpoint_rejects_foreign_host_headers(live_server):
    """DNS-rebinding protection: a browser page on another origin cannot drive the tools."""
    async with httpx.AsyncClient(base_url=live_server) as http:
        response = await http.post(
            "/mcp",
            headers={"Host": "evil.example", "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code in (403, 421)
