"""Action Network public-betting + sharp-money scraper (best-effort).

Action Network publishes percentage-of-money & percentage-of-bets on each
game without a paywall. The page uses Next.js, so the data is embedded in
the bundled __NEXT_DATA__ JSON blob; we extract it once per fetch.
"""

from __future__ import annotations

import json
import re

from ..http_util import fetch
from .base import SourceResult, STATUS_ERROR, STATUS_OK, STATUS_PARTIAL

AN_NBA = "https://www.actionnetwork.com/nba/public-betting"

HEADERS = {
    "Accept": "text/html",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.DOTALL)


def fetch_public_betting() -> SourceResult:
    res = fetch(AN_NBA, headers=HEADERS)
    if not res.ok or not res.body:
        return SourceResult("action_network", STATUS_ERROR, error=res.error)
    m = _NEXT_DATA.search(res.body)
    if not m:
        return SourceResult("action_network", STATUS_PARTIAL,
                             error="no __NEXT_DATA__ blob on page")
    try:
        data = json.loads(m.group(1))
    except ValueError as e:
        return SourceResult("action_network", STATUS_PARTIAL,
                             error=f"NEXT_DATA parse failed: {e}")

    # Walk the tree to find the games list. Action Network's exact path
    # changes; we search for any list of dicts with public_betting keys.
    games = _find_public_betting(data)
    if not games:
        return SourceResult("action_network", STATUS_PARTIAL,
                             error="public_betting payload not located")
    return SourceResult("action_network", STATUS_OK, records=[],
                         meta={"games": games})


def _find_public_betting(node, depth: int = 0):
    """Recursive search for the games list."""
    if depth > 7:
        return None
    if isinstance(node, dict):
        if "publicBetting" in node or "public_betting" in node:
            return node.get("publicBetting") or node.get("public_betting")
        if {"teams", "odds"}.issubset(node.keys() if hasattr(node, "keys") else set()):
            return [node]
        for v in node.values():
            r = _find_public_betting(v, depth + 1)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_public_betting(v, depth + 1)
            if r:
                return r
    return None
