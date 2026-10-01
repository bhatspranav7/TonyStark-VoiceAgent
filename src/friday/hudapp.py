"""The HUD web app: the page, its static files and the LiveKit token endpoint.

It is mounted into the local tool server (see server.py) and can also be deployed
on its own, e.g. to Vercel, so the HUD opens from any device while the voice agent
keeps running on your machine.
"""

import hmac
import ipaddress
import json
import secrets
from pathlib import Path

from livekit import api
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .config import settings

HUD_DIR = Path(__file__).parent / "hud"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


async def hud_page(request: Request) -> FileResponse:
    return FileResponse(HUD_DIR / "index.html")


def _is_local(request: Request) -> bool:
    """True when the request comes from this machine to a localhost address."""
    if settings.on_vercel or request.client is None:
        return False
    try:
        from_loopback = ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False
    # The Host check stops a web page on another origin reaching us via DNS rebinding.
    host = request.headers.get("host", "").rsplit(":", 1)[0]
    return from_loopback and host in LOCAL_HOSTS


async def _submitted_code(request: Request) -> str:
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        return ""
    code = body.get("code", "") if isinstance(body, dict) else ""
    return code if isinstance(code, str) else ""


async def issue_token(request: Request) -> JSONResponse:
    """Create a fresh room and a token for the HUD to join it.

    A token lets the holder talk to the agent and spend the project's quota, so it
    is handed out freely only to this machine; anyone else needs the access code.
    """
    if not _is_local(request):
        if not settings.access_code:
            return JSONResponse(
                {"error": "Remote access is off. Set FRIDAY_ACCESS_CODE to enable it."},
                status_code=403,
            )
        code = await _submitted_code(request)
        if not hmac.compare_digest(code.encode(), settings.access_code.encode()):
            message = "Wrong access code." if code else "Access code required."
            return JSONResponse({"error": message, "needs_code": True}, status_code=401)

    required = {
        "LIVEKIT_URL": settings.livekit_url,
        "LIVEKIT_API_KEY": settings.livekit_api_key,
        "LIVEKIT_API_SECRET": settings.livekit_api_secret,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return JSONResponse(
            {"error": f"Server is missing settings: {', '.join(missing)}"}, status_code=500
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


def hud_routes() -> list:
    return [
        Route("/", hud_page),
        Route("/api/token", issue_token, methods=["POST"]),
        Mount("/static", StaticFiles(directory=HUD_DIR), name="static"),
    ]


app = Starlette(routes=hud_routes())
