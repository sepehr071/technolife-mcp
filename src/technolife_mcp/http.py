"""Shared async HTTP client for the Technolife API.

Every tool goes through `gql` (GraphQL services) or `fetch` (the two REST map helpers),
which cap concurrency and turn HTTP and GraphQL failures into `ToolError` messages the
model can act on.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from typing import Any

import httpx
from httpx_curl_cffi import AsyncCurlTransport
from mcp.server.mcpserver.exceptions import ToolError

BASE = "https://www.technolife.com"

HEADERS = {
    # User-Agent, sec-ch-ua and TLS come from the impersonated Chrome profile (see _get_client).
    "Accept": "application/json",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Referer": f"{BASE}/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "priority": "u=1, i",
}

MAX_CONCURRENCY = 2
JITTER = (0.15, 0.6)  # seconds before each uncached call
MAX_RETRIES = 2
MAX_RETRY_WAIT = 10  # cap for Retry-After and backoff, seconds
RETRY_DELAY = 0.5

_transport: httpx.AsyncBaseTransport | None = None
_client: httpx.AsyncClient | None = None
_limit: asyncio.Semaphore | None = None
_proxy_index = 0
_retired: set[asyncio.Task] = set()
_browser_lock: asyncio.Lock | None = None
_cleared: tuple[httpx.AsyncClient, float] | None = None
_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
CACHE_MAX = 16
CACHE_TTL = 300  # nav tree and home landing change rarely


class _XhrTransport(AsyncCurlTransport):
    """The Chrome profile sends navigation-only headers; a None value makes curl drop them (API calls are XHR)."""

    def _create_request_params(self, req: httpx.Request) -> dict[str, Any]:
        p = super()._create_request_params(req)
        p["headers"] = [*p["headers"], (b"upgrade-insecure-requests", None), (b"sec-fetch-user", None)]
        return p


class ApiError(ToolError):
    """A failed upstream call. `status` is the HTTP status, or None for network errors."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class GraphQLError(ApiError):
    """GraphQL `errors` in an HTTP 200 body; the site's answer to an unknown code or url."""


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Swap the transport (tests use httpx.MockTransport). Drops the current client."""
    global _transport, _client, _limit, _proxy_index, _browser_lock, _cleared
    _transport, _client, _limit, _proxy_index, _browser_lock, _cleared = transport, None, None, 0, None, None
    _cache.clear()


def _proxies() -> list[str]:
    """TECHNOLIFE_MCP_PROXY: one proxy URL, or a comma-separated list used one at a time."""
    return [p.strip() for p in os.environ.get("TECHNOLIFE_MCP_PROXY", "").split(",") if p.strip()]


# A bare HTML 403 is a normal refusal; only a page with a bot-check marker is a challenge.
_CHALLENGE = re.compile(r"just a moment|captcha|challenge|arvan|attention required|enable javascript", re.I)


def _is_challenge(r: httpx.Response) -> bool:
    """A bot-check page: 403/429/503 with an HTML body that carries a known challenge marker."""
    return (
        r.status_code in (403, 429, 503)
        and "html" in r.headers.get("content-type", "") + r.text[:20].lower()
        and bool(_CHALLENGE.search(r.text[:5000]))
    )


def _next_proxy(client: httpx.AsyncClient) -> None:
    """Sticky pool: move to the next proxy after a block or connect error; the next call rebuilds the client.

    Only the client that failed may rotate: a slower request that failed on an old client must not skip a good proxy.
    The old client is closed late because other requests may still be using it.
    """
    global _client, _limit, _proxy_index
    if len(_proxies()) < 2 or client is not _client:
        return
    _client, _limit, _proxy_index = None, None, _proxy_index + 1
    t = asyncio.create_task(_close_later(client))
    _retired.add(t)
    t.add_done_callback(_retired.discard)


async def _close_later(client: httpx.AsyncClient) -> None:
    await asyncio.sleep(30)  # longer than the 30 s request timeout
    await client.aclose()


def _get_client() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    global _client, _limit
    if _client is None:
        # Direct calls are fastest; ignore system proxy settings unless the user opts in
        # with TECHNOLIFE_MCP_PROXY. curl_cffi presents Chrome's TLS/HTTP2 fingerprint and default
        # headers; cookies and redirects stay with httpx. The proxy goes to the transport (a
        # client-level proxy would be ignored once a transport is given).
        proxies = _proxies()
        _client = httpx.AsyncClient(
            transport=_transport
            or _XhrTransport(
                impersonate="chrome",
                default_headers=True,
                proxy=proxies[_proxy_index % len(proxies)] if proxies else None,
                max_connections=2 * MAX_CONCURRENCY,
            ),
            headers=HEADERS,
            timeout=30,
            limits=httpx.Limits(max_connections=2 * MAX_CONCURRENCY),
            follow_redirects=True,
            trust_env=False,
        )
        _limit = asyncio.Semaphore(MAX_CONCURRENCY)
    assert _limit is not None
    return _client, _limit


async def gql(service: str, query: str, variables: dict[str, Any] | None = None, *, ttl: float = 0) -> dict[str, Any]:
    """POST a GraphQL operation to `/<service>` and return its `data` object.

    GraphQL `errors` come with HTTP 200 (or 400 for invalid variables) and become ApiError.
    ttl > 0 caches the answer in memory for that many seconds (keyed on all arguments); callers
    must treat a cached result as read-only.
    """
    key = (service, query, json.dumps(variables, sort_keys=True)) if ttl else None
    if key and (hit := _cache.get(key)) and time.monotonic() - hit[0] < ttl:
        return hit[1]
    body = await fetch(f"{BASE}/{service}", method="POST", json={"query": query, "variables": variables or {}})
    if not isinstance(body, dict):
        raise ApiError(f"Technolife returned an unexpected response from /{service}.")
    if body.get("errors"):
        raise GraphQLError(f"Technolife rejected the request: {_error_text(body)}")
    data = body.get("data") or {}
    if key:
        if len(_cache) >= CACHE_MAX:
            _cache.clear()
        _cache[key] = (time.monotonic(), data)
    return data


async def fetch(url: str, params: dict[str, Any] | None = None, *, method: str = "GET", json: Any = None) -> Any:
    """Call an endpoint and return the parsed JSON body.

    A timeout, network error, 5xx or 429 is retried up to MAX_RETRIES times with jittered exponential backoff,
    or after Retry-After when sent (the calls are idempotent reads). Other 4xx (403 too) are never retried.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await _request(method, url, params, json)
        except ApiError as e:
            if attempt == MAX_RETRIES or (e.status is not None and e.status < 500 and e.status != 429):
                raise
            wait = e.retry_after if e.retry_after is not None else RETRY_DELAY * 2**attempt * random.uniform(1, 1.5)
            await asyncio.sleep(min(wait, MAX_RETRY_WAIT))


