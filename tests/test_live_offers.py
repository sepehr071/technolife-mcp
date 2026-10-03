import pytest
from conftest import live_call as call

pytestmark = [pytest.mark.anyio, pytest.mark.live]

SELLER = "TLS-15172"


async def test_tl_deals(client):
    data = await call(client, "tl_deals", {"limit": 10})
    pcts = [d["discount_pct"] for d in data["deals"]]
    assert pcts and pcts == sorted(pcts, reverse=True) and pcts[-1] > 0
    assert all(d["final_price"] < d["price"] for d in data["deals"])


async def test_tl_campaigns(client):
    data = await call(client, "tl_campaigns", {})
    landing = next(c for c in data["campaigns"] if c["kind"] == "landing")
    detail = await call(client, "tl_campaigns", {"code": landing["code"]})
    assert detail["sections"]


async def test_tl_seller(client):
    data = await call(client, "tl_seller", {"seller_code": SELLER, "limit": 5})
    assert data["seller"]["code"] == SELLER and 0 <= data["seller"]["rating"] <= 5 and data["products"]
