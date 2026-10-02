"""The HUD web app: page, static files, and who may get a LiveKit token."""

import dataclasses

import httpx
import jwt
import pytest

from friday import hudapp
from friday.config import settings

API_KEY = "APItestkey"
API_SECRET = "test-secret-that-is-long-enough-for-hs256"
LOOPBACK = ("127.0.0.1", 50000)
REMOTE = ("203.0.113.9", 50000)


@pytest.fixture
def configure(monkeypatch):
    """Replace the app's settings; LiveKit credentials are fake unless overridden."""

    def apply(**overrides):
        values = {
            "livekit_url": "wss://test.livekit.cloud",
            "livekit_api_key": API_KEY,
            "livekit_api_secret": API_SECRET,
            "access_code": "",
            "on_vercel": False,
            "user_title": "boss",
            **overrides,
        }
        monkeypatch.setattr(hudapp, "settings", dataclasses.replace(settings, **values))

    apply()
    return apply


def client(peer=LOOPBACK, host="127.0.0.1:8000") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=hudapp.app, client=peer), base_url=f"http://{host}"
    )


# ---------- page + static ----------


async def test_hud_page_and_assets_are_served(configure):
    async with client() as http:
        page = await http.get("/")
        assert page.status_code == 200
        assert "F.R.I.D.A.Y." in page.text
        for asset in ("/static/hud.js", "/static/hud.css"):
            assert asset in page.text
            assert (await http.get(asset)).status_code == 200


async def test_browsers_are_told_to_check_for_updated_hud_files(configure):
    async with client() as http:
        for path in ("/", "/static/hud.js", "/static/hud.css"):
            response = await http.get(path)
            assert response.headers["cache-control"] == "no-cache", path

        # ...and for the script and stylesheet a repeat visit is a cheap "not modified".
        for path in ("/static/hud.js", "/static/hud.css"):
            etag = (await http.get(path)).headers["etag"]
            repeat = await http.get(path, headers={"If-None-Match": etag})
            assert repeat.status_code == 304, path
            assert repeat.headers["cache-control"] == "no-cache", path


async def test_static_does_not_serve_files_outside_the_hud_folder(configure):
    async with client() as http:
        response = await http.get("/static/../config.py")
        assert response.status_code == 404
        assert (await http.get("/static/%2e%2e/config.py")).status_code == 404


async def test_token_endpoint_is_post_only(configure):
    async with client() as http:
        assert (await http.get("/api/token")).status_code == 405


# ---------- token: local ----------


async def test_local_request_gets_a_valid_room_token(configure):
    async with client() as http:
        response = await http.post("/api/token")
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "wss://test.livekit.cloud"
    assert body["room"].startswith("friday-")

    claims = jwt.decode(body["token"], API_SECRET, algorithms=["HS256"])
    assert claims["iss"] == API_KEY
    assert claims["name"] == "boss"
    assert claims["sub"].startswith("user-")
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["room"] == body["room"]  # valid for this room only


async def test_each_token_is_for_a_new_room(configure):
    async with client() as http:
        rooms = {(await http.post("/api/token")).json()["room"] for _ in range(5)}
    assert len(rooms) == 5


async def test_missing_livekit_settings_are_reported_not_leaked(configure):
    configure(livekit_api_secret="")
    async with client() as http:
        response = await http.post("/api/token")
    assert response.status_code == 500
    assert response.json() == {"error": "Server is missing settings: LIVEKIT_API_SECRET"}


# ---------- token: who counts as local ----------


@pytest.mark.parametrize(
    ("peer", "host"),
    [
        (REMOTE, "203.0.113.9:8000"),  # someone else on the network
        (REMOTE, "localhost:8000"),  # remote peer faking the Host header
        (LOOPBACK, "evil.example:8000"),  # DNS rebinding: local peer, foreign Host
    ],
)
async def test_non_local_requests_are_refused_when_no_access_code_is_set(configure, peer, host):
    async with client(peer, host) as http:
        response = await http.post("/api/token")
    assert response.status_code == 403
    assert "token" not in response.json()


async def test_on_vercel_nothing_counts_as_local(configure):
    configure(on_vercel=True)
    async with client(LOOPBACK, "localhost") as http:
        assert (await http.post("/api/token")).status_code == 403


# ---------- token: access code ----------


async def test_remote_request_needs_the_access_code(configure):
    configure(access_code="open-sesame")
    async with client(REMOTE, "friday.example") as http:
        missing = await http.post("/api/token")
        wrong = await http.post("/api/token", json={"code": "guess"})
        right = await http.post("/api/token", json={"code": "open-sesame"})

    assert missing.status_code == 401
    assert missing.json() == {"error": "Access code required.", "needs_code": True}
    assert wrong.status_code == 401
    assert wrong.json() == {"error": "Wrong access code.", "needs_code": True}
    assert right.status_code == 200
    assert "token" in right.json()


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"code": 5}', b'{"code": null}', b'"x"'])
async def test_malformed_access_code_bodies_are_rejected_cleanly(configure, body):
    configure(access_code="open-sesame")
    async with client(REMOTE, "friday.example") as http:
        response = await http.post("/api/token", content=body)
    assert response.status_code == 401


async def test_local_request_does_not_need_the_access_code(configure):
    configure(access_code="open-sesame")
    async with client() as http:
        assert (await http.post("/api/token")).status_code == 200
