# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fake_api import FakeApi  # noqa: E402
from uex_market.catalog import Catalog, build, fold  # noqa: E402
from uex_market.market import Market  # noqa: E402


def market():
    api = FakeApi()
    cat = Catalog(None, api=api, auto_refresh=False)
    cat._load(build(api, pause=0))
    return Market(api=api, catalog=cat), api


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.m, self.api = market()

    def test_fold(self):
        self.assertEqual(fold("Qualité: Stileron (Raw)"), "qualite stileron raw")

    def test_build_skips_service_categories(self):
        self.assertNotIn(("items", 90), self.api.calls)

    def test_exact_name_pulls_variants(self):
        status, found = self.m.catalog.resolve("stileron")
        self.assertEqual(status, "ok")
        self.assertEqual(sorted(f["id_item"] for f in found), [5843, 5978])

    def test_exact_variant_only(self):
        status, found = self.m.catalog.resolve("Stileron (Raw)")
        self.assertEqual([f["id_item"] for f in found], [5978])

    def test_typo(self):
        status, found = self.m.catalog.resolve("quantanium")
        self.assertEqual(status, "ok")
        self.assertIn(4745, [f["id_item"] for f in found])

    def test_ambiguous(self):
        status, found = self.m.catalog.resolve("pembroke")
        self.assertEqual(status, "ambiguous")
        self.assertEqual(len(found), 2)

    def test_not_found(self):
        self.assertEqual(self.m.catalog.resolve("zzzzzz")[0], "not_found")

    def test_cache_roundtrip(self):
        d = tempfile.mkdtemp()
        api = FakeApi()
        c = Catalog(d, api=api, auto_refresh=False)
        c.refresh(pause=0, min_items=1)
        c2 = Catalog(d, api=FakeApi(), auto_refresh=False)
        self.assertEqual(len(c2.items), 6)
        self.assertFalse(c2.stale())


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.m, self.api = market()

    def test_julien_example(self):
        r = self.m.search(item="Stileron", quality_min=800, max_age_days=14)
        self.assertEqual(r["status"], "ok")
        titles = [x["title"] for x in r["results"]]
        # 974 alice first, alice's 900 hidden as duplicate seller, raw 850,
        # title-only 880 listing without id_item; sold out 999 and 40-day-old
        # 990 excluded; multi 517-747 below threshold.
        self.assertEqual(titles[0], "Stileron 974Q")
        self.assertIn("WTS Stileron 880 quality, 32 SCU", titles)
        self.assertIn("Raw Stileron 850q", titles)
        self.assertNotIn("Stileron 999", titles)
        self.assertNotIn("Stileron 990", titles)
        self.assertNotIn("Stileron 900", titles)
        self.assertEqual(r["stats"]["hidden_duplicate_sellers"], 1)
        self.assertTrue(r["results"][0]["url"].startswith("https://uexcorp.space/"))

    def test_multi_quality_range_passes_threshold(self):
        r = self.m.search(item="Stileron", quality_min=700, one_per_seller=False, limit=50)
        bob = [x for x in r["results"] if x["seller"] == "bob"][0]
        self.assertEqual(bob["quality"]["label"], "517-747")
        self.assertEqual(bob["quality"]["range"], [517, 747])

    def test_quality_sources_reported(self):
        r = self.m.search(item="Stileron", limit=50, max_age_days=0, one_per_seller=False)
        by = dict((x["title"], x["quality"]) for x in r["results"])
        self.assertEqual(by["Stileron cheap"]["label"], "500?")
        self.assertIn("default", by["Stileron cheap"]["source"])
        self.assertEqual(by["Raw Stileron 850q"]["label"], "~850")

    def test_ambiguous_returns_candidates(self):
        r = self.m.search(item="Pembroke")
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(len(r["candidates"]), 2)

    def test_id_items(self):
        r = self.m.search(id_items=[5978])
        titles = [x["title"] for x in r["results"]]
        self.assertIn("Raw Stileron 850q", titles)
        self.assertNotIn("Stileron 974Q", titles)

    def test_recent_window_text_and_category(self):
        r = self.m.search(text="armor", category="helmets")
        self.assertEqual([x["title"] for x in r["results"]], ["Selling armor bundle"])
        self.assertIn("coverage", r["data"])

    def test_unknown_category(self):
        r = self.m.search(category="spaceships")
        self.assertEqual(r["status"], "unknown_category")

    def test_buy_side(self):
        r = self.m.search(item="Quantainium", operation="buy")
        self.assertEqual([x["seller"] for x in r["results"]], ["ivan"])

    def test_caches(self):
        self.m.search(item="Stileron")
        n = len(self.api.calls)
        self.m.search(item="Stileron", quality_min=900)
        self.assertEqual(len(self.api.calls), n)

    def test_empty_hint(self):
        r = self.m.search(item="Stileron", quality_min=1000)
        self.assertEqual(r["results"], [])
        self.assertIn("hint", r)

    def test_system_filter(self):
        r = self.m.search(item="Stileron", system="pyro")
        self.assertEqual(r["results"], [])
        r = self.m.search(item="Stileron", system="Stanton")
        self.assertTrue(r["results"])

    def test_status(self):
        s = self.m.status()
        self.assertEqual(s["catalog_items"], 6)


if __name__ == "__main__":
    unittest.main()


class SellerActivityTest(unittest.TestCase):
    def test_rank_by_seller_activity(self):
        m, api = market()
        r = m.search(item="Stileron", sort="seller_activity", limit=5)
        sellers = [x["seller"] for x in r["results"]]
        # carol a publie il y a 2 h ; bob est absent du jeu : dernier
        self.assertEqual(sellers[0], "carol")
        self.assertEqual(sellers[-1], "bob")
        top = r["results"][0]["seller_activity"]
        self.assertEqual(top["last_listing_days_ago"], 0)
        self.assertTrue(top["rsi_verified"])
        self.assertTrue([x for x in r["results"] if x["seller"] == "bob"][0]["seller_activity"]["away_from_game"])
        self.assertIn("no last-login", r["seller_activity_note"])
        n = sum(1 for c in api.calls if c[0] == "user")
        m.search(item="Stileron", sort="seller_activity", limit=5)      # cache
        self.assertEqual(sum(1 for c in api.calls if c[0] == "user"), n)

    def test_other_sorts_unchanged(self):
        m, api = market()
        r = m.search(item="Stileron", sort="quality", limit=5)
        self.assertNotIn("seller_activity", r["results"][0])
        self.assertFalse([c for c in api.calls if c[0] == "user"])