async def _send(
    client: httpx.AsyncClient, limit: asyncio.Semaphore, method: str, url: str, params: Any, json: Any
) -> httpx.Response:
    # Browsers send Origin on same-origin POSTs only.
    headers = {"Origin": BASE} if method != "GET" else None
    try:
        async with limit:
            await asyncio.sleep(random.uniform(*JITTER))
            return await client.request(method, url, params=params, json=json, headers=headers)
    except httpx.TimeoutException as e:
        raise ApiError("www.technolife.com did not answer in time. Try again in a moment.") from e
    except httpx.RequestError as e:
        if isinstance(e, httpx.ConnectError | httpx.ProxyError):
            _next_proxy(client)
        raise ApiError(
            f"Could not reach www.technolife.com ({type(e).__name__}). Check the internet connection, "
            "or set TECHNOLIFE_MCP_PROXY."
        ) from e


async def _browser_cookies(proxy: str | None) -> list[dict[str, Any]]:
    """Open the home page in headless patchright, wait for the challenge to clear, return the cookies."""
    try:
        from patchright.async_api import async_playwright
    except ImportError as e:
        raise ApiError(
            "Technolife served a bot-check page. Install the browser extra (`pip install technolife-mcp[browser]`, or "
            "`uvx --with patchright==1.63.0 technolife-mcp`) and run `patchright install chromium`.",
            403,
        ) from e
    u = httpx.URL(proxy) if proxy else None
    opts = u and {"server": f"{u.scheme}://{u.host}:{u.port}", "username": u.username, "password": u.password}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=opts)
        try:
            page = await browser.new_page()
            await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_function(
                "!/just a moment|access denied|attention required|arvancloud/i.test(document.title)", timeout=30_000
            )
            return await browser.contexts[0].cookies()
        finally:
            await browser.close()


async def _clear_challenge(client: httpx.AsyncClient) -> None:
    """Rung 2: let a real browser pass the bot check once and share its cookies with the httpx jar."""
    global _browser_lock, _cleared
    _browser_lock = _browser_lock or asyncio.Lock()
    async with _browser_lock:  # one browser at a time; callers that waited reuse the cookies just fetched
        if _cleared and _cleared[0] is client and time.monotonic() - _cleared[1] < 30:
            return
        proxies = _proxies()
        try:
            cookies = await _browser_cookies(proxies[_proxy_index % len(proxies)] if proxies else None)
        except ApiError:
            raise
        except Exception as e:
            raise ApiError(f"Technolife bot check was not cleared by the browser ({type(e).__name__}).", 403) from e
        for c in cookies:
            client.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
        _cleared = (client, time.monotonic())


async def _request(method: str, url: str, params: dict[str, Any] | None, json: Any) -> Any:
    client, limit = _get_client()
    r = await _send(client, limit, method, url, params, json)
    if _is_challenge(r):
        _next_proxy(client)
        client, limit = _get_client()
        await _clear_challenge(client)
        r = await _send(client, limit, method, url, params, json)  # one retry; a second block is final
        if _is_challenge(r):
            _next_proxy(client)

    if r.status_code >= 400:
        raise ApiError(_status_message(r), r.status_code, _retry_after(r))
    try:
        return r.json()
    except ValueError as e:
        raise ApiError(f"www.technolife.com returned a non-JSON response (HTTP {r.status_code}).") from e


def _retry_after(r: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After on a 429/503, else None (HTTP-date form is ignored)."""
    v = r.headers.get("retry-after", "")
    return float(v) if r.status_code in (429, 503) and v.replace(".", "", 1).isdigit() else None


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
