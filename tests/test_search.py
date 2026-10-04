import httpx
import pytest
from conftest import fixture, variables

pytestmark = pytest.mark.anyio


async def test_tl_suggest(client, api):
    api["search"] = fixture("search_suggest.json")
    data = (await client.call_tool("tl_suggest", {"query": "آیفون 16"})).structured_content
    assert data["products"][0] == {
        "code": "TLP-69610",
        "title": "گوشی موبایل اپل مدل iPhone 16 CH/A ظرفیت 128 گیگابایت رم 8 گیگابایت رجیستر شده",
        "url": "https://www.technolife.com/product-69610",
    }
    assert len(data["products"]) == 3 and data["pages"] == []
    assert variables(api.calls[0]) == {"text": "آیفون 16"}


async def test_tl_search_cheapest_resorts_on_real_price(client, api):
    api["search_page_results"] = fixture("search_results.json")
    args = {
        "query": "آیفون 16",
        "sort": "cheapest",
        "category_code": 1,
        "brand_codes": [20],
        "min_price": 1000,
        "limit": 5,
    }
    data = (await client.call_tool("tl_search", args)).structured_content
    # the API's price order is approximate: iPhone 16 (317M) came before the discounted iPhone 14 (239.9M)
    assert [p["code"] for p in data["products"]] == ["TLP-7452", "TLP-69610", "TLP-165487", "TLP-586168", "TLP-603463"]
    assert data["products"][0] == {
        "code": "TLP-7452",
        "title": "گوشی موبایل اپل iPhone 14 CH نات اکتیو ظرفیت 128 گیگابایت رم 6 گیگابایت رجیستر شده",
        "final_price": 239900000,
        "price": 249000000,
        "discount_pct": 4,
        "in_stock": True,
        "rating": 4.4,
        "rating_count": 117,
        "deal": "تکنوآف",
        "deal_ends": "2026-10-22T08:26+00:00",
        "url": "https://www.technolife.com/product-7452",
    }
    assert data["total"] == 15
    assert data["categories"][0] == {"code": 2, "name": "قاب و کیف گوشی", "count": 14369}
    assert data["brands"][2] == {"code": 19, "name": "ایسوس", "count": 2409}
    assert data["price_range"] == {"min": 0, "max": 1355740000}
    assert variables(api.calls[0])["filter"] == {
        "limit": 5,
        "skip": 0,
        "ordering": "price-asc",
        "available": True,
        "price_min": 1000,
        "brand_filters": [20],
        "category_filters": [1],
    }


async def test_tl_search_relevance_keeps_api_order(client, api):
    api["search_page_results"] = fixture("search_results.json")
    data = (await client.call_tool("tl_search", {"query": "آیفون 16", "in_stock": False, "page": 2})).structured_content
    assert data["products"][0]["code"] == "TLP-69610"
    assert data["products"][0]["deal"] is None  # some cards send an ISO deadline (2026-09-12), already past
    sent = variables(api.calls[0])["filter"]
    assert sent["ordering"] == "kalascore" and sent["skip"] == 2 and "available" not in sent


async def test_tl_search_biggest_discount_resorts(client, api):
    api["search_page_results"] = fixture("search_results.json")
    data = (
        await client.call_tool("tl_search", {"query": "آیفون 16", "sort": "biggest_discount_toman"})
    ).structured_content
    # the API order (0, 9.1M, 18.4M, 10M, 17M off) follows a lagging index
    assert [p["price"] - p["final_price"] for p in data["products"]] == [18400000, 17000000, 10000000, 9100000, 0]


async def test_tl_find_cheapest(client, api):
    pages = [fixture("search_cheapest_p0.json"), fixture("search_cheapest_p1.json")]
    pages[1]["data"]["search_page_results"]["results"][0]["available"] = 0  # out of stock: dropped
    facets = pages[0]["data"]["search_page_results"]["page_filters"]
    category = next(i for f in facets if "دسته" in f["title"] for i in f["items"] if i["code"] == "19")
    category["name"] = "لپ تاپ (14319)"  # some searches label facets 'name (count)'

    def by_page(request):
        return httpx.Response(200, json=pages[variables(request)["filter"]["skip"]])

    api["search_page_results"] = by_page
    data = (
        await client.call_tool("tl_find_cheapest", {"query": "لپ تاپ لنوو", "category_code": 19, "pages": 2})
    ).structured_content
    prices = [p["final_price"] for p in data["products"]]
    assert prices == [82000000, 83500000, 88000000, 185000000, 186000000, 190000000]
    assert data["scanned"] == 6 and data["total"] == 1053
    assert data["categories"][0] == {"code": 19, "name": "لپ تاپ", "count": 14319}
    sent = sorted(
        (variables(r)["filter"]["skip"], variables(r)["filter"]["limit"], variables(r)["filter"]["ordering"])
        for r in api.calls
    )
    assert sent == [(0, 100, "price-asc"), (1, 100, "price-asc")]


async def test_tl_find_cheapest_caps_pages(client, api):
    result = await client.call_tool("tl_find_cheapest", {"query": "لپ تاپ", "pages": 9})
    assert result.is_error and not api.calls


async def test_tl_find_brand(client, api):
    api["similar_brands"] = fixture("similar_brands.json")
    data = (await client.call_tool("tl_find_brand", {"name": " لنوو "})).structured_content
    assert data["brands"] == [
        {"brand_code": 16, "name": "لنوو", "en_name": "Lenovo", "brand_page": "brand/lenovo", "match_pct": 100}
    ]
    assert variables(api.calls[0]) == {"brand_name": "لنوو"}


async def test_short_query_rejected(client, api):
    result = await client.call_tool("tl_search", {"query": "a"})
    assert result.is_error and not api.calls
