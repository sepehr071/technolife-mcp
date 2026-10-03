import pytest
from conftest import fixture, variables

pytestmark = pytest.mark.anyio


async def test_tl_deals_biggest_percent(client, api):
    api["marketing_group_results"] = fixture("special_products.json")
    api["get_landing_page"] = fixture("home.json")
    data = (await client.call_tool("tl_deals", {"limit": 5})).structured_content
    # the API orders by Toman amount off (66% first); re-sorted by percent
    assert [(d["code"], d["discount_pct"]) for d in data["deals"]] == [
        ("TLP-37131", 70),
        ("TLP-598756", 65),
        ("TLP-35893", 56),
        ("TLP-102071", 43),
        ("TLP-447508", 15),
    ]
    assert data["deals"][0]["final_price"] == 89000000 and data["deals"][0]["deal"] == "تکنوآف"
    sent = variables(next(r for r in api.calls if "marketing_group_results" in r.content.decode()))
    assert sent == {
        "marketing_group": "1",
        "filter": {"limit": 100, "skip": 0, "ordering": "discount-desc", "available": True},
    }
    # timed deals come from the تکنوآف and تکنو تایم home sections; the laptop carousel has no discount
    timed = data["timed_deals"]
    assert [d["code"] for d in timed] == ["TLP-167567", "TLP-31023", "TLP-586168", "TLP-175987", "TLP-511242"]
    assert timed[3]["section"] == "تکنو تایم" and timed[3]["discount_pct"] == 35
    assert timed[0]["section"] == "تکنوآف"  # the banner has no title of its own
    assert data["more_on_page"] > 0  # deals of the scanned 100 cut off by limit


async def test_tl_deals_min_discount_and_later_page(client, api):
    api["marketing_group_results"] = fixture("special_products.json")
    data = (
        await client.call_tool("tl_deals", {"sort": "cheapest", "min_discount_pct": 50, "page": 1})
    ).structured_content
    assert [d["final_price"] for d in data["deals"]] == [89000000, 158000000, 159000000]
    assert "timed_deals" not in data and len(api.calls) == 1
    # min_discount_pct filters a wide page
    assert variables(api.calls[0])["filter"] == {"limit": 100, "skip": 1, "ordering": "price-asc", "available": True}


async def test_tl_campaigns_list(client, api):
    api["get_landing_page"] = fixture("home.json")
    data = (await client.call_tool("tl_campaigns", {})).structured_content
    assert data["campaigns"][0] == {"title": "خرید سرماه", "kind": "landing", "code": "payday-technolife"}
    # partner sites, seller pages and brand pages are not campaigns
    assert [c["kind"] for c in data["campaigns"]] == ["landing"] * 4 + ["promotion"] * 2
    assert data["campaigns"][-2] == {"title": "اپیسر", "kind": "promotion", "page_url": "promotion/apacer-storage"}


async def test_tl_campaign_landing(client, api):
    api["get_landing_page_daynamic"] = fixture("landing.json")
    data = (
        await client.call_tool("tl_campaigns", {"code": "payday-technolife", "products_per_section": 2})
    ).structured_content
    assert variables(api.calls[0]) == {"code": "payday-technolife", "device_type": "desktop", "landing_type": "landing"}
    assert data["title"] == "خرید سر ماه"
    names = [s["name"] for s in data["sections"]]
    assert "جداکننده" not in names  # empty separators are dropped
    carousel = data["sections"][2]
    assert carousel["page_url"] == "promotion/hsp" and carousel["products_in_carousel"] == 4
    assert [p["code"] for p in carousel["products"]] == ["TLP-21162", "TLP-99215"]
    assert data["sections"][3]["links"][0] == {
        "title": "گوشی موبایل",
        "kind": "category",
        "page_url": "category/mobile",
    }


async def test_tl_campaign_unknown_code(client, api):
    api["get_landing_page_daynamic"] = {
        "data": {"get_landing_page_daynamic": {"code": None, "meta_title": None, "components": None}}
    }
    result = await client.call_tool("tl_campaigns", {"code": "nope"})
    assert result.is_error and "without a code" in result.content[0].text


async def test_tl_seller(client, api):
    api["get_seller_product_list"] = fixture("seller.json")
    data = (
        await client.call_tool("tl_seller", {"seller_code": "TLS-15172", "sort": "cheapest", "limit": 3})
    ).structured_content
    assert data["seller"] == {
        "code": "TLS-15172",
        "name": "ایران پشتیبان",
        "en_name": "IRANPOSHTIBAN",
        "rating": 5,
        "on_time_pct": 99.3,
        "faultless_pct": 99.5,
        "supply_pct": 99.7,
        "joined": "1y 5m",
    }
    # TLP-133524 still lists 149,999,000 but its deal ended on 2026-09-22: the real price is 176,800,000
    assert [(p["code"], p["final_price"]) for p in data["products"]] == [
        ("TLP-60492", 125000000),
        ("TLP-49420", 165000000),
        ("TLP-133524", 176800000),
    ]
    assert data["products"][2]["discount_pct"] == 0 and data["products"][2]["deal_ends"] is None
    assert variables(api.calls[0]) == {
        "seller_codes": ["15172"],
        "filterObj": {"limit": 3, "skip": 0, "ordering": "price-asc", "available": True},
    }


async def test_tl_seller_unknown(client, api):
    api["get_seller_product_list"] = {
        "errors": [{"message": "server error"}],
        "data": {"get_seller_product_list": None},
    }
    result = await client.call_tool("tl_seller", {"seller_code": "999999"})
    assert result.is_error and "Unknown seller" in result.content[0].text
