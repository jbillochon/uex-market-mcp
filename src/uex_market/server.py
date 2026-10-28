# -*- coding: utf-8 -*-
"""MCP server: UEX marketplace search for Claude and any MCP client.

    uex-market-mcp                         # stdio, for Claude Desktop / Claude Code
    uex-market-mcp --http --port 8792      # Streamable HTTP, behind a reverse proxy

Read-only tools over public data; no account, no secret needed.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Annotated, Literal

from pydantic import Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from . import __version__, client
from .market import Market

log = logging.getLogger("uex_market")

INSTRUCTIONS = """\
Search the UEX player marketplace of Star Citizen (uexcorp.space/marketplace):
player-to-player listings of commodities, ores, armor, weapons, components.

- search_listings is the main tool. Name the item with `item` (resolved
  against the UEX catalog; 'Stileron' covers Stileron and Stileron (Raw)).
  If the answer is 'ambiguous', pick from the candidates and call again with
  `id_items`. Without an item, it searches recent listings (last few days)
  by `text`, `category` or other filters.
- Quality (0-1000) is often missing or only written in the title. The
  result tells where each quality comes from: '~886' was read from the
  title, '500?' is the unconfirmed form default, '517-747' is a listing
  with several qualities, '?' is unknown. Say so when it matters.
- Results keep one listing per seller by default, and only active ones
  (not sold out, not expired).
- sort='seller_activity' ranks by how recently each seller posted a listing
  on UEX (sellers marked away from the game last). UEX has no last-login
  date: say "last posted a listing N days ago", not "last online".
- Prices are as entered by the seller, for the listing's `unit` (scu, box,
  unit...); some sellers enter the whole lot price. Quote price and unit
  together, never convert.
- Always give the listing URL. Trades happen between players, outside UEX
  guarantees: remind the user to check the seller's reputation.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                            idempotentHint=True, openWorldHint=True)


def build_server(market=None, cache_dir=None):
    market = market or Market(cache_dir=cache_dir)
    mcp = MCPServer(name="uex-market", title="UEX Marketplace (Star Citizen)",
                    version=__version__, instructions=INSTRUCTIONS,
                    website_url="https://github.com/jbillochon/uex-market-mcp")

    def guarded(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except client.UexError as exc:
            raise ToolError("UEX API unavailable right now (%s). Retry in a minute." % exc)

    @mcp.tool(title="Search marketplace listings", annotations=READ_ONLY)
    def search_listings(
        item: Annotated[str | None, Field(description=(
            "Item name, e.g. 'Stileron', 'Quantainium', 'Pembroke helmet'. "
            "Leave empty to search recent listings by text/category."))] = None,
        id_items: Annotated[list[int] | None, Field(description=(
            "Exact UEX item ids (from find_items or an 'ambiguous' answer). "
            "Overrides `item`. Up to 6."))] = None,
        operation: Annotated[Literal["sell", "buy"], Field(description=(
            "'sell': players selling (you want to buy). 'buy': players looking "
            "to buy (you want to sell)."))] = "sell",
        quality_min: Annotated[int | None, Field(ge=0, le=1000, description=(
            "Minimum quality 0-1000. Listings of unknown quality are excluded "
            "when set."))] = None,
        quality_max: Annotated[int | None, Field(ge=0, le=1000)] = None,
        max_age_days: Annotated[int | None, Field(ge=0, le=365, description=(
            "Only listings posted within this many days. 0 or empty: any age. "
            "'Recent' usually means 7 to 14."))] = 30,
        price_max: Annotated[float | None, Field(ge=0, description=(
            "Maximum price, in the listing's own unit (see `unit`)."))] = None,
        system: Annotated[str | None, Field(description="Star system, e.g. 'Stanton', 'Pyro', 'Nyx'.")] = None,
        location: Annotated[str | None, Field(description="Substring of the location, e.g. 'Area18'.")] = None,
        seller: Annotated[str | None, Field(description="Substring of the seller's username.")] = None,
        text: Annotated[str | None, Field(description=(
            "Words that must all appear in the listing title."))] = None,
        category: Annotated[str | None, Field(description=(
            "UEX category or section, e.g. 'Commodities', 'Helmets', 'Armor', "
            "'Personal Weapons', 'Quantum Drives'."))] = None,
        sort: Annotated[Literal["quality", "recent", "price", "seller_activity"], Field(description=(
            "quality: best first; recent: newest first; price: cheapest first; "
            "seller_activity: sellers who posted on UEX most recently first, sellers "
            "marked away from the game last (adds a seller_activity block per result)."))] = "quality",
        one_per_seller: Annotated[bool, Field(description=(
            "Keep only each seller's best listing (default), otherwise one "
            "prolific seller fills the whole list."))] = True,
        include_unknown_quality: bool = True,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict:
        """Find player listings on the UEX marketplace with combined filters
        (item, quality range, age, price, system, location, seller, title
        words, category), ranked by quality, recency or price. Each result
        has a direct link to the listing."""
        return guarded(market.search, item=item, id_items=id_items, text=text,
                       category=category, operation=operation,
                       quality_min=quality_min, quality_max=quality_max,
                       max_age_days=max_age_days, price_max=price_max,
                       system=system, location=location, seller=seller,
                       sort=sort, one_per_seller=one_per_seller,
                       include_unknown_quality=include_unknown_quality, limit=limit)

    @mcp.tool(title="Find UEX items", annotations=READ_ONLY)
    def find_items(
        query: Annotated[str, Field(min_length=2, description="Part of an item name.")],
        category: Annotated[str | None, Field(description="Optional UEX category or section.")] = None,
        limit: Annotated[int, Field(ge=1, le=30)] = 10,
    ) -> dict:
        """Look up items in the UEX catalog by name (typo tolerant) to get
        their exact names and ids before searching listings."""
        return guarded(market.find_items, query, category=category, limit=limit)

    @mcp.tool(title="Marketplace data status", annotations=READ_ONLY)
    def marketplace_status() -> dict:
        """Freshness of the catalog and caches, and the UEX call budget."""
        return dict(server="uex-market-mcp", version=__version__, **market.status())

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request):  # noqa: ARG001
        from starlette.responses import JSONResponse
        return JSONResponse(dict(status="ok", version=__version__,
                                 catalog_items=len(market.catalog.items)))

    return mcp, market


def default_cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "uex-market")


