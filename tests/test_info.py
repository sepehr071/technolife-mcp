import httpx
import pytest
from conftest import fixture, variables

from technolife_mcp.info import html_text

pytestmark = pytest.mark.anyio


async def test_all_tools_are_read_only(client):
    tools = (await client.list_tools()).tools
    assert len(tools) == 19
    for t in tools:
        assert t.name.startswith("tl_"), t.name
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False, t.name
        assert t.description and t.title, t.name


async def test_tl_store_info(client, api):
    api["get_static_pages"] = fixture("static_page.json")
    data = (await client.call_tool("tl_store_info", {"topic": "shipping"})).structured_content
    assert variables(api.calls[0]) == {"page_number": "9"}
    assert data["title"] == "روش\u200cها و هزینه\u200cهای ارسال"
    assert data["text"].startswith("همراهان عزیز تکنولایف")  # soft hyphens and tags removed
    assert "- پست پیشتاز (برای سراسر کشور)" in data["text"].splitlines()


async def test_tl_faq_keeps_links(client, api):
    api["get_search_faq"] = fixture("faq_search.json")
    data = (await client.call_tool("tl_faq", {"query": "اقساط"})).structured_content
    assert data["results"][0]["answer"] == (
        "بله، برای اطلاعات کامل به صفحه زیر مراجعه نمایید.\nراهنمای خرید اقساطی از تکنولایف (https://www.technolife.ir/landings/installment-payment)"
    )


async def test_tl_shop_reviews(client, api):
    api["get_article_comments"] = fixture("shop_reviews.json")
    data = (await client.call_tool("tl_shop_reviews", {"page": 1, "limit": 3})).structured_content
    assert variables(api.calls[0]) == {"limit": 3, "skip": 1}
    assert data["count"] == 393 and [r["rating"] for r in data["reviews"]] == [3, 5, 5]
    assert data["reviews"][1]["reply"].startswith("مرجی عزیز")


async def test_tl_find_location(client, api):
    api["/map_forward"] = fixture("map_forward.json")
    data = (await client.call_tool("tl_find_location", {"query": "میدان ونک"})).structured_content
    assert data["places"][0] == {
        "name": "م. ونک",
        "description": "تهران،م. ونک",
        "lat": 35.757535,
        "long": 51.40994,
        "province": "استان تهران",
        "city": "شهر تهران",
        "type": "Street",
    }
    assert api.calls[0].url.params["search_text"] == "میدان ونک"


async def test_tl_reverse_geocode(client, api):
    api["/map_reverse"] = fixture("map_reverse.json")
    data = (await client.call_tool("tl_reverse_geocode", {"lat": 35.7575, "long": 51.4106})).structured_content
    assert data == {"address": "ضلع شرقی م. ونک", "province": "تهران", "city": "تهران", "areas": ["گاندی"]}
    assert api.calls[0].url.params["location"] == "51.4106,35.7575"  # lng,lat


async def test_map_error_status(client, api):
    api["/map_forward"] = {"status": "ERROR", "reason": "quota"}
    result = await client.call_tool("tl_find_location", {"query": "ونک"})
    assert result.is_error and "map service" in result.content[0].text


def test_html_text():
    assert (
        html_text("<p>&shy;a<br/>b <a href='https://x.ir/y'>link</a></p><ul><li>c</li></ul>")
        == "a\nb link (https://x.ir/y)\nc"
    )
    assert html_text(None) == ""


# --- upstream failure paths (shared http.py) ---


async def test_graphql_errors_become_tool_errors(client, api):
    api["get_search_faq"] = {"errors": [{"message": "Cannot query field", "extensions": {"stacktrace": ["..."]}}]}
    result = await client.call_tool("tl_faq", {"query": "ارسال"})
    assert result.is_error and "Technolife rejected the request: Cannot query field" in result.content[0].text


async def test_graphql_validation_error_http_400(client, api):
    api["get_search_faq"] = lambda r: httpx.Response(
        400, json={"errors": [{"message": 'Variable "$search" got invalid value'}]}
    )
    result = await client.call_tool("tl_faq", {"query": "ارسال"})
    assert result.is_error and "HTTP 400" in result.content[0].text and "invalid value" in result.content[0].text


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(403, text="cloudflare"), "HTTP 403"),
        (httpx.Response(404), "HTTP 404"),
        (httpx.Response(429), "rate limiting"),
        (httpx.Response(502, text="<html>bad gateway</html>"), "server error (HTTP 502)"),
        (httpx.Response(200, text="<html>not json</html>"), "non-JSON"),
    ],
)
async def test_http_failures_are_actionable(client, api, response, expected):
    api["get_search_faq"] = lambda r: response
    result = await client.call_tool("tl_faq", {"query": "ارسال"})
    assert result.is_error and expected in result.content[0].text


async def test_tls_reset_is_retried_once(client, api, monkeypatch):
    monkeypatch.setattr("technolife_mcp.http.asyncio.sleep", _no_sleep)
    attempts = []

    def flaky(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ConnectError("[WinError 10054] connection reset during TLS handshake")
        return httpx.Response(200, json=fixture("faq_search.json"))

    api["get_search_faq"] = flaky
    result = await client.call_tool("tl_faq", {"query": "اقساط"})
    assert not result.is_error and len(attempts) == 2


async def test_network_down_after_retry(client, api, monkeypatch):
    monkeypatch.setattr("technolife_mcp.http.asyncio.sleep", _no_sleep)

    def down(request):
        raise httpx.ConnectError("unreachable")

    api["get_search_faq"] = down
    result = await client.call_tool("tl_faq", {"query": "اقساط"})
    assert result.is_error and "Could not reach www.technolife.com (ConnectError)" in result.content[0].text
    assert len(api.calls) == 2
    # tools that explain unknown codes or urls keep the network message as is
    api["get_menu_products"] = down
    result = await client.call_tool("tl_category_products", {"url": "brand/samsung"})
    assert (
        result.is_error
        and "Could not reach" in result.content[0].text
        and "tl_categories" not in result.content[0].text
    )


async def test_timeout(client, api):
    def slow(request):
        raise httpx.ReadTimeout("slow")

    api["get_search_faq"] = slow
    result = await client.call_tool("tl_faq", {"query": "اقساط"})
    assert result.is_error and "did not answer in time" in result.content[0].text


async def _no_sleep(_seconds):
    return None
