import pytest
from conftest import live_call as call

pytestmark = [pytest.mark.anyio, pytest.mark.live]

LAPTOPS = "category/laptop-equipment/laptop"


async def test_tl_categories(client):
    data = await call(client, "tl_categories", {"query": "لپ تاپ گیمینگ"})
    assert any(c["url"] == "category/laptop-equipment/laptop/type-gaming" for c in data["categories"])


async def test_tl_category_products(client):
    data = await call(
        client, "tl_category_products", {"url": LAPTOPS, "sort": "cheapest", "brand_codes": [16], "limit": 10}
    )
    prices = [p["final_price"] for p in data["products"]]
    assert data["total"] > 0 and prices == sorted(prices) and prices[0] > 0


async def test_tl_category_filters(client):
    data = await call(client, "tl_category_filters", {"url": LAPTOPS})
    assert any(b["code"] == 16 for b in data["brands"]) and data["attributes"]


async def test_tl_category_products_max_price_only(client):
    data = await call(client, "tl_category_products", {"url": LAPTOPS, "sort": "cheapest", "max_price": 100000000})
    assert data["products"] and all(0 < p["final_price"] <= 100000000 for p in data["products"])


async def test_tl_category_filters_brand_page(client):
    data = await call(client, "tl_category_filters", {"url": "brand/samsung"})
    assert data["price_range"] and any(c["code"] == 1 for c in data["categories"])  # 1 = phones
    phones = await call(client, "tl_category_products", {"url": "brand/samsung", "category_codes": [1], "limit": 3})
    everything = await call(client, "tl_category_products", {"url": "brand/samsung", "limit": 3})
    assert 0 < phones["total"] < everything["total"]
