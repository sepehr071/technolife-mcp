"""Shop info tools: branches, shipping and return rules, FAQ, shop reviews, address lookup."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Annotated, Any, Literal

from pydantic import Field

from .http import BASE, ApiError, fetch, gql
from .registry import tool

# Static content pages by number.
PAGES = {"branches": "55", "shipping": "9", "returns": "8", "payment_methods": "7"}


@tool("Shop info")
async def tl_store_info(
    topic: Annotated[
        Literal["branches", "shipping", "returns", "payment_methods"],
        Field(
            description="branches (physical stores, hours, phones), shipping (methods and costs), returns (7-day return guarantee), payment_methods (online, in store, installments)."
        ),
    ],
) -> dict[str, Any]:
    """Read one of Technolife's info pages as plain text.

    Use for questions about physical stores, how and how much shipping costs per city,
    returns and how to pay. Exact shipping cost of an order needs a logged-in address,
    so quote the rules from here. For other questions try tl_faq.
    """
    data = await gql(
        "shop_static_page",
        "query get_static_pages ($page_number: String) { get_static_pages (page_number: $page_number) { static_pages { meta_title content canonical } } }",
        {"page_number": PAGES[topic]},
    )
    pages = (data.get("get_static_pages") or {}).get("static_pages") or []
    if not pages:
        raise ApiError(f"Technolife returned no '{topic}' page.")
    p = pages[0]
    return {
        "title": p.get("meta_title"),
        "text": html_text(p.get("content")),
        "url": f"{BASE}/staticpage/page-{PAGES[topic]}",
    }


@tool("Search FAQ")
async def tl_faq(
    query: Annotated[
        str, Field(min_length=2, description="One or two Persian words, e.g. 'ارسال', 'اقساط', 'مرجوعی', 'گارانتی'.")
    ],
) -> dict[str, Any]:
    """Search Technolife's help-center FAQ and return matching questions with plain-text answers.

    Use for policy questions (installments, delivery, returns, warranty, invoices). Short
    single words match best; an empty list means try another word or tl_store_info.
    """
    data = await gql(
        "shop_customer",
        "query get_search_faq ($search: String) { get_search_faq (search: $search) { question answer } }",
        {"search": query.strip()},
    )
    return {
        "results": [
            {"question": f.get("question"), "answer": html_text(f.get("answer"))}
            for f in data.get("get_search_faq") or []
        ]
    }


@tool("Shop reviews")
async def tl_shop_reviews(
    page: Annotated[int, Field(ge=0, le=100, description="Zero-based page number, newest first.")] = 0,
    limit: Annotated[int, Field(ge=1, le=50, description="Reviews per page.")] = 10,
) -> dict[str, Any]:
    """Read customer reviews of the Technolife shop itself (service, delivery), newest first, rating 1-5, with staff replies.

    Use to judge the shop rather than a product (for a product use tl_reviews). Dates are
    Jalali; the newest reviews on the site may be a few years old.
    """
    data = await gql(
        "comment",
        "query get_article_comments ($limit: Int, $skip: Int) { get_article_comments (limit: $limit, skip: $skip) { count comments { name body date_added score answer { body } } } }",
        {"limit": limit, "skip": page},  # skip is a page index
    )
    d = data.get("get_article_comments") or {}
    return {
        "count": d.get("count"),
        "page": page,
        "reviews": [
            {
                "date": c.get("date_added"),
                "author": c.get("name"),
                "rating": c.get("score"),
                "text": c.get("body"),
                "reply": html_text((c.get("answer") or {}).get("body")) or None,
            }
            for c in d.get("comments") or []
        ],
    }


@tool("Find location")
async def tl_find_location(
    query: Annotated[
        str,
        Field(
            min_length=2,
            description="Address, street or landmark, Persian works best, e.g. 'میدان ونک' or 'شیراز خیابان زند'.",
        ),
    ],
    limit: Annotated[int, Field(ge=1, le=20, description="Max places to return.")] = 5,
) -> dict[str, Any]:
    """Turn an address or landmark into coordinates with its province and city.

    Use to tell which city an address is in (shipping methods depend on the city, see
    tl_store_info topic=shipping) or to find the nearest branch.
    """
    body = await fetch(f"{BASE}/map_forward", {"search_text": query})
    _check_map(body)
    places = []
    for r in (body.get("results") or [])[:limit]:
        geo = r.get("geo_location") or {}
        center = geo.get("center") or {}
        subs = r.get("subdivisions") or {}
        places.append(
            {
                "name": geo.get("title"),
                "description": r.get("description"),
                "lat": center.get("lat"),
                "long": center.get("lng"),
                "province": (subs.get("ostan") or {}).get("title"),
                "city": (subs.get("shahr") or {}).get("title"),
                "type": geo.get("category"),
            }
        )
    return {"places": places}


@tool("Describe coordinates")
async def tl_reverse_geocode(
    lat: Annotated[float, Field(ge=24, le=40, description="Latitude (Iran: ~25 to ~40), e.g. 35.7575.")],
    long: Annotated[float, Field(ge=44, le=64, description="Longitude (Iran: ~44 to ~63), e.g. 51.4106.")],
) -> dict[str, Any]:
    """Describe coordinates as an address with province, city and neighbourhood.

    Use to confirm a delivery point with the user, or to get the city for shipping rules.
    """
    body = await fetch(f"{BASE}/map_reverse", {"location": f"{long},{lat}"})  # lng,lat order
    _check_map(body)
    subs = body.get("subdivisions") or {}
    return {
        "address": body.get("address"),
        "province": (subs.get("ostan") or {}).get("title"),
        "city": (subs.get("shahr") or {}).get("title"),
        "areas": [g.get("title") for g in body.get("geofences") or [] if g.get("id")],  # id 0 = no area registered
    }


def _check_map(body: Any) -> None:
    if not isinstance(body, dict) or body.get("status") != "OK":
        raise ApiError(f"Technolife's map service rejected the request: {str(body)[:200]}")


class _Text(HTMLParser):
    BLOCKS = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.BLOCKS:
            self.parts.append("\n")
        if tag == "a":
            self.href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href and self.href.startswith("http"):
            self.parts.append(f" ({self.href})")  # FAQ answers often just point to a guide page
            self.href = None

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_text(html: str | None) -> str:
    """HTML to plain text, one line per block, without soft hyphens or empty lines."""
    parser = _Text()
    parser.feed(html or "")
    lines = (" ".join(line.replace("\xad", "").split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)
