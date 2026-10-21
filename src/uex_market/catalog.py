# -*- coding: utf-8 -*-
"""Catalog of UEX items: name to id_item resolution.

Marketplace listings carry an id_item but no item name, so searching by
name needs the catalog. Building it costs one call per item category (about
70 calls, under a minute), so a snapshot ships with the package and a fresh
copy is rebuilt in the background once a day.
"""
from __future__ import annotations

import difflib
import gzip
import json
import logging
import os
import re
import tempfile
import threading
import time
import unicodedata
from importlib import resources

from . import client

log = logging.getLogger(__name__)

TTL = 86400
_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_NON_WORD = re.compile(r"[^0-9a-z]+")


def fold(text):
    """Lower case, no accents, punctuation turned into single spaces."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return _NON_WORD.sub(" ", text).strip()


def base_name(name):
    """'Stileron (Raw)' -> 'Stileron'."""
    return _PAREN.sub("", name or "").strip()


def _snapshot():
    try:
        data = resources.files("uex_market").joinpath("data/catalog.json.gz")
        with data.open("rb") as fh:
            return json.loads(gzip.decompress(fh.read()).decode("utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None


def build(api=client, pause=3.0):
    # About 70 calls: at 3 s apart the rebuild uses about a third of the
    # default call budget, so searches keep running while it happens.
    """Fresh catalog from the API: item categories, then their items."""
    cats = [c for c in api.categories() if c.get("type") == "item"]
    items = []
    for c in cats:
        for it in api.items(c["id"]):
            items.append(dict(id=int(it["id"]), name=(it.get("name") or "").strip(),
                              id_category=int(c["id"]),
                              is_commodity=1 if it.get("is_commodity") else 0))
        time.sleep(pause)
    categories = [dict(id=int(c["id"]), section=c.get("section") or "",
                       name=c.get("name") or "") for c in cats]
    return dict(built_at=int(time.time()), categories=categories, items=items)


def save(data, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    with os.fdopen(fd, "wb") as fh:
        fh.write(gzip.compress(json.dumps(data, separators=(",", ":")).encode("utf-8")))
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


class Catalog:
    def __init__(self, cache_dir=None, api=client, ttl=TTL, auto_refresh=True):
        self.api = api
        self.ttl = ttl
        self.auto_refresh = auto_refresh
        self.path = os.path.join(cache_dir, "catalog.json.gz") if cache_dir else None
        self._lock = threading.Lock()
        self._refreshing = False
        self.last_error = None
        data = None
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, "rb") as fh:
                    data = json.loads(gzip.decompress(fh.read()).decode("utf-8"))
            except (OSError, ValueError):
                data = None
        self._load(data or _snapshot() or dict(built_at=0, categories=[], items=[]))

    def _load(self, data):
        cats = dict((c["id"], c) for c in data.get("categories", []))
        items = []
        for it in data.get("items", []):
            c = cats.get(it.get("id_category")) or dict()
            items.append(dict(id=it["id"], name=it["name"],
                              id_category=it.get("id_category"),
                              category=c.get("name") or "", section=c.get("section") or "",
                              is_commodity=it.get("is_commodity", 0),
                              _f=fold(it["name"]), _b=fold(base_name(it["name"]))))
        self.built_at = data.get("built_at") or 0
        self.categories = cats
        self.items = items
        self.by_id = dict((it["id"], it) for it in items)

    # Freshness -----------------------------------------------------------

    def stale(self):
        return time.time() - self.built_at > self.ttl

    def refresh(self, pause=3.0, min_items=1000):
        data = build(self.api, pause=pause)
        if len(data["items"]) < min_items:
            raise client.UexError("catalog too small (%d items)" % len(data["items"]))
        if self.path:
            save(data, self.path)
        with self._lock:
            self._load(data)

    def refresh_in_background(self):
        if not self.auto_refresh or not self.stale():
            return False
        with self._lock:
            if self._refreshing:
                return False
            self._refreshing = True

        def run():
            try:
                self.refresh()
                self.last_error = None
                log.info("catalog refreshed: %d items", len(self.items))
            except Exception as exc:  # noqa: BLE001  never kill the server
                self.last_error = str(exc)
                log.warning("catalog refresh failed: %s", exc)
            finally:
                self._refreshing = False

        threading.Thread(target=run, name="catalog-refresh", daemon=True).start()
        return True

    # Lookup --------------------------------------------------------------

    def category_ids(self, query):
        """Categories whose name or section matches, e.g. 'helmets', 'armor'."""
        q = fold(query)
        if not q:
            return set()
        return set(cid for cid, c in self.categories.items()
                   if q in fold(c.get("name")) or q in fold(c.get("section")))

    def find(self, query, limit=10, category_ids=None):
        q = fold(query)
        if not q:
            return []
        tokens = q.split()
        scored = []
        for it in self.items:
            if category_ids and it["id_category"] not in category_ids:
                continue
            f, b = it["_f"], it["_b"]
            if f == q:
                score = 100
            elif b == q:
                score = 95
            elif f.startswith(q + " ") or b.startswith(q):
                score = 80
            elif all(t in f.split() for t in tokens):
                score = 70
            elif q in f:
                score = 60
            else:
                ratio = difflib.SequenceMatcher(None, q, b).ratio()
                if ratio < 0.8:
                    continue
                score = int(ratio * 60)
            scored.append((score, it))
        scored.sort(key=lambda s: (-s[0], len(s[1]["name"]), s[1]["name"]))
        return [dict(score=s, **public(it)) for s, it in scored[:limit]]

    def resolve(self, query, category_ids=None):
        """(status, matches): 'ok' with the item(s) meant, 'ambiguous' with
        candidates, or 'not_found'. An exact name pulls in its variants
        sharing the same base name: 'Stileron' means Stileron and
        Stileron (Raw)."""
        cands = self.find(query, limit=25, category_ids=category_ids)
        if not cands:
            return "not_found", []
        group = [c for c in cands if c["score"] >= 95]
        if group:
            return "ok", group[:6]
        # A clear winner, possibly with its variants (Raw, Ore...): every
        # candidate sharing its base name, and no other item close behind.
        top = cands[0]
        tb = fold(base_name(top["name"]))
        same = [c for c in cands if fold(base_name(c["name"])) == tb]
        others = [c for c in cands if fold(base_name(c["name"])) != tb]
        if top["score"] >= 45 and (not others or others[0]["score"] <= top["score"] - 15):
            return "ok", same[:6]
        return "ambiguous", cands[:10]


def public(it):
    return dict(id_item=it["id"], name=it["name"], category=it["category"],
                section=it["section"], is_commodity=bool(it["is_commodity"]))
