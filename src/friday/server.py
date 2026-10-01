"""Tool server + HUD host.

One local web server that provides:
  /mcp         MCP endpoint (streamable HTTP) the voice agent pulls its tools from
  /            the HUD web page you talk to
  /api/token   mints a LiveKit access token so the HUD can join a room

Run with: uv run friday-server
"""

import secrets
from pathlib import Path

import uvicorn
from livekit import api
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from .config import settings
from .tools import register_all

HUD_DIR = Path(__file__).parent / "hud"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

mcp = FastMCP(
    name="friday",
    instructions="Tools for F.R.I.D.A.Y.: news briefings, web search, page reading and local time.",
    host=settings.host,
    port=settings.port,
)
register_all(mcp)


@mcp.custom_route("/", methods=["GET"])
async def hud_page(request: Request) -> FileResponse:
    return FileResponse(HUD_DIR / "index.html")


@mcp.custom_route("/api/token", methods=["POST"])
async def issue_token(request: Request) -> JSONResponse:
    """Create a fresh room and a token for the HUD to join it."""
    # Tokens grant access to the LiveKit project, so only hand them to this machine.
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    if host not in LOCAL_HOSTS:
        return JSONResponse({"error": "The HUD is only served to localhost."}, status_code=403)

    missing = settings.missing("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
    if missing:
        return JSONResponse(
            {"error": f"Missing in .env: {', '.join(missing)}"}, status_code=500
        )

    room = f"friday-{secrets.token_hex(4)}"
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"user-{secrets.token_hex(3)}")
        .with_name(settings.user_title)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    return JSONResponse({"url": settings.livekit_url, "token": token, "room": room})


def build_app():
    app = mcp.streamable_http_app()
    app.mount("/static", StaticFiles(directory=HUD_DIR), name="static")
    return app


def main() -> None:
    print(f"\n  F.R.I.D.A.Y. tool server\n  HUD   {settings.base_url}/\n  MCP   {settings.mcp_url}\n")
    uvicorn.run(build_app(), host=settings.host, port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
