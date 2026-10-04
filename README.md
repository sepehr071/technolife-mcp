<!-- mcp-name: io.github.sepehr071/technolife-mcp -->

<div align="center">

<img src="https://raw.githubusercontent.com/sepehr071/technolife-mcp/main/.github/banner.png" alt="technolife-mcp: let your AI agent compare every seller on Technolife" width="100%">

# 📱 technolife-mcp

**Let your AI agent shop around on Technolife.**<br>
Search phones, laptops and appliances, compare every seller's cash and installment price,<br>
read specs and reviews, and catch today's deals, all from Claude, Cursor or Copilot.

[![PyPI](https://img.shields.io/pypi/v/technolife-mcp?color=2563eb)](https://pypi.org/project/technolife-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/technolife-mcp)](https://pypi.org/project/technolife-mcp/)
[![CI](https://github.com/sepehr071/technolife-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sepehr071/technolife-mcp/actions/workflows/ci.yml)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-io.github.sepehr071%2Ftechnolife--mcp-7c3aed)](https://registry.modelcontextprotocol.io/?q=technolife-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-16a34a)](https://github.com/sepehr071/technolife-mcp/blob/main/LICENSE)

[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en/install-mcp?name=technolife&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJ0ZWNobm9saWZlLW1jcCJdfQ==)
[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_technolife--mcp-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=technolife&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22technolife-mcp%22%5D%7D)

[Quick start](#quick-start) · [What it can do](#what-it-can-do) · [Tools](#tools) · [FAQ](#faq) · [فارسی](#فارسی)

</div>

---

## Why

On Technolife one product page hides several sellers, colors, warranties and three price lists
(cash, installment, buy now pay later). Finding *the best offer* means clicking through each of them.
An agent with `technolife-mcp` reads them all at once:

> **You:** Where is the Lenovo IdeaPad Slim 3 i3 1315U cheapest on Technolife, and what does it cost in installments?
>
> **Agent:** *calls* `tl_suggest(query="IdeaPad Slim 3 i3 1315U")` → `tl_product(product_code="TLP-60492")`
>
> | Seller | Cash | Installment | Buy now pay later | Warranty |
> |---|---:|---:|---:|---|
> | ایران پشتیبان | **125,000,000** | 128,750,000 | 135,000,000 | 18 months |
> | چیتک شاپ | 129,500,000 | 133,385,000 | 139,860,000 | 18 months |
> | دیباکام | 130,000,000 | 133,900,000 | 140,400,000 | 18 months (Dibacom) |
>
> ایران پشتیبان is cheapest in every price list and ships the next working day; device insurance adds 2,375,000.
> Want me to check the exact total with insurance using `tl_price_basket`?

<sub>Real tool output from 2026-10-03; prices change all the time. Prices are in Toman.</sub>

## What it can do

- 🔎 **Search** the whole catalog with prices, stock, rating, price range and brand/category filters
- 💸 **Find the cheapest** in-stock offers, re-sorted on the real price after discount
- 🏷️ **Compare sellers** of one product: price per color, warranty, stock, delivery time, seller reputation
- 💳 **See installment prices** (installment and buy now pay later) next to cash, and price a basket with insurance
- 📋 **Read specs** and compare up to 5 products side by side
- ⭐ **Check quality** with customer reviews, star distribution and the site's AI review summary
- ⚡ **Catch deals**: the main discount list, timed deals (تکنو تایم) and current campaigns
- 🔒 **Read-only by design**: no login, no basket, no orders, no payment

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/).

<details open>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add technolife -- uvx technolife-mcp
```
</details>

<details>
<summary><b>Claude Desktop</b></summary>

Settings → Developer → Edit Config, then add:

```json
{
  "mcpServers": {
    "technolife": { "command": "uvx", "args": ["technolife-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Cursor</b></summary>

Click **Install in Cursor** above, or add the Claude Desktop block to `~/.cursor/mcp.json`.
</details>

<details>
<summary><b>VS Code (Copilot agent mode)</b></summary>

Click **Install in VS Code** above, or add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "technolife": { "type": "stdio", "command": "uvx", "args": ["technolife-mcp"] }
  }
}
```
</details>

<details>
<summary><b>Anything else</b></summary>

It's a standard stdio MCP server: run `uvx technolife-mcp`, or `pip install technolife-mcp` and run `technolife-mcp`.
</details>

Then just ask:

- "Cheapest in-stock Lenovo laptop with 16 GB RAM on Technolife?"
- "Compare the iPhone 16 and iPhone 17: price, camera, battery."
- "Which deals on Technolife have more than 50% off right now?"
- <span dir="rtl">ارزان&zwnj;ترین گوشی سامسونگ با قیمت اقساطی در تکنولایف؟</span>

## How it works

```text
  AI agent  (Claude, Cursor, Copilot, ...)
      │
      │  MCP over stdio
      ▼
  technolife-mcp  (runs on your machine)
      │
      │  HTTPS (GraphQL)
      └──────▶  www.technolife.com
```

`technolife-mcp` runs locally and calls the same public endpoints the technolife.com website uses.
There's no hosted server in between, no API key, and nothing about you is sent anywhere else.

## Tools

Products are identified by codes like `TLP-60492` and sellers by `TLS-15172`. List tools return the
site's featured offer per product, which is not always the cheapest seller; `tl_product` returns every
seller, color and price list.

<details open>
<summary><b>🔎 Search</b> (4)</summary>

| Tool | What it does |
|---|---|
| `tl_search` | Search with prices, stock, rating; filters for price, brand, category; category/brand facets with their codes |
| `tl_find_cheapest` | Cheapest in-stock products for a search, one flat list sorted by the real price |
| `tl_suggest` | Product name → product codes (typeahead) |
| `tl_find_brand` | Brand name → brand filter code and brand page |
</details>

<details open>
<summary><b>🗂️ Catalog</b> (3)</summary>

| Tool | What it does |
|---|---|
| `tl_categories` | Find category pages by name, list the top level, or a category's sub-pages |
| `tl_category_products` | Products of a category, brand or promotion page, sorted and filtered |
| `tl_category_filters` | A page's brands, categories, price range and attribute filters (RAM, screen, CPU, ...) with codes |
</details>

<details open>
<summary><b>📦 Product</b> (4)</summary>

| Tool | What it does |
|---|---|
| `tl_product` | Every offer: seller, color, warranty, stock, delivery, insurance, installment prices, specs |
| `tl_compare` | 2-5 products side by side: price, stock, rating, every spec |
| `tl_reviews` | Customer reviews, star distribution and the AI summary with pros and cons |
| `tl_price_basket` | Exact total for seller items: discounts, insurance, quantity limits, cash vs installment |
</details>

<details open>
<summary><b>⚡ Deals and sellers</b> (3)</summary>

| Tool | What it does |
|---|---|
| `tl_deals` | Current discounts (biggest percent first) and timed home-page deals |
| `tl_campaigns` | Current campaigns, or one campaign's sections and products |
| `tl_seller` | A seller's rating, on-time and fault-free percentages, and its products |
</details>

<details open>
<summary><b>ℹ️ Shop info</b> (5)</summary>

| Tool | What it does |
|---|---|
| `tl_store_info` | Physical stores, shipping methods and costs, 7-day returns, payment methods |
| `tl_faq` | Search the help-center FAQ |
| `tl_shop_reviews` | Customer reviews of the shop itself |
| `tl_find_location` | Address or landmark → coordinates, province and city |
| `tl_reverse_geocode` | Coordinates → address, province, city and neighbourhood |
</details>

All 19 tools are annotated `readOnlyHint: true` and return compact structured JSON, so they don't flood the agent's context.

## Good to know

- **Prices are in Toman**, as on the site (1 Toman = 10 Rial). `final_price` is after discount; `discount_pct` is computed from the two prices, because the site's own percent label is sometimes missing.
- **Ratings are 0–5**; `null` means not rated yet. Review and shop-review dates are Jalali, as the site shows them.
- **Installments:** the same seller item costs a few percent more in the installment and buy-now-pay-later price lists; `tl_product` shows all three and `tl_price_basket` totals any of them.
- **Shipping cost is not included** anywhere: Technolife only prices shipping for a logged-in address. `tl_store_info(topic="shipping")` has the rules.
- **Price sorting:** the site's price order is approximate (timed deals lag), so price sorts are re-sorted on the real price.
- **Persian queries match best** (`آیفون 16`, `لپ تاپ لنوو`). Category search treats Arabic ي/ك and half-space vs space as equal.

## FAQ

<details>
<summary><b>A phone search returns phone cases first</b></summary>

Sort by price and accessories win. `tl_search` and `tl_find_cheapest` return the matching `categories` with their codes;
the agent passes the phone one back as `category_code` (e.g. `1` for mobile phones).
</details>

<details>
<summary><b>Can it place an order for me?</b></summary>

No, and that's deliberate. It has no login and never saves a basket or touches order or payment endpoints.
`tl_price_basket` only asks the server for prices. The agent finds the best offer; you buy on the site.
</details>

<details>
<summary><b>I get "did not answer in time" or "Could not reach"</b></summary>

Technolife sometimes resets connections; the server retries a failed connection once (timeouts are not retried). If it keeps failing, check your connection or set
`TECHNOLIFE_MCP_PROXY`. Normal system proxy variables are ignored on purpose, because direct calls are the fastest.
</details>

<details>
<summary><b>Claude Desktop says <code>uvx</code> is not found</b></summary>

Use the full path to `uvx` (`where uvx` on Windows, `which uvx` on macOS/Linux) as `command`.
</details>

<details>
<summary><b>How do I debug what the agent sees?</b></summary>

```bash
npx @modelcontextprotocol/inspector uvx technolife-mcp
```
</details>

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TECHNOLIFE_MCP_PROXY` | unset | HTTP proxy for every request, e.g. `http://user:pass@host:port` |

## فارسی

<div dir="rtl">

**technolife-mcp** به دستیار هوش مصنوعی شما (Claude، Cursor، Copilot و ...) اجازه می&zwnj;دهد در تکنولایف جستجو کند،
قیمت نقدی و اقساطی همه فروشندگان یک کالا را مقایسه کند، مشخصات فنی و نظرات را بخواند و تخفیف&zwnj;های فعال را پیدا کند.

- فقط خواندنی است: وارد حساب نمی&zwnj;شود، سبد خرید ذخیره نمی&zwnj;کند و سفارش ثبت نمی&zwnj;کند.
- قیمت هر رنگ، فروشنده و گارانتی را همراه با قیمت اقساطی و هزینه بیمه نشان می&zwnj;دهد.
- همه قیمت&zwnj;ها به تومان است.
- روی سیستم خود شما اجرا می&zwnj;شود و به هیچ سرور واسطی داده نمی&zwnj;فرستد.

**نصب در Claude Code:**

</div>

```bash
claude mcp add technolife -- uvx technolife-mcp
```

<div dir="rtl">

بعد بپرسید: «ارزان&zwnj;ترین لپ تاپ لنوو با ۱۶ گیگ رم در تکنولایف و قیمت اقساطی آن چقدر است؟»

</div>

## Development

```bash
git clone https://github.com/sepehr071/technolife-mcp && cd technolife-mcp
uv sync
uv run pytest            # offline, against recorded responses
uv run pytest -m live    # real API
uv run ruff check .
```

Tools live in `src/technolife_mcp/search.py`, `catalog.py`, `product.py`, `offers.py` and `info.py`; each is a typed
async function with a docstring that tells the agent when to use it. Issues and PRs are welcome, especially new tools
and fixes for API changes.

Releases: bump the version in `pyproject.toml` and `server.json`, then push a `v*` tag. GitHub Actions tests,
publishes to PyPI and the [MCP Registry](https://registry.modelcontextprotocol.io), and creates the GitHub Release.

## Disclaimer

Unofficial and not affiliated with or endorsed by Technolife. It uses the public endpoints of the technolife.com
website, which can change without notice. Please keep request rates reasonable.

## License

[MIT](https://github.com/sepehr071/technolife-mcp/blob/main/LICENSE)
