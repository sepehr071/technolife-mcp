"""Product tools: one product's offers and specs, comparison, reviews, basket pricing."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from .http import ApiError, GraphQLError, gql
from .info import html_text
from .registry import tool
from .search import card, expired, ms_to_iso, product_url, rating

ProductCode = Annotated[
    str,
    Field(
        pattern=r"^(TLP-)?\d{1,9}$",
        description="Product code from a search or list, e.g. 'TLP-60492' (the bare number works too).",
    ),
]

OFFER_FIELDS = (
    "_id seller seller_code price discounted_price discount guarantee available stock_text delivery_text insurance { bill } "
    "score on_schedule faultless is_techno is_turbo deadline marketing_group"
)
PRODUCT = (
    "query get_product_page ($code: String) { get_product_page (code: $code) { has_insurance "
    "product_info { _id code title model is_available score_avg score_count category { code name } brand { name enName code } } "
    f"seller_items_component {{ color {{ value }} seller_items {{ {OFFER_FIELDS} }} "
    "cluster_seller_items { cluster_type { name } seller_items { _id seller_code price discounted_price available } } } "
    "configurations_component { title info { item value } } } }"
)
COMPARE = (
    "query get_compare_page ($products: [String]) { get_compare_page (products: $products) { category { name code } "
    "products { name code score_avg score_count normal_price discounted_price discount available } config_table { title items { name values } } } }"
)
COMMENTS = (
    "query get_product_comments ($code: String, $filter: CommentFilter!) { get_product_comments (code: $code, filter: $filter) { "
    "results { text name date likes dislikes score pros cons answers { reviewer date body } } scores { score percentage } count average_score } }"
)
SUMMARY = (
    "query Get_product_review_summary ($code: String!) { get_product_review_summary (code: $code) { "
    "products_reviews_count reviews_summary pros_summary cons_summary product_rating } }"
)
BASKET = (
    "query get_basket_notLogin ($items: [BasketItem]) { get_basket_notLogin (items: $items) { "
    "products { _id insurance_count insurance_price count max_valid_count code price discount discounted_price color { value } "
    "guarantee seller title stock_text cluster_type } purchase_box { price final_price discount insurance_bill } } }"
)

# Price clusters: the same seller item costs more when paid in installments.
CLUSTERS = {"cash": "CASH", "installment": "LOAN", "bnpl": "BNPL"}
CLUSTER_NAMES = {v: k for k, v in CLUSTERS.items()}

REVIEW_SORT = {
    "newest": {"field": "date", "order": "desc"},
    "oldest": {"field": "date", "order": "asc"},
    "highest_rated": {"field": "score", "order": "desc"},
    "lowest_rated": {"field": "score", "order": "asc"},
}


@tool("Product details")
async def tl_product(
    product_code: ProductCode,
    include_specs: Annotated[bool, Field(description="Include the full spec table (adds a few KB).")] = True,
) -> dict[str, Any]:
    """Get one product's offers: price per color, seller and warranty, stock, delivery time, insurance and installment prices.

    Use after tl_search / tl_suggest to answer "where is it cheapest, which color, which
    warranty, when does it ship, how much in installments". offers are cheapest cash price
    first; installment_price and bnpl_price are the same seller item in the installment (LOAN)
    and buy now pay later (BNPL) price lists, null if not offered. Pass seller_item_id to
    tl_price_basket for a final total.
    """
    code = tlp(product_code)
    try:
        data = await gql("shop_product", PRODUCT, {"code": code})
    except GraphQLError as e:
        # An unknown code answers a GraphQL INTERNAL_SERVER_ERROR.
        raise ApiError(f"Could not load product {code} ({e}). Check the code with tl_suggest or tl_search.") from e
    page = data.get("get_product_page") or {}
    info = page.get("product_info")
    if not info:
        raise ApiError(f"Unknown product code {code}. Get codes from tl_suggest or tl_search.")

    offers, cluster_prices = [], {}
    for group in page.get("seller_items_component") or []:
        color = (group.get("color") or {}).get("value")
        offers += [_offer(o, color) for o in group.get("seller_items") or []]
        for cluster in group.get("cluster_seller_items") or []:
            kind = CLUSTER_NAMES.get((cluster.get("cluster_type") or {}).get("name"))
            for o in cluster.get("seller_items") or []:
                if kind and o.get("available"):
                    cluster_prices[(o.get("_id"), kind)] = o.get("discounted_price") or o.get("price")
    for o in offers:
        o["installment_price"] = cluster_prices.get((o["seller_item_id"], "installment"))
        o["bnpl_price"] = cluster_prices.get((o["seller_item_id"], "bnpl"))
    brand = info.get("brand") or {}
    result: dict[str, Any] = {
        "code": info.get("code"),
        "id": info.get("_id"),
        "title": info.get("title"),
        "model": info.get("model"),
        "url": product_url(info.get("code")),
        "brand": brand.get("name"),
        "brand_en": brand.get("enName"),
        "category": (info.get("category") or {}).get("name"),
        "available": info.get("is_available"),
        "rating": rating(info.get("score_avg"), info.get("score_count")),
        "rating_count": info.get("score_count"),
        "insurance_available": page.get("has_insurance"),
        "offers": sorted(offers, key=lambda o: o["final_price"] or 0),
    }
    if include_specs:
        result["specs"] = {
            (s.get("title") or "").strip(): {
                (i.get("item") or "").strip(): (i.get("value") or "").strip() for i in s.get("info") or []
            }
            for s in page.get("configurations_component") or []
        }
    return result


@tool("Compare products")
async def tl_compare(
    product_codes: Annotated[
        list[ProductCode],
        Field(min_length=2, max_length=5, description="2 to 5 product codes, e.g. ['TLP-60492', 'TLP-133524']."),
    ],
) -> dict[str, Any]:
    """Compare 2-5 products side by side: price, stock, rating and every spec.

    specs is {section: {spec: values}} with one value per product, in the order of `products`;
    specs no product fills are left out. Products of the same category compare best. For sellers and colors
    of one product use tl_product.
    """
    codes = [tlp(c) for c in product_codes]
    try:
        data = await gql("shop_product", COMPARE, {"products": codes})
    except GraphQLError as e:
        # An unknown code answers a GraphQL INTERNAL_SERVER_ERROR.
        raise ApiError(
            f"Could not compare {', '.join(codes)} ({e}). One of the codes may be wrong; check them with tl_suggest or tl_search."
        ) from e
    d = data.get("get_compare_page") or {}
    specs: dict[str, dict[str, list[str]]] = {}
    for s in d.get("config_table") or []:
        for i in s.get("items") or []:
            values = [(v or "").strip() for v in i.get("values") or []]
            if any(v not in ("", "--") for v in values):
                specs.setdefault((s.get("title") or "").strip(), {})[(i.get("name") or "").strip()] = values
    return {
        "category": (d.get("category") or {}).get("name"),
        "products": [card(p) for p in d.get("products") or []],
        "specs": specs,
    }


@tool("Product reviews")
async def tl_reviews(
    product_code: ProductCode,
    sort: Annotated[
        Literal["newest", "oldest", "highest_rated", "lowest_rated"], Field(description="Order of the reviews.")
    ] = "newest",
    page: Annotated[int, Field(ge=0, le=100, description="Zero-based page number.")] = 0,
    limit: Annotated[int, Field(ge=1, le=50, description="Reviews per page.")] = 10,
) -> dict[str, Any]:
    """Read customer reviews of a product: average 0-5, star distribution, AI summary with pros/cons, and the reviews.

    Use as a quality check before recommending a product. sort=lowest_rated surfaces
    complaints. The AI summary (null for products with few reviews) comes on page 0 only.
    The rating sorts rank the newest 500 reviews, newest first within a rating.
    """
    code = tlp(product_code)
    by_score = sort in ("highest_rated", "lowest_rated")
    if by_score:
        # The API's score order shuffles equal scores between calls, so its pages overlap.
        # ponytail: rank the newest 500 locally; page the API by date if older reviews matter
        flt = {"limit": 500, "skip": 0, "sort": REVIEW_SORT["newest"]}
    else:
        flt = {"limit": limit, "skip": page, "sort": REVIEW_SORT[sort]}  # skip is a page index
    calls = [gql("comment", COMMENTS, {"code": code, "filter": flt})]
    if page == 0:
        calls.append(gql("comment", SUMMARY, {"code": code}))
    results = await asyncio.gather(*calls)
    d = results[0].get("get_product_comments") or {}
    comments = d.get("results") or []
    if by_score:
        sign = -1 if sort == "highest_rated" else 1
        comments = sorted(comments, key=lambda c: sign * (c.get("score") or 0))[page * limit : (page + 1) * limit]
    out: dict[str, Any] = {
        "count": d.get("count"),
        "average_rating": round(d["average_score"], 1) if d.get("average_score") else None,
        "stars_pct": {
            str(s["score"]): round(s.get("percentage") or 0) for s in d.get("scores") or [] if s.get("score")
        },
        "reviews": [
            {
                "date": c.get("date"),
                "author": c.get("name"),
                "rating": c.get("score"),
                "text": c.get("text"),
                "pros": c.get("pros") or [],
                "cons": c.get("cons") or [],
                "likes": c.get("likes"),
                "dislikes": c.get("dislikes"),
                "replies": [html_text(a["body"]) for a in c.get("answers") or [] if a.get("body")],
            }
            for c in comments
        ],
    }
    if page == 0:
        s = results[1].get("get_product_review_summary")
        out["summary"] = (
            {
                "text": s.get("reviews_summary"),
                "pros": s.get("pros_summary") or [],
                "cons": s.get("cons_summary") or [],
                "reviews_used": s.get("products_reviews_count"),
            }
            if s
            else None
        )
    return out


class BasketItem(BaseModel):
    seller_item_id: Annotated[
        str,
        Field(
            pattern=r"^[0-9a-f]{24}$",
            description="seller_item_id from tl_product offers, e.g. '68a8a44fd66b224721bea068'.",
        ),
    ]
    count: Annotated[int, Field(ge=1, le=20, description="Quantity.")] = 1
    insured_count: Annotated[int, Field(ge=0, le=20, description="How many of the units get device insurance.")] = 0
    payment: Annotated[
        Literal["cash", "installment", "bnpl"],
        Field(description="cash, installment (LOAN cluster) or bnpl (buy now pay later)."),
    ] = "cash"


@tool("Price a basket")
async def tl_price_basket(
    items: Annotated[
        list[BasketItem],
        Field(min_length=1, max_length=20, description="Seller items to price, from tl_product offers."),
    ],
) -> dict[str, Any]:
    """Get the exact total for a set of seller items: discounts, insurance, quantity limits, cash vs installment price.

    Prices on Technolife's server as a guest; nothing is saved, no login, no order.
    Shipping is not included (it needs a logged-in address). max_count is the most units
    one order may contain; over_max_count means the site will refuse that quantity.
    Each seller_item_id may appear once: compare cash and installment in separate calls.
    """
    ids = [i.seller_item_id for i in items]
    if len(set(ids)) < len(ids):
        raise ToolError(
            "Each seller_item_id may appear once (the site merges repeats). Put the whole quantity in one "
            "line, and price cash and installment in separate calls."
        )
    payload = [
        {
            "item": i.seller_item_id,
            "count": i.count,
            "insurance_count": min(i.insured_count, i.count),
            "priceClusterType": CLUSTERS[i.payment],
        }
        for i in items
    ]
    try:
        data = await gql("shop_basket", BASKET, {"items": payload})
    except GraphQLError as e:
        # One unknown id among known ones fails the whole call; all-unknown answers an empty basket.
        raise ApiError(
            f"One or more seller_item_id values are unknown or no longer sold ({e}). Get fresh ids from "
            "tl_product, or price the items one at a time to find the bad one."
        ) from e
    d = data.get("get_basket_notLogin") or {}
    lines = []
    for p in d.get("products") or []:
        unit = p.get("discounted_price") or 0
        count = p.get("count") or 0
        normal = (p.get("price") or 0) / (count or 1)  # price is the undiscounted line price
        insurance = p.get("insurance_price") or 0  # per insured unit
        lines.append(
            {
                "seller_item_id": p.get("_id"),
                "code": p.get("code"),
                "title": p.get("title"),
                "color": (p.get("color") or {}).get("value"),
                "seller": p.get("seller"),
                "guarantee": p.get("guarantee"),
                "payment": CLUSTER_NAMES.get(p.get("cluster_type"), p.get("cluster_type")),
                "count": count,
                "max_count": p.get("max_valid_count"),
                "over_max_count": count > (p.get("max_valid_count") or count),
                "unit_price": unit,
                "discount_pct": round(100 * (normal - unit) / normal) if normal > unit else 0,
                "insured_count": p.get("insurance_count") or 0,
                "insurance_unit_price": insurance,
                "line_total": unit * count + insurance * (p.get("insurance_count") or 0),
                "stock_text": p.get("stock_text"),
            }
        )
    box = d.get("purchase_box") or {}
    found = {line["seller_item_id"] for line in lines}
    return {
        "items": lines,
        "not_found": [i.seller_item_id for i in items if i.seller_item_id not in found],
        "price_before_discount": box.get("price"),
        "discount": box.get("discount"),
        "insurance": box.get("insurance_bill"),
        "total": box.get("final_price"),
    }


def tlp(code: str) -> str:
    """product-page, compare and comments need the TLP- form."""
    return code if code.startswith("TLP-") else f"TLP-{code}"


def _offer(o: dict[str, Any], color: str | None) -> dict[str, Any]:
    price = o.get("price") or 0
    over = expired(o.get("deadline"))  # the deal label outlives its deadline
    final = price if over else o.get("discounted_price") or price
    return {
        "seller_item_id": o.get("_id"),
        "color": color,
        "seller": o.get("seller"),
        "seller_code": o.get("seller_code"),
        "final_price": final,
        "price": price,
        "discount_pct": round(100 * (price - final) / price) if price and final < price else 0,
        "guarantee": o.get("guarantee"),
        "in_stock": bool(o.get("available")),  # the raw count is 3000 for Technolife's own stock
        "stock_text": o.get("stock_text"),
        "delivery_text": o.get("delivery_text"),
        "insurance_price": (o.get("insurance") or {}).get("bill"),
        "seller_rating": o.get("score"),
        "seller_on_time_pct": o.get("on_schedule"),
        "seller_faultless_pct": o.get("faultless"),
        "sold_by_technolife": o.get("is_techno"),
        "fast_delivery": o.get("is_turbo"),
        "deal": None if over else o.get("marketing_group") or None,
        "deal_ends": None if over else ms_to_iso(o.get("deadline")),
    }
