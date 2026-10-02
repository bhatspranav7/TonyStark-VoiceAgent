"""Tool server + HUD host.

One local web server that provides:
  /mcp         MCP endpoint (streamable HTTP) the voice agent pulls its tools from
  /            the HUD web page you talk to
  /api/token   mints a LiveKit access token so the HUD can join a room

Run with: uv run friday-server
"""

import uvicorn
from mcp.server.fastmcp import FastMCP

from .config import settings
from .hudapp import hud_routes
from .tools import register_all

mcp = FastMCP(
    name="friday",
    instructions="Tools for F.R.I.D.A.Y.: news briefings, web search, page reading and local time.",
    host=settings.host,
    port=settings.port,
    log_level="WARNING",
)
register_all(mcp)


def build_app():
    app = mcp.streamable_http_app()
    app.routes.extend(hud_routes())
    return app


def main() -> None:
    print(
        f"\n  F.R.I.D.A.Y. tool server\n  HUD   {settings.base_url}/\n  MCP   {settings.mcp_url}\n"
    )
    uvicorn.run(build_app(), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
