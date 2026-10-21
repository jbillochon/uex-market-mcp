# -*- coding: utf-8 -*-
"""Marketplace search over live UEX data, with short-lived caches.

Two sources, merged:
- per item: every listing of an item (id_item + operation, up to 1 000
  rows), fetched live and cached a few minutes. Authoritative.
- recent window: the latest 500 sell and 500 buy listings of the whole
  marketplace (about three days), polled at most every few minutes and
  accumulated in memory. It is the only way to reach listings published
  without an id_item (roughly one in seven), found here by title.
"""
from __future__ import annotations

import datetime
import logging
import re
import threading
import time

from . import client
from .catalog import Catalog, base_name, fold
from .listings import (DAY, age_days, display_quality, is_active, normalize,
                       search)

log = logging.getLogger(__name__)

ITEM_TTL = 600
LATEST_TTL = 300
SYSTEMS_TTL = 86400
WINDOW_DAYS = 21
MAX_ITEMS_PER_SEARCH = 6
MAX_LIMIT = 50

Q_SOURCES = dict(
    declared="quality field set by the seller",
    title="read from the listing title",
    description="read from the listing description",
    default="500, the form default, not confirmed by the seller",
)


def _iso(ts):
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%MZ")


def _compact(d):
    """Drop empty fields: fewer tokens for the model, same information."""
    return dict((k, _compact(v) if isinstance(v, dict) else v)
                for k, v in d.items() if v is not None)


def _words_regex(name):
    words = fold(name).split()
    if not words:
        return None
    return re.compile(r"\b" + r"\W+".join(re.escape(w) for w in words) + r"\b")


