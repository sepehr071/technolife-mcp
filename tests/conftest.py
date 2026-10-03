import asyncio
import json
import re
import types
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from mcp import Client

from technolife_mcp import http, search
from technolife_mcp.server import mcp

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = datetime(2026, 10, 3, tzinfo=timezone.utc).timestamp()


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def operation(request: httpx.Request) -> str:
    """GraphQL operation name of a request (`query name (...)` or `query { field }`), else the URL path."""
    if request.method != "POST":
        return request.url.path
    m = re.search(r"query\s+(\w+)|\{\s*(\w+)", json.loads(request.content)["query"])
    return m[1] or m[2]


def variables(request: httpx.Request) -> dict:
    return json.loads(request.content)["variables"]


async def live_call(client, name: str, args: dict) -> dict:
    """Call a tool against the real site, about one request per second, and fail on tool errors."""
    await asyncio.sleep(1)
    result = await client.call_tool(name, args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh_http_client():
    """The shared httpx client is bound to one event loop; each test gets a new loop."""
    http.set_transport(None)
    yield
    http.set_transport(None)


@pytest.fixture
def api(monkeypatch):
    """Route table for a fake upstream: api["operation"] = JSON body, or a callable(request) -> httpx.Response.

    GraphQL calls are keyed by operation name (e.g. "search_page_results", "getNavBar"),
    REST calls by URL path. Unknown keys return 404. Every request is appended to
    api.calls so tests can assert on what was sent.
    """

    class Routes(dict):
        calls: list[httpx.Request]

    routes = Routes()
    routes.calls = []
    # Fixture discount deadlines are judged against the day they were recorded.
    monkeypatch.setattr(search, "time", types.SimpleNamespace(time=lambda: RECORDED))

    def handler(request: httpx.Request) -> httpx.Response:
        routes.calls.append(request)
        target = routes.get(operation(request))
        if target is None:
            return httpx.Response(404, json={"error": "no fake route"})
        if callable(target):
            return target(request)
        return httpx.Response(200, json=target)

    http.set_transport(httpx.MockTransport(handler))
    return routes


@pytest.fixture
async def client():
    async with Client(mcp, raise_exceptions=True) as c:
        yield c
