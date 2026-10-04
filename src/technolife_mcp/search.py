"""Search tools: typeahead, full search with prices, cheapest offers, brand lookup."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import BASE, gql
from .registry import tool

Query = Annotated[
    str, Field(min_length=2, description="Product name or words, Persian or English, e.g. 'آیفون 16' or 'لپ تاپ لنوو'.")
]
Page = Annotated[int, Field(ge=0, le=50, description="Zero-based page number.")]
SearchPage = Annotated[
    int,
    Field(
        ge=0,
        le=50,
        description="Zero-based page number. Relevance pages can repeat items; page with a price, newest or best_selling sort.",
    ),
]
MinPrice = Annotated[int | None, Field(ge=0, description="Lowest price in Toman, e.g. 50000000.")]
MaxPrice = Annotated[int | None, Field(ge=0, description="Highest price in Toman, e.g. 150000000.")]
BrandCodes = Annotated[
    list[Annotated[int, Field(ge=1)]] | None,
    Field(
        max_length=10,
        description="Brand filter codes from the `brands` list of a result or tl_find_brand, e.g. [16] (Lenovo) or [16, 19] (Lenovo or ASUS).",
    ),
]
CategoryCode = Annotated[
    int | None,
    Field(
        ge=1,
        description="Category filter code from the `categories` list of a tl_search / tl_find_cheapest result, e.g. 1 (mobile phones), to skip accessories.",
    ),
]

# Friendly sort names -> API `ordering`.
ORDERING = {
    "relevance": "kalascore",
    "best_selling": "order-desc",
    "cheapest": "price-asc",
    "most_expensive": "price-desc",
    "newest": "date-desc",
    "biggest_discount_toman": "discount-desc",
}
Sort = Literal["relevance", "best_selling", "cheapest", "most_expensive", "newest", "biggest_discount_toman"]

CARD_FIELDS = (
    "name code normal_price discount discounted_price deadline score_count score_avg available marketing_group"
)
SEARCH = (
    "query search_page_results ($text: String!, $filter: filter_obj) { search_page_results (text: $text, filter: $filter) { "
    f"results {{ {CARD_FIELDS} }} count page_filters {{ title items {{ name code }} price_range {{ min max }} }} }} }}"
)


@tool("Suggest products")
async def tl_suggest(query: Query) -> dict[str, Any]:
    """Turn a product name into Technolife product codes (typeahead, up to 30 products, no prices).

    Use to resolve a name like 'آیفون 16' to codes for tl_product / tl_compare / tl_reviews.
    For prices, filters and paging use tl_search.
    """
    data = await gql(
        "searchapi",
        "query search ($text: String!) { search (text: $text) { pages { text url } products { name code } } }",
        {"text": query},
    )
    s = data.get("search") or {}
    return {
        "products": [
            {"code": p.get("code"), "title": p.get("name"), "url": product_url(p.get("code"))}
            for p in s.get("products") or []
        ],
        "pages": [{"title": p.get("text"), "url": p.get("url")} for p in s.get("pages") or []],
    }


@tool("Search products")
async def tl_search(
    query: Query,
    sort: Annotated[
        Sort,
        Field(
            description="Order; cheapest, most_expensive and biggest_discount_toman are re-sorted on the real price after discount."
        ),
    ] = "relevance",
    in_stock: Annotated[bool, Field(description="Only products that can be ordered now.")] = True,
    min_price: MinPrice = None,
    max_price: MaxPrice = None,
    brand_codes: BrandCodes = None,
    category_code: CategoryCode = None,
    page: SearchPage = 0,
    limit: Annotated[int, Field(ge=1, le=50, description="Products per page.")] = 20,
) -> dict[str, Any]:
    """Search Technolife products with prices, discount, stock and rating.

    Also returns the top matching categories and brands with their filter codes: pass one back as
    category_code (e.g. phones, not phone cases) or brand_codes to narrow the search. For the
    cheapest offers over several pages use tl_find_cheapest; for one product's sellers,
    colors and installment prices use tl_product.
    """
    s = await _search(query, sort, in_stock, min_price, max_price, brand_codes, category_code, page, limit)
    products = resort([card(p) for p in s.get("results") or []], sort)
    return {"total": s.get("count"), "page": page, "products": products, **_facets(s)}


@tool("Find cheapest products")
async def tl_find_cheapest(
    query: Query,
    category_code: CategoryCode = None,
    brand_codes: BrandCodes = None,
    min_price: MinPrice = None,
    max_price: MaxPrice = None,
    pages: Annotated[int, Field(ge=1, le=5, description="Pages of 100 cheapest-indexed results to scan.")] = 2,
    limit: Annotated[int, Field(ge=1, le=50, description="Max products to return.")] = 20,
) -> dict[str, Any]:
    """Find the cheapest in-stock products for a search, one flat list sorted by the real price after discount.

    Use when the user wants the lowest price. Cheap accessories (cases, glass) and other
    models often match a model name ('آیفون 16' also matches Galaxy A16): check the returned
    `categories` and `brands`, call again with category_code and brand_codes, and check titles. Prices
    are the site's featured offer per product (not always the cheapest seller); tl_product shows every
    seller, color and installment price.
    """
    results = await asyncio.gather(
        *(
            _search(query, "cheapest", True, min_price, max_price, brand_codes, category_code, p, 100)
            for p in range(pages)
        )
    )
    best: dict[str, dict[str, Any]] = {}
    for s in results:
        for p in s.get("results") or []:
            c = card(p)
            if c["in_stock"] and c["final_price"] > 0:
                best.setdefault(c["code"], c)
    products = sorted(best.values(), key=lambda p: p["final_price"])
    return {"total": results[0].get("count"), "scanned": len(best), "products": products[:limit], **_facets(results[0])}


@tool("Find brand")
async def tl_find_brand(
    name: Annotated[
        str, Field(min_length=2, description="Brand name in Persian as written on the site, e.g. 'سامسونگ' or 'لنوو'.")
    ],
) -> dict[str, Any]:
    """Look up a brand by its Persian name: filter code and brand page.

    Pass brand_code in brand_codes of tl_search / tl_find_cheapest / tl_category_products, or
    brand_page as the url of tl_category_products to list all the brand's products.
    Empty list: the site spells the brand differently (هوآوی, not هواوی); call tl_search with
    the name and take the code from its `brands` facet.
    """
    data = await gql(
        "searchapi",
        "query similar_brands ($brand_name: String) { similar_brands (brand_name: $brand_name) { brandName brandEnName code Percentage } }",
        {"brand_name": name.strip()},
    )
    return {
        "brands": [
            {
                "brand_code": int(b["code"].removeprefix("BR-")) if (b.get("code") or "").startswith("BR-") else None,
                "name": b.get("brandName"),
                "en_name": b.get("brandEnName"),
                # ponytail: brand page slug guessed from the English name (true for every brand checked)
                "brand_page": f"brand/{b['brandEnName'].lower().replace(' ', '-')}" if b.get("brandEnName") else None,
                "match_pct": b.get("Percentage"),
            }
            for b in data.get("similar_brands") or []
        ]
    }


async def _search(
    query: str,
    sort: str,
    in_stock: bool,
    min_price: int | None,
    max_price: int | None,
    brand_codes: list[int] | None,
    category_code: int | None,
    page: int,
    limit: int,
) -> dict[str, Any]:
    flt: dict[str, Any] = {"limit": limit, "skip": page, "ordering": ORDERING[sort]}  # skip is a page index
    if in_stock:
        flt["available"] = True
    if min_price is not None:
        flt["price_min"] = min_price
    if max_price is not None:
        flt["price_max"] = max_price
    if brand_codes:
        flt["brand_filters"] = brand_codes
    if category_code:
        flt["category_filters"] = [category_code]
    data = await gql("searchapi", SEARCH, {"text": query, "filter": flt})
    return data.get("search_page_results") or {}


def _facets(s: dict[str, Any]) -> dict[str, Any]:
    """Top categories and brands of a search ('name: count' or 'name (count)' labels) and its price range."""
    out: dict[str, Any] = {"categories": [], "brands": [], "price_range": None}
    for f in s.get("page_filters") or []:
        title = f.get("title") or ""
        key = "brands" if "برند" in title else "categories" if "دسته" in title else None
        if f.get("price_range") and out["price_range"] is None:
            out["price_range"] = f["price_range"]
        if not key:
            continue
        for item in [i for i in f.get("items") or [] if i and str(i.get("code")).isdigit()][:10]:
            label = item.get("name") or ""
            m = re.fullmatch(r"(.+?)(?:: | \()(\d+)\)?", label)
            out[key].append(
                {
                    "code": int(item["code"]),
                    "name": m[1] if m else label,
                    "count": int(m[2]) if m else None,
                }
            )
    return out


def resort(products: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    """The API price and discount sorts follow an indexed price that lags timed deals; re-sort the page."""
    if sort in ("cheapest", "most_expensive"):
        products.sort(key=lambda p: p["final_price"], reverse=sort == "most_expensive")
    elif sort == "biggest_discount_toman":
        products.sort(key=lambda p: p["final_price"] - p["price"])
    return products


def card(p: dict[str, Any]) -> dict[str, Any]:
    """Compact product card from any product list (search, category, seller, deals)."""
    price = p.get("normal_price") or 0
    # Category and seller lists keep a discount after its deadline; the product page no longer applies it.
    over = expired(p.get("deadline"))
    # Lists send discounted_price null (category) or equal to the price (search) when there is no discount.
    final = price if over else p.get("discounted_price") or price
    return {
        "code": p.get("code"),
        "title": p.get("name"),
        "final_price": final,
        "price": price,
        "discount_pct": round(100 * (price - final) / price) if price and final < price else 0,
        "in_stock": bool(p.get("available")),
        "rating": rating(p.get("score_avg"), p.get("score_count")),
        "rating_count": p.get("score_count"),
        "deal": None if over else p.get("marketing_group") or None,
        "deal_ends": None if over else ms_to_iso(p.get("deadline")),
        "url": product_url(p.get("code")),
    }


def rating(avg: Any, count: Any) -> float | None:
    """Scores are 0-5 already; 0 with no votes means not rated yet."""
    return round(avg, 1) if avg and count else None


def deadline(value: Any) -> datetime | None:
    """Discount deadlines are epoch-millisecond strings, or ISO strings on some cards."""
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def expired(value: Any) -> bool:
    """True when a discount deadline has passed."""
    d = deadline(value)
    return d is not None and d.timestamp() < time.time()


def ms_to_iso(value: Any) -> str | None:
    d = deadline(value)
    return d.astimezone(timezone.utc).isoformat(timespec="minutes") if d else None


def product_url(code: str | None) -> str | None:
    return f"{BASE}/product-{code.removeprefix('TLP-')}" if code else None