class Market:
    def __init__(self, cache_dir=None, api=client, catalog=None,
                 item_ttl=ITEM_TTL, latest_ttl=LATEST_TTL):
        self.api = api
        self.catalog = catalog or Catalog(cache_dir, api=api)
        self.item_ttl = item_ttl
        self.latest_ttl = latest_ttl
        self._lock = threading.Lock()
        self._items = dict()      # (id_item, operation) -> (fetched_at, rows)
        self._window = dict()     # listing id -> row
        self._latest_at = 0
        self._systems = (0, dict())
        self.started_at = time.time()

    # Sources -------------------------------------------------------------

    def systems(self):
        at, systems = self._systems
        if time.time() - at > SYSTEMS_TTL or not systems:
            try:
                systems = self.api.star_systems()
                self._systems = (time.time(), systems)
            except client.UexError as exc:
                log.warning("star systems unavailable: %s", exc)
        return systems

    def _enrich(self, row):
        it = self.catalog.by_id.get(row.get("id_item"))
        cat = self.catalog.categories.get(row.get("id_category")) or dict()
        row["item"] = it["name"] if it else None
        row["category"] = cat.get("name") or (it["category"] if it else None)
        return row

    def item_rows(self, id_item, operation):
        key = (int(id_item), operation)
        hit = self._items.get(key)
        if hit and time.time() - hit[0] < self.item_ttl:
            return hit[1], hit[0]
        systems = self.systems()
        rows = [self._enrich(normalize(r, systems))
                for r in self.api.listings(id_item, operation)]
        now = time.time()
        with self._lock:
            self._items[key] = (now, rows)
            if len(self._items) > 2000:
                for k, _ in sorted(self._items.items(), key=lambda kv: kv[1][0])[:500]:
                    self._items.pop(k, None)
        return rows, now

    def window_rows(self):
        if time.time() - self._latest_at >= self.latest_ttl:
            systems = self.systems()
            fresh = []
            for op in ("sell", "buy"):
                fresh += self.api.listings(None, op)
            now = time.time()
            with self._lock:
                for raw in fresh:
                    row = self._enrich(normalize(raw, systems))
                    row["_seen"] = now
                    self._window[row["id"]] = row
                limite = now - WINDOW_DAYS * DAY
                for lid in [k for k, r in self._window.items()
                            if not is_active(r, now) or (r.get("date_added") or 0) < limite]:
                    self._window.pop(lid, None)
                self._latest_at = now
        return list(self._window.values()), self._latest_at

    # Search --------------------------------------------------------------

    def search(self, item=None, id_items=None, text=None, category=None,
               operation="sell", quality_min=None, quality_max=None,
               max_age_days=30, price_max=None, system=None, location=None,
               seller=None, sort="quality", one_per_seller=True,
               include_unknown_quality=True, limit=10):
        self.catalog.refresh_in_background()
        limit = max(1, min(int(limit or 10), MAX_LIMIT))
        operation = operation if operation in ("sell", "buy") else "sell"
        cat_ids = self.catalog.category_ids(category) if category else None
        if category and not cat_ids:
            return dict(status="unknown_category", category=category,
                        categories=sorted(set(c["name"] for c in self.catalog.categories.values())),
                        message="No UEX item category matches %r." % category)

        matched = []
        if id_items:
            for i in list(id_items)[:MAX_ITEMS_PER_SEARCH]:
                it = self.catalog.by_id.get(int(i))
                matched.append(dict(id_item=int(i), name=it["name"] if it else None))
        elif item:
            status, found = self.catalog.resolve(item, category_ids=cat_ids)
            if status != "ok":
                return dict(status=status, query=item, candidates=found,
                            message=("Several items match %r: call again with id_items "
                                     "set to the ones meant." % item) if found else
                            ("No UEX item matches %r. Try find_items, or search the "
                             "listing titles with text instead." % item))
            matched = [dict(id_item=f["id_item"], name=f["name"]) for f in found]

        sources = dict()
        rows = []
        window, window_at = self.window_rows()
        sources["recent_window_at"] = _iso(window_at)
        if matched:
            seen = set()
            fetched = []
            for m in matched:
                part, at = self.item_rows(m["id_item"], operation)
                fetched.append(at)
                for r in part:
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        rows.append(r)
            # Listings published without an id_item, found by title.
            patterns = [p for p in (_words_regex(base_name(m["name"] or "")) for m in matched) if p]
            for r in window:
                if r["id"] in seen or r.get("id_item"):
                    continue
                if any(p.search(fold(r.get("title"))) for p in patterns):
                    seen.add(r["id"])
                    r = dict(r, item=r.get("item") or "(not set, matched by title)")
                    rows.append(r)
            sources["item_listings_at"] = _iso(min(fetched)) if fetched else None
        else:
            rows = window
            sources["coverage"] = ("recent window only: listings of the last few days; "
                                   "name an item for its complete list")
        if cat_ids:
            rows = [r for r in rows if r.get("id_category") in cat_ids]
        if text:
            needles = fold(text).split()
            rows = [r for r in rows if all(n in fold(r.get("title")) for n in needles)]

        results, stats = search(
            rows, operation=operation, quality_min=quality_min, quality_max=quality_max,
            max_age_days=max_age_days or None, price_max=price_max, system=system,
            location=location, seller=seller, include_unknown=include_unknown_quality,
            sort=sort if sort in ("quality", "recent", "price") else "quality",
            dedupe_seller=one_per_seller, limit=limit)

        out = dict(
            status="ok",
            items=matched or None,
            filters=_compact(dict(operation=operation, quality_min=quality_min,
                         quality_max=quality_max, max_age_days=max_age_days or None,
                         price_max=price_max, system=system, location=location,
                         seller=seller, text=text, category=category, sort=sort,
                         one_per_seller=one_per_seller)),
            stats=dict(listings_scanned=stats["total"], active=stats["active"],
                       matching=stats["matched"], returned=len(results),
                       hidden_duplicate_sellers=stats["dropped_dupes"]),
            results=[self._present(i + 1, r) for i, r in enumerate(results)],
            data=dict(source="UEX public API (uexcorp.space), live with short caches",
                      **sources),
        )
        if not results:
            out["hint"] = ("No listing matches every filter. Widen max_age_days, "
                           "lower quality_min, or drop location/system filters.")
        return out

    def _present(self, rank, r):
        q = dict(label=display_quality(r), value=r.get("q_eff"),
                 source=Q_SOURCES.get(r.get("q_source")) if r.get("q_source") != "none" else None)
        if r.get("q_multi"):
            q["range"] = [r.get("q_min"), r.get("q_max")]
        return _compact(dict(
            rank=rank,
            title=r.get("title"),
            item=r.get("item"),
            category=r.get("category"),
            operation=r.get("operation"),
            quality=q,
            price=r.get("price"),
            currency=r.get("currency"),
            unit=r.get("unit"),
            seller=r.get("seller"),
            location=r.get("location"),
            system=r.get("system"),
            posted=_iso(r.get("date_added")),
            posted_days_ago=age_days(r),
            expires=_iso(r.get("date_expiration")),
            url=r.get("url"),
        ))

    def find_items(self, query, category=None, limit=10):
        self.catalog.refresh_in_background()
        cat_ids = self.catalog.category_ids(category) if category else None
        found = self.catalog.find(query, limit=max(1, min(int(limit or 10), 30)),
                                  category_ids=cat_ids)
        for f in found:
            f.pop("score", None)
        return dict(status="ok" if found else "not_found", query=query, items=found)

    def status(self):
        return dict(
            catalog_items=len(self.catalog.items),
            catalog_built=_iso(self.catalog.built_at),
            catalog_stale=self.catalog.stale(),
            catalog_last_error=self.catalog.last_error,
            recent_window_listings=len(self._window),
            recent_window_at=_iso(self._latest_at),
            cached_items=len(self._items),
            uex_calls_last_minute=client.BUDGET.used(),
            uex_call_budget_per_minute=client.BUDGET.per_minute,
            running_since=_iso(self.started_at),
        )
