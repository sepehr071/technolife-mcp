import pytest
from conftest import fixture, variables

pytestmark = pytest.mark.anyio


async def test_tl_product(client, api):
    body = fixture("product_page.json")
    group = body["data"]["get_product_page"]["seller_items_component"][0]
    group["seller_items"].reverse()  # most expensive first: the tool sorts cheapest first
    group["seller_items"][0]["discounted_price"] = 117000000  # dibacom 130M -> 117M, 10% off
    api["get_product_page"] = body
    p = (await client.call_tool("tl_product", {"product_code": "60492"})).structured_content
    assert variables(api.calls[0]) == {"code": "TLP-60492"}
    assert p["title"] == "لپ تاپ لنوو 15.6 اینچی مدل IdeaPad Slim 3 i3 1315U 8GB 512GB"
    assert p["rating"] == 4.2 and p["rating_count"] == 45 and p["brand_en"] == "Lenovo"
    assert [(o["seller_code"], o["final_price"]) for o in p["offers"]] == [
        ("TLS-1350", 117000000),
        ("TLS-15172", 125000000),
        ("TLS-1445", 129500000),
    ]
    assert p["offers"][0]["discount_pct"] == 10 and p["offers"][0]["price"] == 130000000
    assert p["offers"][1] == {
        "seller_item_id": "68a8a44fd66b224721bea068",
        "color": "خاکستری",
        "seller": "ایران پشتیبان",
        "seller_code": "TLS-15172",
        "final_price": 125000000,
        "price": 125000000,
        "discount_pct": 0,
        "guarantee": "18 ماه گارانتی شرکتی",
        "in_stock": True,
        "stock_text": "موجود در انبار فروشنده",
        "delivery_text": "ارسال از 1 روز کاری بعد",
        "insurance_price": 2375000,
        "seller_rating": 5,
        "seller_on_time_pct": 100,
        "seller_faultless_pct": 100,
        "sold_by_technolife": False,
        "fast_delivery": False,
        "deal": None,
        "deal_ends": None,
        "installment_price": 128750000,
        "bnpl_price": 135000000,
    }
    assert p["specs"]["مشخصات فیزیکی"] == {"ابعاد": "359.3x235x17.9 میلی متر", "وزن": "1.6 کیلوگرم"}


async def test_tl_product_unknown_code(client, api):
    api["get_product_page"] = {
        "errors": [{"message": "INTERNAL_SERVER_ERROR", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}],
        "data": {"get_product_page": None},
    }
    result = await client.call_tool("tl_product", {"product_code": "TLP-999999999", "include_specs": False})
    assert result.is_error and "tl_suggest" in result.content[0].text


async def test_tl_product_rejects_bad_code(client, api):
    result = await client.call_tool("tl_product", {"product_code": "TLS-15172"})
    assert result.is_error and not api.calls


async def test_tl_compare(client, api):
    api["get_compare_page"] = fixture("compare.json")
    data = (await client.call_tool("tl_compare", {"product_codes": ["TLP-60492", "133524"]})).structured_content
    assert variables(api.calls[0]) == {"products": ["TLP-60492", "TLP-133524"]}
    assert data["category"] == "لپ تاپ"
    assert [p["final_price"] for p in data["products"]] == [125000000, 176800000]
    assert data["specs"]["مشخصات فیزیکی"]["وزن"] == ["1.6 کیلوگرم", "--"]


async def test_tl_compare_unknown_code(client, api):
    api["get_compare_page"] = {"errors": [{"message": "INTERNAL_SERVER_ERROR"}], "data": {"get_compare_page": None}}
    result = await client.call_tool("tl_compare", {"product_codes": ["TLP-60492", "TLP-999999999"]})
    assert result.is_error and "tl_suggest" in result.content[0].text


async def test_tl_product_expired_deal(client, api):
    body = fixture("product_page.json")
    offer = body["data"]["get_product_page"]["seller_items_component"][0]["seller_items"][0]
    # the deal label and price outlive the deadline (2025-09-12)
    offer.update(discounted_price=100000000, marketing_group="تکنوآف", deadline="1757674000000")
    api["get_product_page"] = body
    p = (await client.call_tool("tl_product", {"product_code": "60492"})).structured_content
    o = next(o for o in p["offers"] if o["seller_item_id"] == offer["_id"])
    assert (o["final_price"], o["discount_pct"], o["deal"], o["deal_ends"]) == (125000000, 0, None, None)


async def test_tl_compare_needs_two(client, api):
    result = await client.call_tool("tl_compare", {"product_codes": ["TLP-60492"]})
    assert result.is_error and not api.calls