def main(argv=None):
    p = argparse.ArgumentParser(prog="uex-market-mcp", description=__doc__.split("\n")[0])
    p.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    p.add_argument("--host", default=os.environ.get("UEX_MCP_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("UEX_MCP_PORT", "8792")))
    p.add_argument("--path", default=os.environ.get("UEX_MCP_PATH", "/mcp"))
    p.add_argument("--allowed-host", action="append", default=None,
                   help="public Host header accepted behind a proxy (repeatable); "
                        "env UEX_MCP_ALLOWED_HOSTS, comma separated")
    p.add_argument("--cache-dir", default=os.environ.get("UEX_MARKET_CACHE") or default_cache_dir())
    p.add_argument("--oauth-shim", action="store_true",
                   default=os.environ.get("UEX_MCP_OAUTH_SHIM", "") in ("1", "true", "yes"),
                   help="answer OAuth discovery/registration with an auto-approving "
                        "facade (for claude.ai custom connectors); needs --public-url")
    p.add_argument("--public-url", default=os.environ.get("UEX_MCP_PUBLIC_URL"),
                   help="public base URL, e.g. https://uex.example.org")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)
    if args.oauth_shim and not args.public_url:
        p.error("--oauth-shim needs --public-url (or UEX_MCP_PUBLIC_URL)")

    # stdout belongs to the protocol in stdio mode: log to stderr only.
    logging.basicConfig(stream=sys.stderr, level=os.environ.get("UEX_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mcp, market = build_server(cache_dir=args.cache_dir)
    market.catalog.refresh_in_background()

    if not args.http:
        mcp.run("stdio")
        return
    if args.oauth_shim:
        from . import oauth_shim
        redirect_hosts = [h for h in os.environ.get("UEX_MCP_OAUTH_REDIRECT_HOSTS", "").split(",")
                          if h.strip()] or oauth_shim.DEFAULT_REDIRECT_HOSTS
        oauth_shim.install(mcp, args.public_url, args.path, redirect_hosts)
        log.info("OAuth shim enabled for %s", args.public_url)
    hosts = args.allowed_host or [h.strip() for h in
                                  os.environ.get("UEX_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts + ["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=["https://%s" % h for h in hosts] + ["https://claude.ai"],
    )
    mcp.run("streamable-http", host=args.host, port=args.port,
            streamable_http_path=args.path, json_response=True,
            stateless_http=True, transport_security=security)


if __name__ == "__main__":
    main()
