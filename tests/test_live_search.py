import pytest
from conftest import live_call as call

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def test_tl_suggest(client):
    data = await call(client, "tl_suggest", {"query": "آیفون 16"})
    assert data["products"] and all(p["code"].startswith("TLP-") for p in data["products"])


async def test_tl_search(client):
    data = await call(client, "tl_search", {"query": "آیفون 16", "sort": "cheapest", "category_code": 1, "limit": 10})
    prices = [p["final_price"] for p in data["products"]]
    assert prices and prices == sorted(prices) and prices[0] > 0
    assert data["categories"] and data["brands"]


async def test_tl_find_cheapest(client):
    data = await call(
        client, "tl_find_cheapest", {"query": "لپ تاپ لنوو", "category_code": 19, "pages": 1, "limit": 10}
    )
    prices = [p["final_price"] for p in data["products"]]
    assert prices and prices == sorted(prices) and prices[0] > 0
    assert all(p["in_stock"] for p in data["products"])


async def test_tl_find_brand(client):
    data = await call(client, "tl_find_brand", {"name": "سامسونگ"})
    assert data["brands"][0]["brand_code"] == 26 and data["brands"][0]["brand_page"] == "brand/samsung"
