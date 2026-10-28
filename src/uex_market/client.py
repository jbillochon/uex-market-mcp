# -*- coding: utf-8 -*-
"""Minimal client for the public UEX 2.0 API, standard library only.

The marketplace endpoints need no authentication. A token stays possible
(UEX_TOKEN environment variable) for anyone who wants a quota of their own.

Every call goes through a process-wide budget (UEX_MAX_CALLS_PER_MIN), so
the traffic sent to UEX never depends on the traffic a server receives.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

API = os.environ.get("UEX_API", "https://api.uexcorp.space/2.0")
USER_AGENT = os.environ.get(
    "UEX_USER_AGENT",
    "uex-market-mcp/%s (+https://github.com/jbillochon/uex-market-mcp)" % __version__)
MAX_CALLS_PER_MIN = int(os.environ.get("UEX_MAX_CALLS_PER_MIN", "40"))
MAX_WAIT = 20.0


class UexError(RuntimeError):
    pass


class _Budget:
    """Sliding one-minute window shared by every thread of the process."""

    def __init__(self, per_minute):
        self.per_minute = max(1, per_minute)
        self.calls = collections.deque()
        self.lock = threading.Lock()

    def acquire(self, max_wait=MAX_WAIT):
        limite = time.monotonic() + max_wait
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= 60:
                    self.calls.popleft()
                if len(self.calls) < self.per_minute:
                    self.calls.append(now)
                    return
                attente = 60 - (now - self.calls[0])
            if time.monotonic() + attente > limite:
                raise UexError("UEX call budget exhausted, retry in a minute")
            time.sleep(min(attente, 1.0))

    def used(self):
        with self.lock:
            now = time.monotonic()
            return sum(1 for t in self.calls if now - t < 60)


BUDGET = _Budget(MAX_CALLS_PER_MIN)


def get(resource, params=None, timeout=30, retries=2, pause=2.0):
    url = "%s/%s" % (API.rstrip("/"), resource.strip("/"))
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = dict([("User-Agent", USER_AGENT), ("Accept", "application/json")])
    token = os.environ.get("UEX_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    last = None
    for attempt in range(retries + 1):
        BUDGET.acquire()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as rep:
                body = json.loads(rep.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last = exc
            time.sleep(pause * (attempt + 1))
            continue
        status = body.get("status")
        if status == "requests_limit_reached":
            last = UexError("UEX quota reached")
            time.sleep(pause * 5 * (attempt + 1))
            continue
        if status != "ok":
            raise UexError("UEX %s: %s" % (resource, status))
        return body.get("data") or []
    raise UexError("UEX %s unreachable: %s" % (resource, last))


def listings(id_item=None, operation=None):
    """Marketplace listings. With id_item (and operation) the API returns
    every listing of that item, up to 1 000 rows; without it, the latest
    500 listings of the whole marketplace."""
    params = dict()
    if id_item:
        params["id_item"] = int(id_item)
    if operation:
        params["operation"] = operation
    return get("marketplace_listings", params or None)


def listings_for_item(id_item, operation="sell"):
    return listings(id_item, operation)


def categories():
    return get("categories")


def items(id_category):
    return get("items", dict([("id_category", int(id_category))]))


def star_systems():
    return dict((s.get("id"), s.get("name")) for s in get("star_systems"))


def commodities():
    return get("commodities")


def user(username):
    """Public UEX profile: is_away_game, date_rsi_verified, time_availability,
    timezone, date_modified (last profile edit, not last login)."""
    return get("user", dict([("username", username)]))


def listings_by_user(username):
    """Every listing of one seller (all items)."""
    return get("marketplace_listings", dict([("username", username)]))
