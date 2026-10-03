"""Shared async HTTP client for the Technolife API.

Every tool goes through `gql` (GraphQL services) or `fetch` (the two REST map helpers),
which cap concurrency and turn HTTP and GraphQL failures into `ToolError` messages the
model can act on.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

BASE = "https://www.technolife.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0",
    "Accept": "application/json",
}

MAX_CONCURRENCY = 4

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None


class ApiError(ToolError):
    """A failed upstream call."""


class GraphQLError(ApiError):
    """GraphQL `errors` in an HTTP 200 body; the site's answer to an unknown code or url."""


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit
    _transport, _client, _limit = transport, None, None


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # Direct calls are fastest; ignore system proxy settings unless the user opts in
        # with TECHNOLIFE_MCP_PROXY.
        _client = httpx.AsyncClient(
            transport=_transport,
            headers=HEADERS,
            timeout=30,
            follow_redirects=True,
            trust_env=False,
            proxy=os.environ.get("TECHNOLIFE_MCP_PROXY") or None,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def gql(service: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST a GraphQL operation to `/<service>` and return its `data` object.

    GraphQL `errors` come with HTTP 200 (or 400 for invalid variables) and become ApiError.
    """
    body = await fetch(f"{BASE}/{service}", method="POST", json={"query": query, "variables": variables or {}})
    if not isinstance(body, dict):
        raise ApiError(f"Technolife returned an unexpected response from /{service}.")
    if body.get("errors"):
        raise GraphQLError(f"Technolife rejected the request: {_error_text(body)}")
    return body.get("data") or {}


async def fetch(url: str, params: dict[str, Any] | None = None, *, method: str = "GET", json: Any = None) -> Any:
    """Call an endpoint and return the parsed JSON body."""
    client, limit = _get_client()
    r = None
    # Technolife sometimes resets the TLS handshake; one retry after a short pause fixes it.
    for attempt in range(2):
        try:
            async with limit:
                r = await client.request(method, url, params=params, json=json)
            break
        except httpx.TimeoutException as e:
            raise ApiError("www.technolife.com did not answer in time. Try again in a moment.") from e
        except httpx.RequestError as e:
            if attempt == 0 and isinstance(e, httpx.ConnectError):
                await asyncio.sleep(1)
                continue
            raise ApiError(
                f"Could not reach www.technolife.com ({type(e).__name__}). Check the internet connection, "
                "or set TECHNOLIFE_MCP_PROXY."
            ) from e
    assert r is not None

    if r.status_code >= 400:
        raise ApiError(_status_message(r))
    try:
        return r.json()
    except ValueError as e:
        raise ApiError(f"www.technolife.com returned a non-JSON response (HTTP {r.status_code}).") from e


def _status_message(r: httpx.Response) -> str:
    code = r.status_code
    if code == 403:
        return (
            "www.technolife.com blocked the request (HTTP 403). Wait a minute; if it persists, "
            "turn off the VPN or set TECHNOLIFE_MCP_PROXY to another proxy."
        )
    if code == 404:
        return "Not found on www.technolife.com (HTTP 404). Check the product, seller or page code."
    if code == 429:
        return "www.technolife.com is rate limiting requests (HTTP 429). Wait a minute before retrying."
    if code >= 500:
        return f"www.technolife.com had a server error (HTTP {code}). Try again later."
    try:
        detail = _error_text(r.json())
    except ValueError:
        detail = r.text[:200]
    return f"www.technolife.com rejected the request (HTTP {code}): {detail}"


def _error_text(body: Any) -> str:
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            return str(errors[0].get("message"))[:300]
        return str(body.get("message") or body)[:300]
    return str(body)[:300]
