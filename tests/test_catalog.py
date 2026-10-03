import httpx
import pytest
from conftest import fixture, variables

pytestmark = pytest.mark.anyio


async def test_tl_categories_top_level(client, api):
    api["getNavBar"] = fixture("navbar.json")
    cats = (await client.call_tool("tl_categories", {})).structured_content["categories"]
    assert [c["url"] for c in cats] == ["category/mobile", "category/laptop-equipment"]
    # menu nodes that are not category/brand/promotion pages are dropped
    assert cats[0]["children"] == ["گوشی موبایل"]


async def test_tl_categories_query(client, api):
    api["getNavBar"] = fixture("navbar.json")
    data = (await client.call_tool("tl_categories", {"query": "گیمینگ"})).structured_content
    assert data["categories"] == [
        {
            "title": "گوشی گیمینگ",
            "url": "category/mobile/mobile-phone/type-gaming",
            "path": "گوشی موبایل و تجهیزات > گوشی براساس عملکرد",
        },
        {
            "title": "لپ تاپ گیمینگ",
            "url": "category/laptop-equipment/laptop/type-gaming",
            "path": "لپ تاپ و تجهیزات > لپ تاپ براساس کاربرد",
        },
    ]
    # Arabic ي/ك and half-spaces still match
    data = (await client.call_tool("tl_categories", {"query": "لپ\u200cتاپ گيمينگ"})).structured_content
    assert [c["title"] for c in data["categories"]] == ["لپ تاپ گیمینگ"]


async def test_tl_categories_sub_pages(client, api):
    api["getSubBreadCrumbProductList"] = fixture("sub_categories.json")
    data = (await client.call_tool("tl_categories", {"url": "category/mobile/mobile-phone"})).structured_content
    assert data["categories"][1] == {"title": "گوشی موبایل شیائومی", "url": "category/mobile/mobile-phone/brand-xiaomi"}
    assert variables(api.calls[0]) == {"url": "/category/mobile/mobile-phone"}


async def test_tl_category_products(client, api):
    api["get_menu_products"] = fixture("menu_products.json")
    args = {
        "url": "/category/laptop-equipment/laptop",
        "sort": "cheapest",
        "attribute_codes": [4447],
        "brand_codes": [16],
        "fast_delivery": True,
        "limit": 5,
    }
    data = (await client.call_tool("tl_category_products", args)).structured_content
    assert data["total"] == 258
    first = data["products"][0]
    # category lists send discounted_price null when there is no discount
    assert (
        first["code"] == "TLP-33392"
        and first["final_price"] == first["price"] == 101000000
        and first["discount_pct"] == 0
    )
    assert variables(api.calls[0]) == {
        "url": "category/laptop-equipment/laptop",
        "filterObj": {
            "page_type": "dynamic",
            "limit": 5,
            "skip": 0,
            "ordering": "price-asc",
            "available": True,
            "brand_filters": [16],
            "attribute_filters": [4447],
            "available_in_stock": True,
        },
    }


async def test_tl_category_products_promotion_url(client, api):
    api["get_menu_products"] = fixture("menu_products.json")
    await client.call_tool(
        "tl_category_products", {"url": "https://www.technolife.com/promotion/power48/پاوربانک", "category_codes": [22]}
    )
    sent = variables(api.calls[0])
    assert sent["url"] == "power48" and sent["filterObj"]["page_type"] == "promotion"
    assert sent["filterObj"]["category_filters"] == [22]


async def test_tl_category_products_bad_page(client, api):
    api["get_menu_products"] = {
        "errors": [{"message": "Internal Server Error", "statusCode": 500}],
        "data": {"get_menu_products": None},
    }
    result = await client.call_tool("tl_category_products", {"url": "brand/nope"})
    assert result.is_error and "tl_categories" in result.content[0].text
    # the same error comes back when nothing is priced inside the range
    result = await client.call_tool("tl_category_products", {"url": "brand/samsung", "max_price": 1000})
    assert result.is_error and "no product in that price range" in result.content[0].text


async def test_tl_category_products_rejects_other_urls(client, api):
    result = await client.call_tool("tl_category_products", {"url": "sellers/seller-11507"})
    assert result.is_error and not api.calls


async def test_tl_category_filters(client, api):
    api["get_menu_filters"] = fixture("menu_filters.json")
    data = (
        await client.call_tool("tl_category_filters", {"url": "category/laptop-equipment/laptop"})
    ).structured_content
    assert data["price_range"] == {"min": 0, "max": 1355740000}
    assert data["brands"][1] == {"code": 16, "name": "لنوو", "en_name": "Lenovo"}
    # colors use hex codes, which are not attribute filters
    assert data["attributes"] == [
        {
            "title": "ظرفیت حافظه RAM",
            "options": [
                {"code": 4439, "name": "تا 2 گیگابایت"},
                {"code": 4440, "name": "2 گیگابایت"},
                {"code": 4441, "name": "3 گیگابایت"},
            ],
            "options_total": 3,
        }
    ]


async def test_tl_category_filters_null_items_and_categories(client, api):
    body = fixture("menu_filters.json")
    filters = body["data"]["get_menu_filters"]["page_filters"]
    filters[3]["items"].append(None)  # brand pages send null color items
    # promotion pages filter by category
    filters.append({"title": "دسته بندی ها", "price_range": None, "items": [{"name": "فلش مموری", "code": "22"}, None]})
    api["get_menu_filters"] = body
    data = (await client.call_tool("tl_category_filters", {"url": "promotion/apacer-storage"})).structured_content
    assert data["categories"] == [{"code": 22, "name": "فلش مموری"}]
    assert [a["title"] for a in data["attributes"]] == ["ظرفیت حافظه RAM"]


async def test_tl_category_filters_bad_page(client, api):
    api["get_menu_filters"] = {"errors": [{"message": "Internal Server Error"}], "data": {"get_menu_filters": None}}
    result = await client.call_tool("tl_category_filters", {"url": "category/nonexistent/xyz"})
    assert result.is_error and "tl_categories" in result.content[0].text


async def test_upstream_rate_limit_passes_through(client, api):
    api["get_menu_products"] = lambda r: httpx.Response(429)
    result = await client.call_tool("tl_category_products", {"url": "brand/samsung"})
    assert result.is_error and "HTTP 429" in result.content[0].text
