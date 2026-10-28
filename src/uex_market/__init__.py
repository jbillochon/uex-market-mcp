# -*- coding: utf-8 -*-
"""uex_market: multi-criteria search of the UEX marketplace (Star Citizen).

The core (quality, listings, client, catalog, market) uses the standard
library only. The MCP server (uex_market.server) adds the `mcp` SDK.
"""
__version__ = "0.4.0"

from .quality import effective_quality, qualities_in_text  # noqa: E402
from .listings import (normalize, search, display_quality, is_active,  # noqa: E402
                       age_days, listing_url)

__all__ = ["effective_quality", "qualities_in_text", "normalize", "search",
           "display_quality", "is_active", "age_days", "listing_url"]
