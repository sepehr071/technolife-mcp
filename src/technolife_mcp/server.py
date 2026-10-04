"""MCP server entry point: registers every read-only Technolife tool."""

import logging

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from . import __version__, catalog, info, offers, product, search  # noqa: F401  (imports register the tools)
from .registry import TOOLS

INSTRUCTIONS = """\
Unofficial, read-only access to Technolife (technolife.com), an Iranian electronics retailer and
marketplace (phones, laptops, home appliances, accessories). Nothing here can log in, save a basket
or order.

Workflow:
1. Find products: tl_search (prices, filters, facets), tl_find_cheapest (one flat cheapest-first list),
   tl_suggest (name -> code). For one model also pass brand_codes and category_code and check
   titles: searches match loosely ('آیفون 16' also finds Galaxy A16). Browse with tl_categories -> tl_category_filters -> tl_category_products;
   brands with tl_find_brand.
2. One product: tl_product (every seller, color, warranty, stock, delivery, installment prices, specs),
   then tl_reviews, tl_compare (2-5 products), tl_seller (seller reputation).
3. Final total incl. insurance, quantity limits and installment surcharge: tl_price_basket with
   seller_item_id values from tl_product.
4. Deals: tl_deals, tl_campaigns. Shop rules: tl_store_info (branches, shipping, returns, payment),
   tl_faq, tl_shop_reviews. Addresses: tl_find_location, tl_reverse_geocode.

Conventions: all prices are Toman (the API is Toman; 1 Toman = 10 Rial). final_price is the price
after discount; discount_pct is computed from the two prices. Ratings are 0-5, null = not rated.
Product codes look like 'TLP-60492', sellers 'TLS-15172'. List results show the site's featured
offer per product, which is not always the cheapest; tl_product has the full offer list. Shipping cost is not included anywhere (it needs a
logged-in address). Persian queries match best ('آیفون 16', 'لپ تاپ لنوو').
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

mcp = MCPServer(
    "technolife-mcp",
    title="Technolife",
    instructions=INSTRUCTIONS,
    version=__version__,
    website_url="https://github.com/sepehr071/technolife-mcp",
)

for fn, title in TOOLS:
    mcp.add_tool(fn, title=title, annotations=READ_ONLY)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request floods client logs
    mcp.run()


if __name__ == "__main__":
    main()
