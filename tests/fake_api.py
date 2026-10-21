# -*- coding: utf-8 -*-
"""Offline stand-in for uex_market.client, shaped like the real API."""
import time

NOW = time.time()
DAY = 86400


def listing(id, id_item, title, quality=None, seller="alice", age=1.0, op="sell",
            price=10000, unit="scu", sold_out=0, id_category=36, system=68,
            location="Area18", expires_in=20):
    return dict(id=id, id_item=id_item, id_category=id_category, operation=op,
                type="item", slug="slug-%d" % id, title=title, price=price, unit=unit,
                currency="UEC", location=location, id_star_system=system,
                in_stock=1, is_sold_out=sold_out, user_username=seller,
                user_name=seller.title(), votes=0, quality=quality,
                date_added=int(NOW - age * DAY),
                date_expiration=int(NOW + expires_in * DAY), description="")


CATEGORIES = [
    dict(id=36, type="item", section="Commodities", name="Commodities"),
    dict(id=3, type="item", section="Armor", name="Helmets"),
    dict(id=90, type="service", section="Services", name="Escort"),
]
ITEMS = {
    36: [dict(id=5843, name="Stileron", is_commodity=1),
         dict(id=5978, name="Stileron (Raw)", is_commodity=1),
         dict(id=4745, name="Quantainium", is_commodity=1),
         dict(id=5950, name="Quantainium (Raw)", is_commodity=1)],
    3: [dict(id=100, name="Pembroke Helmet Arctic", is_commodity=0),
        dict(id=101, name="Pembroke Helmet RSI Edition", is_commodity=0)],
}
BY_ITEM = {
    (5843, "sell"): [
        listing(1, 5843, "Stileron 974Q", 974, "alice", 2),
        listing(2, 5843, "Stileron q517, q681, q747", None, "bob", 3),
        listing(3, 5843, "Stileron cheap", 500, "carol", 1),
        listing(4, 5843, "Stileron 990", None, "dave", 40),
        listing(5, 5843, "Stileron 999", 999, "erin", 1, sold_out=1),
        listing(6, 5843, "Stileron 900", 900, "alice", 1),
    ],
    (5978, "sell"): [listing(7, 5978, "Raw Stileron 850q", None, "frank", 5)],
    (4745, "buy"): [listing(10, 4745, "WTB Quantainium 900+", None, "ivan", 1, op="buy")],
}
LATEST = {
    "sell": [listing(8, 0, "WTS Stileron 880 quality, 32 SCU", None, "gina", 1, id_category=36),
             listing(9, 0, "Selling armor bundle", None, "hank", 1, id_category=3),
             listing(1, 5843, "Stileron 974Q", 974, "alice", 2)],
    "buy": [listing(10, 4745, "WTB Quantainium 900+", None, "ivan", 1, op="buy")],
}


class FakeApi:
    UexError = RuntimeError

    def __init__(self):
        self.calls = []

    def categories(self):
        self.calls.append("categories")
        return CATEGORIES

    def items(self, id_category):
        self.calls.append(("items", id_category))
        return ITEMS.get(id_category, [])

    def star_systems(self):
        self.calls.append("systems")
        return {68: "Stanton", 64: "Pyro"}

    def listings(self, id_item=None, operation=None):
        self.calls.append(("listings", id_item, operation))
        if id_item:
            return BY_ITEM.get((id_item, operation), [])
        return LATEST.get(operation, [])
