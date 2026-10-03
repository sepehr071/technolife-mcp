import pytest
from conftest import live_call as call

pytestmark = [pytest.mark.anyio, pytest.mark.live]

LAPTOP = "TLP-60492"  # Lenovo IdeaPad Slim 3, several sellers, LOAN and BNPL clusters
IPHONE = "TLP-69610"  # iPhone 16, hundreds of reviews and an AI summary


async def test_tl_product(client):
    data = await call(client, "tl_product", {"product_code": LAPTOP})
    assert data["code"] == LAPTOP and data["offers"] and data["specs"]
    prices = [o["final_price"] for o in data["offers"]]
    assert prices == sorted(prices) and prices[0] > 0
    # installment prices cost a little more than cash
    assert any(o["installment_price"] and o["installment_price"] >= o["final_price"] for o in data["offers"])


async def test_tl_compare(client):
    data = await call(client, "tl_compare", {"product_codes": [LAPTOP, "TLP-133524"]})
    assert len(data["products"]) == 2 and all(len(v) == 2 for sec in data["specs"].values() for v in sec.values())


async def test_tl_reviews(client):
    data = await call(client, "tl_reviews", {"product_code": IPHONE, "limit": 5})
    assert data["count"] > 100 and 0 < data["average_rating"] <= 5
    assert all(1 <= r["rating"] <= 5 for r in data["reviews"])


async def test_tl_price_basket(client):
    product = await call(client, "tl_product", {"product_code": LAPTOP, "include_specs": False})
    offer = product["offers"][0]
    data = await call(
        client,
        "tl_price_basket",
        {"items": [{"seller_item_id": offer["seller_item_id"], "count": 1, "payment": "cash"}]},
    )
    assert data["total"] == offer["final_price"] and not data["not_found"]
