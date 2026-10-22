---
name: uex-marketplace
description: Search the UEX player marketplace of Star Citizen (uexcorp.space) with combined filters - item, quality, age, price, system, location, seller. Use when someone asks who sells or buys an item, ore or commodity, for the best quality or cheapest listings, or for recent marketplace listings.
---

# UEX marketplace search

This skill drives the `uex-market` MCP server (tools `search_listings`,
`find_items`, `marketplace_status`). If those tools are not available, tell
the user to add the connector first (see "Setup" below) instead of guessing
listings: the marketplace changes by the hour and cannot be answered from
memory or from web search.

## Turning a request into filters

Map every criterion the user gives; combine them in one call.

| User says | Parameter |
|---|---|
| an item, ore, commodity, armor piece... | `item` (name as said; the server resolves it) |
| "quality above 800", "800+", "Q800 minimum" | `quality_min=800` |
| "between 700 and 900" | `quality_min=700, quality_max=900` |
| "recent", "latest" | `max_age_days=14` (7 for "this week", 1 to 2 for "today") |
| "any age", "all listings" | `max_age_days=0` |
| "cheapest", "best price" | `sort="price"` |
| "newest first" | `sort="recent"` |
| "best", "highest quality" (default) | `sort="quality"` |
| "who wants to buy", "I want to sell my..." | `operation="buy"` |
| "in Pyro", "in Stanton" | `system` |
| "at Area18", "near Orison" | `location` (substring) |
| "under 20k per SCU" | `price_max=20000` (price is in the listing's own `unit`) |
| "top 10", "5 sellers" | `limit` |
| "all listings, even from the same seller" | `one_per_seller=false` |

- If the answer has `status: "ambiguous"`, pick the candidate that fits the
  request when it is obvious, otherwise ask the user, then call again with
  `id_items`. Do not search every candidate blindly.
- `status: "not_found"`: try `find_items` with a shorter or corrected name,
  or search titles with `text` and no item.
- Ores and commodities: `item="Stileron"` already covers Stileron and
  Stileron (Raw). Ask for the raw form explicitly only if the user does.
- Without an item, the search covers recent listings only (the last few
  days of the whole marketplace). Say so if the user expects more.
- Empty result: read the `hint`, relax one filter (age first, then quality)
  and tell the user which one you relaxed.

## Presenting results

- A compact table or list, ranked as returned: quality, item, price + unit,
  seller, location/system, age, and the listing link (always).
- Quality labels mean different things, keep them as given:
  `974` declared by the seller; `~886` read from the title, not declared;
  `517-747` one listing offering several qualities; `500?` the form default,
  often not the real quality; `?` unknown. Flag `~` and `?` values when the
  user's decision depends on quality.
- Prices: quote price and `unit` together as given (scu, box, unit...).
  Sellers enter them freely and some put the whole lot price: never convert
  or compare across units without saying so.
- Mention when one listing per seller was kept (`hidden_duplicate_sellers`)
  if the user asked for "all".
- End with a short reminder: trades are between players, outside any
  guarantee; check the seller (votes, history on UEX) before paying.
- Answer in the user's language; keep item names in English as in game.

## Setup

- Claude (web or desktop): Customize > Connectors > + Add > Add custom
  connector, URL `https://uex.cavalera.news/mcp` (public, read only, no
  account) or the URL of your own instance. In a chat, switch it on with
  + > Connectors. Skills and instructions: https://cavalera.news/claude
- Claude Code: `claude mcp add --transport http uex-market https://uex.cavalera.news/mcp`
- Fully local, no third-party server: `uvx --from git+https://github.com/jbillochon/uex-market-mcp uex-market-mcp`
  as a stdio MCP server (Claude Desktop config or `claude mcp add uex-market -- uvx --from git+https://github.com/jbillochon/uex-market-mcp uex-market-mcp`).
