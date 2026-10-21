# -*- coding: utf-8 -*-
"""Tests du package uex_market. Les titres sont tous reels, releves sur la
marketplace UEX le 21/10/2026."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from uex_market.quality import qualities_in_text, effective_quality  # noqa: E402
from uex_market.listings import search, display_quality, normalize  # noqa: E402

NOW = 1792590000


class TitreQualites(unittest.TestCase):
    CAS = [
        ("Dolivine 886Q", [886]),
        ("Beryl-937Q", [937]),
        ("Feynmaline Q965", [965]),
        ("WTS Sadaryx 940Q / 865Q / 797Q / 688Q / 510Q / 258Q",
         [258, 510, 688, 797, 865, 940]),
        ("Ouratite 779q 150K, 860q 1M, 912q 3M, 960q 10M", [779, 860, 912, 960]),
        ("Borase 550-676q 50K, 743q 150K, 892q 500K", [550, 676, 743, 892]),
        ("Carinite [554-959Q][BULK AVAIL]", [554, 959]),
        ("WTS Hadanite | Q526-916 | 521 Gems | 9M Full Buyout", [526, 916]),
        ("Feynmaline q500-700", [500, 700]),
        ("Beryl Q860 0.293SUC 880K/1SCU", [860]),
        ("Copper Q855 0.447SCU 880K/1SCU", [855]),
        ("Dolivine 886Q X 22 40k each (880k total)", [886]),
        ("Corundum Q904 x3.95 scu", [904]),
        ("Savrilium 580 150K, 878 - 1.5M, 905 - 3M, 967 - 4M", [580, 878, 905, 967]),
        ("Lindinium 729 1mil", [729]),
        ("Lindinium 853", [853]),
        ("Stileron 947 1.13scu", [947]),
        ("Stileron - 7.72 SCU - 517q", [517]),
        ("Stileron Q947 1.427 scu 21.39 million uec", [947]),
        ("Stileron Quality 1000 (0.710 SCU)", [1000]),
        ("Stileron q517, q681, q747", [517, 681, 747]),
        ("WANT TO BUY Feynmaline 1000 Q / 969 Q / 890Q", [890, 969, 1000]),
        ("I am looking for 947 or 972 quality Stileron", [947, 972]),
        ("[WTB] Bulk Mid/High-Tier Ore Orders (900 Plus Quality)", [900]),
        ("WTS Stileron Q972 | 22M/SCU | Top Tier | KohlyG", [972]),
        ("Pressurized Ice 714q 50K, 873q 150K, 922q 700K, 966 3M",
         [714, 873, 922, 966]),
        ("Q561/Q371 Feynmaline [check description]", [371, 561]),
        ("965q Feynmaline wanna buy", [965]),
        ("Hadanite Q956, Q916, and Q857", [857, 916, 956]),
        ("Beryl (937q) .393scu 4mil", [937]),
        ("Veyronis-Torite-Q873-76-cSCU", [873]),
    ]
    SANS = [
        "Quantainium",
        "Carinite (NOT PURE)",
        "WTB Quantainium all qualities!",
        "Beradom for sale 200K/unit 2.7M for all",
        "WTS Hadanite 300k",
        "Carinite for IDRIS 50x",
        "Iron for RSI Discovery Event (Collection) Missions (per mission pack)",
        "Beryl 324P 150K uni",
        "WTS 2954 Red Festival Poster",
        "Quantainium Bulk",
        "Quartz",
        "Carinite for IDRIS 50x q50",
        "Lindinium 585 400 000$ per",
        "Titanium 1 500 000 per SCU",
    ]

    def test_qualites_lues(self):
        for titre, attendu in self.CAS:
            with self.subTest(titre=titre):
                self.assertEqual(qualities_in_text(titre), attendu)

    def test_rien_a_lire(self):
        for titre in self.SANS:
            with self.subTest(titre=titre):
                self.assertEqual(qualities_in_text(titre), [])

    def test_description_sans_nombres_nus(self):
        desc = "Weapon Class: Ballistic\r\nEffective Range: 200 m\r\nRate of Fire: 600 rpm"
        self.assertEqual(qualities_in_text(desc, bare=False), [])
        self.assertEqual(qualities_in_text("Quality: 974 Q", bare=False), [974])


class QualiteEffective(unittest.TestCase):
    def test_declaree_prime(self):
        q = effective_quality(947, "Stileron 947Q 0.91 SCU")
        self.assertEqual((q["q_eff"], q["source"], q["multi"]), (947, "declared", False))

    def test_absente_deduite_du_titre(self):
        q = effective_quality(None, "Dolivine 886Q")
        self.assertEqual((q["q_eff"], q["source"]), (886, "title"))
        q = effective_quality(0, "Stileron 517 SOLD OUT")
        self.assertEqual((q["q_eff"], q["source"]), (517, "title"))

    def test_plage_multi(self):
        q = effective_quality(517, "Stileron q517, q681, q747")
        self.assertEqual((q["q_eff"], q["q_min"], q["q_max"], q["multi"]),
                         (517, 517, 747, True))

    def test_desaccord_titre_declaree(self):
        # Faute de frappe d un cote ou de l autre : on garde la declaree pour
        # l affichage, mais la plage couvre les deux pour le filtrage.
        q = effective_quality(865, "Riccite WTS: 1 SCU of Q965 Riccite")
        self.assertEqual((q["q_eff"], q["q_min"], q["q_max"]), (865, 865, 965))

    def test_defaut_500(self):
        q = effective_quality(500, "Stileron")
        self.assertEqual((q["q_eff"], q["source"]), (500, "default"))
        q = effective_quality(500, "Feynmaline q500-700")
        self.assertEqual((q["source"], q["q_max"]), ("title", 700))

    def test_declaree_1_ignoree(self):
        q = effective_quality(1, "Beryl 324P 150K uni")
        self.assertEqual(q["source"], "none")
        self.assertIsNone(q["q_eff"])

    def test_rien(self):
        q = effective_quality(None, "Carinite", "Pickup at Area 18")
        self.assertEqual((q["q_eff"], q["source"]), (None, "none"))

    def test_description_marquee(self):
        q = effective_quality(None, "Stileron", "STILERON\r\n\r\nQuality: 974 Q\r\n\r\nPrice: 12M")
        self.assertEqual((q["q_eff"], q["source"]), (974, "description"))


def annonce(id, seller, q, jours, op="sell", sold=0, title="", price=1e6):
    raw = dict(id=id, id_item=5843, operation=op, title=title or "Stileron",
               quality=q, user_username=seller, is_sold_out=sold,
               date_added=NOW - jours * 86400, date_expiration=NOW + 86400,
               price=price, slug="s-%d" % id, unit="scu")
    return normalize(raw)


class Recherche(unittest.TestCase):
    def setUp(self):
        self.rows = [
            annonce(1, "alfie", 947, 3),
            annonce(2, "nogoose", 974, 10),
            annonce(3, "nogoose", 330, 1),
            annonce(4, "kohly", 972, 40),
            annonce(5, "cat", 517, 2, title="Stileron q517, q681, q747"),
            annonce(6, "old", 1000, 5, sold=1),
            annonce(7, "anon", None, 1),
            annonce(8, "buyer", 950, 1, op="buy"),
            annonce(9, "alfie", 900, 1),
        ]

    def test_qualite_et_recence(self):
        res, stats = search(self.rows, quality_min=800, max_age_days=14, now=NOW)
        self.assertEqual([r["id"] for r in res], [2, 1])
        self.assertEqual(stats["dropped_dupes"], 1)  # alfie 900 masque par 947

    def test_epuisee_exclue(self):
        res, _ = search(self.rows, quality_min=990, now=NOW)
        self.assertEqual(res, [])

    def test_plage_multi_qualites(self):
        res, _ = search(self.rows, quality_min=700, max_age_days=3, now=NOW)
        ids = [r["id"] for r in res]
        self.assertIn(5, ids)

    def test_inconnue_en_dernier(self):
        res, _ = search(self.rows, max_age_days=14, now=NOW, dedupe_seller=False)
        self.assertEqual(res[-1]["id"], 7)

    def test_tri_recence(self):
        res, _ = search(self.rows, sort="recent", now=NOW, dedupe_seller=False)
        self.assertEqual(res[0]["date_added"], max(r["date_added"] for r in res))

    def test_demandes(self):
        res, _ = search(self.rows, operation="buy", now=NOW)
        self.assertEqual([r["id"] for r in res], [8])

    def test_libelles(self):
        self.assertEqual(display_quality(annonce(10, "a", 947, 1)), "947")
        self.assertEqual(display_quality(annonce(11, "a", None, 1, title="Dolivine 886Q")), "~886")
        self.assertEqual(display_quality(annonce(12, "a", 517, 1, title="Stileron q517, q681, q747")), "517-747")
        self.assertEqual(display_quality(annonce(13, "a", 500, 1)), "500?")
        self.assertEqual(display_quality(annonce(14, "a", None, 1)), "?")


if __name__ == "__main__":
    unittest.main()
