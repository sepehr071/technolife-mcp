"""Catalog tools: category tree, category/brand/promotion product lists and their filters."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import ApiError, GraphQLError, gql
from .registry import tool
from .search import CARD_FIELDS, ORDERING, BrandCodes, MaxPrice, MinPrice, Page, card, resort

PageUrl = Annotated[
    str,
    Field(
        pattern=r"^(https://www\.technolife\.(com|ir))?/?(category|brand|promotion)/\S+$",
        description="Page path from tl_categories / tl_find_brand / tl_campaigns, e.g. 'category/laptop-equipment/laptop', 'brand/samsung' or 'promotion/power48'.",
    ),
]

MENU_PRODUCTS = (
    "query get_menu_products ($url: String, $filterObj: filter_obj) { get_menu_products (url: $url, filterObj: $filterObj) { "
    f"results {{ {CARD_FIELDS} }} count }} }}"
)
MENU_FILTERS = (
    "query get_menu_filters ($url: String, $filterObj: filter_obj) { get_menu_filters (url: $url, filterObj: $filterObj) { "
    "page_filters { title price_range { min max } items { name code enName } } } }"
)
PAGE_HINT = "Get urls from tl_categories, tl_find_brand or tl_campaigns."
# ponytail: options per attribute capped to keep the reply small (laptop GPU models alone have 107);
# add an attribute-title argument if the tail is ever needed.
MAX_OPTIONS = 10


@tool("Categories")
async def tl_categories(
    query: Annotated[
        str | None,
        Field(min_length=2, description="Find categories whose name contains this, e.g. 'لپ تاپ گیمینگ' or 'هدفون'."),
    ] = None,
    url: Annotated[
        str | None,
        Field(
            pattern=r"^/?category/\S+$",
            description="List the sub-pages (brands, series) of this category, e.g. 'category/mobile/mobile-phone'.",
        ),
    ] = None,
) -> dict[str, Any]:
    """Find category pages and their urls for tl_category_products.

    - With query: categories anywhere in the menu whose name matches (best way to get a url).
    - With url: that category's sub-pages (brand and series pages).
    - With neither: the top-level categories and the titles of their children (get a child's url with query).
    """
    if url:
        data = await gql(
            "shop_tree_ts",
            "query getSubBreadCrumbProductList ($url: String!) { getSubBreadCrumbProductList (url: $url) { name url } }",
            {"url": "/" + url.lstrip("/")},
        )
        return {
            "categories": [
                {"title": c.get("name"), "url": _page(c.get("url"))}
                for c in data.get("getSubBreadCrumbProductList") or []
            ]
        }

    tree = (await gql("shop_tree_ts", "query { getNavBar }")).get("getNavBar") or {}
    if query:
        q, found, seen = _norm(query), [], set()

        def walk(nodes: list[dict[str, Any]], path: str) -> None:
            for n in nodes:
                title = (n.get("title") or "").strip()
                u = _page(n.get("url_name"))
                if u and u not in seen and q in _norm(title):
                    seen.add(u)
                    found.append({"title": title, "url": u, "path": path})
                walk(n.get("children") or [], f"{path} > {title}" if path else title)

        walk(tree.get("children") or [], "")
        return {"categories": found[:30], "found": len(found)}

    return {
        "categories": [
            {
                "title": (top.get("title") or "").strip(),
                "url": _page(top.get("url_name")),
                "children": [
                    (c.get("title") or "").strip() for c in top.get("children") or [] if _page(c.get("url_name"))
                ],
            }
            for top in tree.get("children") or []
        ]
    }


@tool("Browse a category or brand")
async def tl_category_products(
    url: PageUrl,
    sort: Annotated[
        Literal["best_selling", "cheapest", "most_expensive", "newest", "biggest_discount_toman"],
        Field(
            description="Order; cheapest, most_expensive and biggest_discount_toman are re-sorted on the real price after discount within the page."
        ),
    ] = "best_selling",
    in_stock: Annotated[bool, Field(description="Only products that can be ordered now.")] = True,
    min_price: MinPrice = None,
    max_price: MaxPrice = None,
    brand_codes: BrandCodes = None,
    attribute_codes: Annotated[
        list[Annotated[int, Field(ge=1)]] | None,
        Field(
            max_length=10,
            description="Attribute filter codes from tl_category_filters (all must match), e.g. [4447] for 16 GB RAM laptops.",
        ),
    ] = None,
    category_codes: Annotated[
        list[Annotated[int, Field(ge=1)]] | None,
        Field(
            max_length=10,
            description="Category filter codes from the `categories` of tl_category_filters (brand and promotion pages), e.g. [1] for phones.",
        ),
    ] = None,
    fast_delivery: Annotated[
        bool, Field(description="Only items shipped quickly from Technolife's own stock.")
    ] = False,
    page: Page = 0,
    limit: Annotated[int, Field(ge=1, le=50, description="Products per page.")] = 20,
) -> dict[str, Any]:
    """List the products of a category, brand or promotion page with prices, discount, stock and rating.

    Use to browse a product type (laptops, phones) or brand sorted by price or popularity,
    with filters. Get brand and attribute codes (RAM, screen size, CPU...) and the price range
    from tl_category_filters first. For free text use tl_search.
    """
    page_url, flt = _filter_obj(url)
    flt.update({"limit": limit, "skip": page, "ordering": ORDERING[sort]})  # skip is a page index
    if in_stock:
        flt["available"] = True
    if min_price is not None:
        flt["price_min"] = min_price
    if max_price is not None:
        flt["price_max"] = max_price
    if brand_codes:
        flt["brand_filters"] = brand_codes
    if attribute_codes:
        flt["attribute_filters"] = attribute_codes
    if category_codes:
        flt["category_filters"] = category_codes
    if fast_delivery:
        flt["available_in_stock"] = True
    try:
        data = await gql("shop_plp", MENU_PRODUCTS, {"url": page_url, "filterObj": flt})
    except GraphQLError as e:
        # The site also answers this error when no product is priced inside min_price..max_price.
        why = "no product in that price range, or an unknown url" if min_price or max_price else "an unknown url"
        raise ApiError(f"Could not load page '{url}' ({e}; {why}). {PAGE_HINT}") from e
    d = data.get("get_menu_products") or {}
    products = resort([card(p) for p in d.get("results") or []], sort)
    return {"total": d.get("count"), "page": page, "products": products}


@tool("Category filters")
async def tl_category_filters(url: PageUrl) -> dict[str, Any]:
    """List the filters of a category, brand or promotion page: brands, categories, price range and attributes with their codes.

    Use before tl_category_products to filter by brand (brand_codes), by category on brand
    and promotion pages (category_codes) or by attributes such as RAM, screen size, CPU
    series or usage (attribute_codes).
    """
    page_url, flt = _filter_obj(url)
    try:
        data = await gql("shop_plp", MENU_FILTERS, {"url": page_url, "filterObj": flt})
    except GraphQLError as e:
        raise ApiError(f"Could not load the filters of '{url}' ({e}). {PAGE_HINT}") from e
    out: dict[str, Any] = {"price_range": None, "brands": [], "categories": [], "attributes": []}
    for f in (data.get("get_menu_filters") or {}).get("page_filters") or []:
        # colors use hex codes and can contain null items
        items = [i for i in f.get("items") or [] if i and str(i.get("code") or "").isdigit()]
        title = f.get("title") or ""
        if f.get("price_range"):
            out["price_range"] = f["price_range"]
        elif "برند" in title:
            out["brands"] = [{"code": int(i["code"]), "name": i.get("name"), "en_name": i.get("enName")} for i in items]
        elif "دسته" in title:
            out["categories"] = [{"code": int(i["code"]), "name": (i.get("name") or "").strip()} for i in items]
        elif items:
            out["attributes"].append(
                {
                    "title": title.strip(),
                    "options": [
                        {"code": int(i["code"]), "name": (i.get("name") or "").strip()} for i in items[:MAX_OPTIONS]
                    ],
                    "options_total": len(items),
                }
            )
    return out


def _filter_obj(url: str) -> tuple[str, dict[str, Any]]:
    """Category/brand pages take the path; promotion pages take only the promotion code."""
    path = re.sub(r"^https://www\.technolife\.(com|ir)", "", url).strip("/")
    if path.startswith("promotion/"):
        return path.split("/")[1], {"page_type": "promotion"}
    return path, {"page_type": "dynamic"}


def _page(url: str | None) -> str | None:
    """Menu links usable by tl_category_products, without the leading slash."""
    u = (url or "").lstrip("/")
    return u if u.startswith(("category/", "brand/", "promotion/")) else None


def _norm(text: str) -> str:
    """Match Persian text regardless of Arabic ي/ك, half-spaces and case."""
    text = text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").lower()
    return " ".join(text.split())