async def test_tl_reviews(client, api):
    api["get_product_comments"] = fixture("comments.json")
    api["Get_product_review_summary"] = fixture("review_summary.json")
    data = (
        await client.call_tool("tl_reviews", {"product_code": "TLP-69610", "sort": "lowest_rated", "limit": 3})
    ).structured_content
    assert data["count"] == 663 and data["average_rating"] == 4.4
    assert data["stars_pct"] == {"1": 3, "2": 2, "3": 9, "4": 25, "5": 61}
    # rating sorts rank date-ordered reviews locally: the API shuffles equal scores between pages
    assert [r["rating"] for r in data["reviews"]] == [3, 4, 5]
    assert data["reviews"][0]["author"] == "مائده امیری فرد امیری فرد" and data["reviews"][0]["likes"] == 3
    assert data["summary"]["cons"] == ["تاخیر در ارسال و تحویل"] and data["summary"]["reviews_used"] == 30
    comments = next(r for r in api.calls if "get_product_comments" in r.content.decode())
    assert variables(comments) == {
        "code": "TLP-69610",
        "filter": {"limit": 500, "skip": 0, "sort": {"field": "date", "order": "desc"}},
    }


async def test_tl_reviews_html_replies(client, api):
    body = fixture("comments.json")
    body["data"]["get_product_comments"]["results"][0]["answers"] = [
        {
            "reviewer": "تکنولایف",
            "date": "1404/01/01",
            "body": "<p>&nbsp;گزینه &lt;موجود شد&gt; رو فعال کنید.<br />\n&nbsp;</p>\n",
        }
    ]
    api["get_product_comments"] = body
    data = (await client.call_tool("tl_reviews", {"product_code": "TLP-69610", "page": 1})).structured_content
    assert data["reviews"][0]["replies"] == ["گزینه <موجود شد> رو فعال کنید."]


async def test_tl_reviews_later_page_skips_summary(client, api):
    api["get_product_comments"] = fixture("comments.json")
    data = (await client.call_tool("tl_reviews", {"product_code": "TLP-69610", "page": 1})).structured_content
    assert "summary" not in data and len(api.calls) == 1
    assert variables(api.calls[0])["filter"]["skip"] == 1


async def test_tl_reviews_no_summary(client, api):
    api["get_product_comments"] = fixture("comments.json")
    api["Get_product_review_summary"] = {"data": {"get_product_review_summary": None}}
    data = (await client.call_tool("tl_reviews", {"product_code": "TLP-60492"})).structured_content
    assert data["summary"] is None


async def test_tl_price_basket(client, api):
    api["get_basket_notLogin"] = fixture("basket.json")
    items = [
        {"seller_item_id": "68a8a44fd66b224721bea068", "count": 2, "insured_count": 1, "payment": "installment"},
        {"seller_item_id": "000000000000000000000000"},
    ]
    data = (await client.call_tool("tl_price_basket", {"items": items})).structured_content
    assert variables(api.calls[0]) == {
        "items": [
            {"item": "68a8a44fd66b224721bea068", "count": 2, "insurance_count": 1, "priceClusterType": "LOAN"},
            {"item": "000000000000000000000000", "count": 1, "insurance_count": 0, "priceClusterType": "CASH"},
        ]
    }
    line = data["items"][0]
    assert line["payment"] == "installment" and line["unit_price"] == 128750000
    assert line["line_total"] == 2 * 128750000 + 2446250 == data["total"]
    assert line["max_count"] == 1 and line["over_max_count"] is True
    assert data["not_found"] == ["000000000000000000000000"]
    assert data["insurance"] == 2446250 and data["price_before_discount"] == 257500000


async def test_tl_price_basket_rejects_repeated_item(client, api):
    item = {"seller_item_id": "68a8a44fd66b224721bea068"}
    result = await client.call_tool("tl_price_basket", {"items": [item, {**item, "payment": "installment"}]})
    assert result.is_error and "separate calls" in result.content[0].text and not api.calls


async def test_tl_price_basket_unknown_among_known(client, api):
    api["get_basket_notLogin"] = {"errors": [{"message": "Cannot read property 'available' of undefined"}]}
    items = [{"seller_item_id": "68a8a44fd66b224721bea068"}, {"seller_item_id": "000000000000000000000000"}]
    result = await client.call_tool("tl_price_basket", {"items": items})
    assert result.is_error and "fresh ids from tl_product" in result.content[0].text


async def test_tl_price_basket_insures_every_unit(client, api):
    body = fixture("basket.json")
    d = body["data"]["get_basket_notLogin"]
    d["products"][0]["insurance_count"] = 2  # insurance_price stays per unit
    d["purchase_box"].update(insurance_bill=2 * 2446250, final_price=257500000 + 2 * 2446250)
    api["get_basket_notLogin"] = body
    items = [{"seller_item_id": "68a8a44fd66b224721bea068", "count": 2, "insured_count": 2, "payment": "installment"}]
    data = (await client.call_tool("tl_price_basket", {"items": items})).structured_content
    line = data["items"][0]
    assert line["insured_count"] == 2 and line["insurance_unit_price"] == 2446250
    assert line["line_total"] == 2 * 128750000 + 2 * 2446250 == data["total"]


async def test_tl_price_basket_rejects_bad_item_id(client, api):
    result = await client.call_tool("tl_price_basket", {"items": [{"seller_item_id": "TLP-60492"}]})
    assert result.is_error and not api.calls
