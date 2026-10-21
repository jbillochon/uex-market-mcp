# -*- coding: utf-8 -*-
"""Protocol-level tests: the MCP server driven by the official client."""
import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mcp import Client  # noqa: E402

from test_market import market  # noqa: E402
from uex_market.server import build_server  # noqa: E402


def payload(result):
    if getattr(result, "structured_content", None):
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) else sc
    return json.loads(result.content[0].text)


class ServerTest(unittest.TestCase):
    def run_client(self, fn):
        m, _ = market()
        server, _ = build_server(market=m)

        async def go():
            async with Client(server) as c:
                return await fn(c)
        return asyncio.run(go())

    def test_tools_listed_read_only(self):
        async def fn(c):
            return await c.list_tools()
        tools = self.run_client(fn).tools
        names = sorted(t.name for t in tools)
        self.assertEqual(names, ["find_items", "marketplace_status", "search_listings"])
        for t in tools:
            self.assertTrue(t.annotations.read_only_hint)
        search = [t for t in tools if t.name == "search_listings"][0]
        props = search.input_schema["properties"]
        self.assertIn("quality_min", props)
        self.assertIn("id_items", props)

    def test_search_call(self):
        async def fn(c):
            return await c.call_tool("search_listings", dict(item="Stileron", quality_min=800,
                                                            max_age_days=14))
        res = self.run_client(fn)
        self.assertFalse(res.is_error)
        data = payload(res)
        self.assertEqual(data["results"][0]["title"], "Stileron 974Q")

    def test_validation_error(self):
        async def fn(c):
            return await c.call_tool("search_listings", dict(item="Stileron", quality_min=5000))
        self.assertTrue(self.run_client(fn).is_error)

    def test_find_items(self):
        async def fn(c):
            return await c.call_tool("find_items", dict(query="pembroke"))
        data = payload(self.run_client(fn))
        self.assertEqual(len(data["items"]), 2)


if __name__ == "__main__":
    unittest.main()
