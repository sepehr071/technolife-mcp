import json

import pytest
from conftest import fixture
from mcp import Client

from technolife_mcp.info import clip
from technolife_mcp.offers import _link
from technolife_mcp.server import mcp

pytestmark = pytest.mark.anyio


async def test_wire_format_is_one_compact_text_block(api):
    api["search_page_results"] = fixture("search_results.json")
    # a fresh Client: the conftest `client` fixture patches call_tool
    async with Client(mcp, raise_exceptions=True) as c:
        tools = (await c.list_tools()).tools
        result = await c.call_tool("tl_search", {"query": "آیفون 16"})
    assert all(t.output_schema is None for t in tools)
    assert result.structured_content is None and len(result.content) == 1
    text = result.content[0].text
    assert text == json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))


async def test_input_schemas_have_no_title_noise():
    for t in await mcp.list_tools():
        assert "title" not in t.input_schema
        assert all("title" not in p for p in t.input_schema.get("properties", {}).values()), t.name


def test_clip_marks_truncation():
    assert clip("short") == "short" and clip(None) is None
    out = clip("x" * 1000)
    assert out.startswith("x" * 400) and out.endswith("[truncated]") and len(out) < 420


def test_link_rejects_lookalike_hosts():
    assert _link("https://evil-technolife.com/landings/x") is None
    assert _link("https://www.technolife.com/landings/x") == {"kind": "landing", "code": "x"}
    assert _link("https://technolife.ir/promotion/p48") == {"kind": "promotion", "page_url": "promotion/p48"}


async def test_nav_tree_is_cached(client, api):
    api["getNavBar"] = fixture("navbar.json")
    for _ in range(2):
        await client.call_tool("tl_categories", {})
    assert len(api.calls) == 1
