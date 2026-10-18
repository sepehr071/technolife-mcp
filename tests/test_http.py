import asyncio
import sys

import httpx
import pytest

from technolife_mcp import http

pytestmark = pytest.mark.anyio

OK = {"data": {}}


def test_is_challenge():
    html = {"content-type": "text/html"}
    assert http._is_challenge(httpx.Response(403, text="<html>Just a moment...</html>", headers=html))
    assert http._is_challenge(httpx.Response(503, text="<!doctype html><title>ArvanCloud</title>"))
    assert not http._is_challenge(httpx.Response(403, text="<html>Access Denied</html>"))
    assert not http._is_challenge(httpx.Response(403, json={"errors": []}))
    assert not http._is_challenge(httpx.Response(200, text="<html></html>", headers=html))


async def test_frontend_headers_and_origin_on_post(api):
    api["op"] = OK
    api["/map_forward"] = OK
    await http.gql("svc", "query op { x }")
    await http.fetch(f"{http.BASE}/map_forward", {"search_text": "a"})
    post, get = api.calls
    assert post.headers["Referer"] == "https://www.technolife.com/" and post.headers["Origin"] == http.BASE
    assert post.headers["sec-fetch-site"] == "same-origin" and post.headers["Accept-Language"].startswith("fa-IR")
    assert "Origin" not in get.headers and "User-Agent" not in http.HEADERS


async def test_retry_on_5xx_and_429_but_not_403(api):
    hits = []

    def flaky(request):
        hits.append(1)
        return httpx.Response(503, text="down") if len(hits) < 3 else httpx.Response(200, json=OK)

    api["op"] = flaky
    assert await http.gql("svc", "query op { x }") == {}
    assert len(hits) == 3
    api["op"] = lambda r: httpx.Response(403, text="no")
    api.calls.clear()
    with pytest.raises(http.ApiError):
        await http.gql("svc", "query op { x }")
    assert len(api.calls) == 1


async def test_retry_after_is_honoured_and_capped(monkeypatch, api):
    waits = []

    async def fake_sleep(s):
        waits.append(s)

    monkeypatch.setattr(http.asyncio, "sleep", fake_sleep)
    hits = []

    def limited(request):
        hits.append(1)
        if len(hits) == 1:
            return httpx.Response(429, json={}, headers={"Retry-After": "3"})
        if len(hits) == 2:
            return httpx.Response(503, json={}, headers={"Retry-After": "999"})
        return httpx.Response(200, json=OK)

    api["op"] = limited
    await http.gql("svc", "query op { x }")
    assert [w for w in waits if w] == [3, http.MAX_RETRY_WAIT]


async def test_proxy_list_rotates_on_connect_error(monkeypatch, api):
    monkeypatch.setenv("TECHNOLIFE_MCP_PROXY", "http://p1:1, http://p2:2")
    assert http._proxies() == ["http://p1:1", "http://p2:2"]

    def boom(request):
        raise httpx.ConnectError("down", request=request)

    api["op"] = boom
    http._get_client()
    with pytest.raises(http.ApiError):
        await http._request("POST", f"{http.BASE}/svc", None, {"query": "query op { x }", "variables": {}})
    assert http._proxy_index == 1 and http._client is None
    monkeypatch.setenv("TECHNOLIFE_MCP_PROXY", "http://p1:1")
    http._get_client()
    with pytest.raises(http.ApiError):
        await http._request("POST", f"{http.BASE}/svc", None, {"query": "query op { x }", "variables": {}})
    assert http._client is not None  # a single proxy never rotates


async def test_stale_client_does_not_rotate(monkeypatch, api):
    monkeypatch.setenv("TECHNOLIFE_MCP_PROXY", "http://p1:1, http://p2:2")
    old, _ = http._get_client()
    http._next_proxy(old)
    new, _ = http._get_client()
    http._next_proxy(old)
    assert http._proxy_index == 1 and http._client is new


async def test_challenge_cleared_by_browser_once(monkeypatch, api):
    runs = []

    async def fake_browser(proxy):
        runs.append(proxy)
        await asyncio.sleep(0.01)
        return [{"name": "clearance", "value": "ok", "domain": "www.technolife.com", "path": "/"}]

    monkeypatch.setattr(http, "_browser_cookies", fake_browser)

    def guarded(request):
        if "clearance=ok" not in request.headers.get("cookie", ""):
            return httpx.Response(403, text="<html>Just a moment</html>", headers={"content-type": "text/html"})
        return httpx.Response(200, json=OK)

    api["op"] = guarded
    await asyncio.gather(http.gql("svc", "query op { x }"), http.gql("svc2", "query op { y }"))
    assert len(runs) == 1  # the second caller reused the cookies the first one fetched

    api["op"] = lambda r: httpx.Response(403, text="<html>Just a moment</html>")
    api.calls.clear()
    with pytest.raises(http.ApiError) as e:  # still blocked after the one retry: final
        await http.gql("svc", "query op { z }")
    assert e.value.status == 403 and len(api.calls) == 2


async def test_challenge_without_patchright(monkeypatch, api):
    monkeypatch.setitem(sys.modules, "patchright.async_api", None)  # makes the import fail
    api["op"] = lambda r: httpx.Response(403, text="<html>Just a moment</html>")
    with pytest.raises(http.ApiError, match=r"technolife-mcp\[browser\].*patchright install chromium"):
        await http.gql("svc", "query op { x }")
