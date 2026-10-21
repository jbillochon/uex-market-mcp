# uex-market-mcp

Search the [UEX](https://uexcorp.space/marketplace/) player marketplace of
Star Citizen from Claude, or any MCP client, with combined filters:

> *List recent listings of Stileron sellers with quality above 800.*

One call combines item, quality range, age, price, star system, location,
seller, title words and category, ranked by quality, recency or price, one
listing per seller, each with a direct link.

Read-only, public data, no UEX account and no secret needed.

## Use it

**Hosted instance** (free, public, rate limited): `https://uex.cavalera.news/mcp`

- Claude web / desktop / mobile: *Settings > Connectors > Add custom connector*, paste the URL.
- Claude Code: `claude mcp add --transport http uex-market https://uex.cavalera.news/mcp`

**Local, no third-party server** (needs [uv](https://docs.astral.sh/uv/)):

```json
{
  "mcpServers": {
    "uex-market": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/jbillochon/uex-market-mcp", "uex-market-mcp"]
    }
  }
}
```

or `claude mcp add uex-market -- uvx --from git+https://github.com/jbillochon/uex-market-mcp uex-market-mcp`.
Calls then go from your machine straight to the UEX API.

**Skill**: `skill/uex-marketplace/SKILL.md` teaches Claude how to turn a
request into filters and how to read quality labels. Zip the
`uex-marketplace` folder and add it in Claude (*Settings > Capabilities >
Skills*), or copy it to `~/.claude/skills/` for Claude Code.

## Tools

| Tool | Purpose |
|---|---|
| `search_listings` | Filtered, ranked listings. Main tool. |
| `find_items` | Typo-tolerant lookup in the UEX catalog (about 7 800 items). |
| `marketplace_status` | Catalog and cache freshness, UEX call budget. |

## How quality is read

Sellers often leave the quality field empty or at its default, and write
the real value in the title (`Dolivine 886Q`, `Q965`, `550-676q`). Each
result says where its quality comes from:

| Label | Meaning |
|---|---|
| `974` | declared by the seller |
| `~886` | read from the title or description |
| `517-747` | one listing offering several qualities (filtered on the range) |
| `500?` | the form default, not confirmed |
| `?` | unknown, never passes a quality threshold |

The parser abstains rather than guess: prices, volumes and quantities
(`585 400 000`, `32 SCU`, `x50`) are not read as qualities.

## Data and limits

- Per item: every active listing (up to 1 000), live from the UEX API,
  cached 10 minutes.
- Listings published without an item id (about one in seven) are found by
  title among the latest 1 000 listings of the marketplace, polled at most
  every 5 minutes and kept for 21 days.
- A search without an item covers that recent window only.
- Sold-out and expired listings are dropped.
- Outgoing UEX traffic is capped per process (`UEX_MAX_CALLS_PER_MIN`,
  default 40), whatever the incoming load.

## Self-hosting over HTTP

```bash
pip install git+https://github.com/jbillochon/uex-market-mcp
UEX_MCP_ALLOWED_HOSTS=uex.example.org uex-market-mcp --http --port 8792
```

Stateless Streamable HTTP on `127.0.0.1:8792/mcp`, `/health` for probes.
Put it behind a TLS reverse proxy; `deploy/` has a systemd unit and an nginx
example with rate limiting.

| Variable | Default | |
|---|---|---|
| `UEX_MCP_ALLOWED_HOSTS` | | public host names accepted (DNS rebinding protection) |
| `UEX_MARKET_CACHE` | `~/.cache/uex-market` | catalog cache |
| `UEX_MAX_CALLS_PER_MIN` | `40` | outgoing UEX budget |
| `UEX_TOKEN` | | optional UEX token, for a quota of your own |
| `UEX_MCP_OAUTH_SHIM` | off | `1`: auto-approving OAuth facade (see below) |
| `UEX_MCP_PUBLIC_URL` | | public base URL, required by the OAuth facade |
| `UEX_MCP_OAUTH_REDIRECT_HOSTS` | `claude.ai,claude.com,localhost,127.0.0.1` | redirect hosts accepted by the facade |

**claude.ai and OAuth.** claude.ai custom connectors run OAuth discovery and
dynamic client registration on "Connect" even for servers without
authentication, and fail when there is no registration endpoint
([anthropics/claude-ai-mcp#457](https://github.com/anthropics/claude-ai-mcp/issues/457)).
`UEX_MCP_OAUTH_SHIM=1` answers that flow with an auto-approving facade: any
client registers, `/authorize` redirects straight back, `/token` issues a
token that grants nothing more, since `/mcp` stays open to everyone. Redirect
URIs are restricted to an allowlist so `/authorize` is not an open redirector.

## Development

```bash
python -m unittest discover -s tests
```

Not affiliated with UEX Corp or Cloud Imperium Games. Trades happen between
players: check the seller before paying.

MIT License.
