"""Offer tools: discount lists, campaigns, sellers."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated, Any, Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field

from .http import BASE, ApiError, GraphQLError, gql
from .registry import tool
from .search import CARD_FIELDS, ORDERING, Page, card, resort

SPECIAL = (
    "query marketing_group_results ($marketing_group: String, $filter: filter_obj) { marketing_group_results (marketing_group: $marketing_group, filter: $filter) { "
    f"results {{ {CARD_FIELDS} }} count }} }}"
)
HOME = (
    "query { get_landing_page { type componentConfig { title } banners { link title alt } "
    "product_tabs { TabTitle TabContent { name code normal_price discount discounted_price marketing_group available deadline } } } }"
)
LANDING = (
    "query get_landing_page_daynamic ($code: String, $device_type: String, $landing_type: String) { "
    "get_landing_page_daynamic (code: $code, device_type: $device_type, landing_type: $landing_type) { code meta_title "
    "components { name component_type carousel { related_page_link products { name code normal_price discount discounted_price marketing_group available deadline } } "
    "banners { link title } } } }"
)
SELLER = (
    "query get_seller_product_list ($seller_codes: [String], $filterObj: filter_obj) { get_seller_product_list (seller_codes: $seller_codes, filterObj: $filterObj) { "
    f"results {{ {CARD_FIELDS} }} sellers_info {{ code fa_name en_name score on_schedule faultless supply joined_duration {{ years months days }} }} count }} }}"
)

MAIN_DEALS = "1"  # /product/list/special/1, the main discount list (تکنوآف)
TIMED_SECTIONS = {"ProductTechnoOffBanner", "SpecialEventCarousel", "SpecialCarousel"}  # timed home-page deals


@tool("Deals")
async def tl_deals(
    sort: Annotated[
        Literal["biggest_percent", "biggest_discount_toman", "cheapest", "best_selling", "newest"],
        Field(description="Order; biggest_percent re-sorts a page of the largest Toman discounts by percent."),
    ] = "biggest_percent",
    min_discount_pct: Annotated[int, Field(ge=0, le=99, description="Only deals with at least this percent off.")] = 0,
    page: Page = 0,
    limit: Annotated[int, Field(ge=1, le=100, description="Max deals to return (and max timed deals).")] = 15,
) -> dict[str, Any]:
    """List current in-stock discounts (Technolife's main deal list, تکنوآف) and, on page 0, the timed home-page deals (تکنو تایم).

    Use for "best deals right now". deal_ends is when the discount stops (UTC). total is the
    size of the whole deal list, before min_discount_pct. With biggest_percent or
    min_discount_pct each page scans the next 100 deals and returns the best `limit` of them;
    more_on_page counts the matches cut off (raise limit to see them). For discounts inside
    one category use tl_category_products with sort=biggest_discount_toman.
    """
    ordering = ORDERING["biggest_discount_toman" if sort == "biggest_percent" else sort]
    # biggest_percent: the API only orders by Toman amount, so take a wide page and re-sort it.
    # min_discount_pct: filter a wide page so `limit` deals can still be found.
    size = 100 if sort == "biggest_percent" or min_discount_pct else limit
    flt = {"limit": size, "skip": page, "ordering": ordering, "available": True}
    calls = [gql("shop_plp", SPECIAL, {"marketing_group": MAIN_DEALS, "filter": flt})]
    if page == 0:
        calls.append(gql("shop_landing", HOME))
    results = await asyncio.gather(*calls)
    d = results[0].get("marketing_group_results") or {}
    deals = [
        c for c in map(card, d.get("results") or []) if c["in_stock"] and c["discount_pct"] >= max(min_discount_pct, 1)
    ]
    if sort == "biggest_percent":
        deals.sort(key=lambda c: -c["discount_pct"])
    resort(deals, sort)
    out: dict[str, Any] = {
        "total": d.get("count"),
        "page": page,
        "deals": deals[:limit],
        "more_on_page": max(0, len(deals) - limit),
    }
    if page == 0:
        out["timed_deals"] = [
            {
                **c,
                # the تکنوآف banner and the special carousel have no section title
                "section": (s.get("componentConfig") or {}).get("title")
                or ("تکنوآف" if s.get("type") == "ProductTechnoOffBanner" else tab.get("TabTitle")),
            }
            for s in results[1].get("get_landing_page") or []
            if s.get("type") in TIMED_SECTIONS
            for tab in s.get("product_tabs") or []
            for c in map(card, tab.get("TabContent") or [])
            if c["in_stock"] and c["discount_pct"] >= max(min_discount_pct, 1)
        ][:limit]
    return out


@tool("Campaigns")
async def tl_campaigns(
    code: Annotated[
        str | None,
        Field(
            pattern=r"^[A-Za-z0-9_-]{2,60}$",
            description="Campaign landing code from this tool's list, e.g. 'payday-technolife'. Omit to list current campaigns.",
        ),
    ] = None,
    products_per_section: Annotated[
        int, Field(ge=0, le=20, description="Products to show per carousel of a campaign.")
    ] = 3,
) -> dict[str, Any]:
    """List current campaigns, or show one campaign's sections and products.

    - Without code: campaign landings (code) and promotion pages (page_url) linked from the home page.
    - With code: the campaign's carousels with a few products each, and its links.
    Pass a page_url to tl_category_products to list all of its products with filters
    (products_in_carousel counts only the carousel, not the page).
    """
    if code is None:
        data = await gql("shop_landing", HOME)
        campaigns, seen = [], set()
        for s in data.get("get_landing_page") or []:
            for b in s.get("banners") or []:
                link = _link(b.get("link"))
                if link and link["kind"] in ("landing", "promotion") and str(link) not in seen:
                    seen.add(str(link))
                    campaigns.append({"title": b.get("title") or b.get("alt"), **link})
        return {"campaigns": campaigns}

    data = await gql("shop_landing", LANDING, {"code": code, "device_type": "desktop", "landing_type": "landing"})
    d = data.get("get_landing_page_daynamic") or {}
    if not d.get("code"):
        raise ApiError(f"Unknown campaign code '{code}'. Call tl_campaigns without a code to list current campaigns.")
    sections = []
    for c in d.get("components") or []:
        carousel = c.get("carousel") or {}
        products = [card(p) for p in carousel.get("products") or []]
        links = [{"title": b.get("title"), **lk} for b in c.get("banners") or [] if (lk := _link(b.get("link")))]
        if not products and not links:
            continue
        section: dict[str, Any] = {"name": c.get("name"), "links": links}
        if products:
            section["page_url"] = (_link(carousel.get("related_page_link")) or {}).get("page_url")
            section["products_in_carousel"] = len(products)
            section["products"] = products[:products_per_section]
        sections.append(section)
    return {"code": code, "title": d.get("meta_title"), "sections": sections}


@tool("Seller")
async def tl_seller(
    seller_code: Annotated[
        str,
        Field(
            pattern=r"^(TLS-)?\d{1,9}$",
            description="Seller code from tl_product offers, e.g. 'TLS-15172' (the bare number works too).",
        ),
    ],
    sort: Annotated[
        Literal["best_selling", "cheapest", "most_expensive", "newest", "biggest_discount_toman"],
        Field(description="Order of the seller's products."),
    ] = "best_selling",
    in_stock: Annotated[bool, Field(description="Only products that can be ordered now.")] = True,
    page: Page = 0,
    limit: Annotated[int, Field(ge=1, le=50, description="Products per page.")] = 20,
) -> dict[str, Any]:
    """Get a marketplace seller's reputation (rating 0-5, on-time %, fault-free %, time on Technolife) and its products.

    Use to judge a seller found in tl_product offers before recommending its offer.
    """
    flt: dict[str, Any] = {"limit": limit, "skip": page, "ordering": ORDERING[sort]}
    if in_stock:
        flt["available"] = True
    try:
        data = await gql("shop_plp", SELLER, {"seller_codes": [seller_code.removeprefix("TLS-")], "filterObj": flt})
    except GraphQLError:
        data = {}  # an unknown seller answers a GraphQL "server error"
    d = data.get("get_seller_product_list") or {}
    info = d.get("sellers_info")
    if not info:
        raise ApiError(f"Unknown seller {seller_code}. Seller codes come from tl_product offers (seller_code).")
    joined = info.get("joined_duration") or {}
    products = resort([card(p) for p in d.get("results") or []], sort)
    return {
        "seller": {
            "code": info.get("code"),
            "name": info.get("fa_name"),
            "en_name": info.get("en_name"),
            "rating": info.get("score"),
            "on_time_pct": info.get("on_schedule"),
            "faultless_pct": info.get("faultless"),
            "supply_pct": info.get("supply"),
            "joined": f"{joined.get('years') or 0}y {joined.get('months') or 0}m",
        },
        "total": d.get("count"),
        "page": page,
        "products": products,
    }


def _link(link: str | None) -> dict[str, Any] | None:
    """Classify a site link: campaign landing, promotion/category/brand page, product, or other."""
    if not link:
        return None
    parts = urlsplit(link)
    if parts.netloc and not parts.netloc.endswith("technolife.com"):
        return None  # partner sites (TechnoPay, loan apps)
    path = unquote(parts.path).strip("/")
    if path.startswith("landings/"):
        return {"kind": "landing", "code": path.split("/")[1]}
    if path.startswith("promotion/"):
        return {"kind": "promotion", "page_url": "promotion/" + path.split("/")[1]}
    if path.startswith(("category/", "brand/")):
        return {"kind": path.split("/")[0], "page_url": path}
    if m := re.match(r"product-(\d+)", path):
        return {"kind": "product", "code": f"TLP-{m[1]}"}
    return {"kind": "other", "url": f"{BASE}/{path}"}
