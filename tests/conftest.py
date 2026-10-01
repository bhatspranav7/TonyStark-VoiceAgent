"""Shared fixtures."""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from friday.server import build_app, mcp


async def call_tool(name: str, **arguments):
    """Call an MCP tool in-process and decode its JSON result (plain text otherwise)."""
    result = await mcp.call_tool(name, arguments)
    content = result[0] if isinstance(result, tuple) else result
    text = content[0].text
    try:
        return json.loads(text)
    except ValueError:
        return text


@pytest.fixture
def fake_web(monkeypatch):
    """Route every httpx.AsyncClient request to canned responses instead of the network.

    Returns a dict: map a URL to an httpx.Response (or a callable taking the request).
    Unmapped URLs answer 404. `fake_web.requests` lists the URLs that were asked for.
    """

    class Routes(dict):
        requests: list[str]

    routes = Routes()
    routes.requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        routes.requests.append(url)
        response = routes.get(url, httpx.Response(404))
        return response(request) if callable(response) else response

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    return routes


@pytest.fixture(scope="session")
def live_server():
    """The real tool server + HUD on a free local port; yields its base URL."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(build_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("tool server did not start")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)
