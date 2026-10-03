import pytest
from conftest import live_call as call

pytestmark = [pytest.mark.anyio, pytest.mark.live]


async def test_tl_store_info(client):
    data = await call(client, "tl_store_info", {"topic": "branches"})
    assert "تکنولایف" in data["title"] and len(data["text"]) > 200


async def test_tl_faq(client):
    data = await call(client, "tl_faq", {"query": "ارسال"})
    assert data["results"] and data["results"][0]["answer"]


async def test_tl_shop_reviews(client):
    data = await call(client, "tl_shop_reviews", {"limit": 5})
    assert data["count"] > 0 and all(1 <= r["rating"] <= 5 for r in data["reviews"])


async def test_tl_find_location(client):
    data = await call(client, "tl_find_location", {"query": "میدان ونک"})
    assert data["places"] and 35 < data["places"][0]["lat"] < 36


async def test_tl_reverse_geocode(client):
    data = await call(client, "tl_reverse_geocode", {"lat": 35.7575, "long": 51.4106})
    assert data["city"] == "تهران" and data["address"]
