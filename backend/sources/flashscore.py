"""Flashscore live scores scraper (best-effort).

Flashscore's public site exposes a feed at d.flashscore.com used by its own
widget. The payload is a pipe/section-delimited custom string ("d:1¬AA÷..."
style) rather than JSON. We parse the headline fields we actually need
(score + status) and stop there — anything richer should come from Sofascore
or NBA.com.

Flashscore is geo/IP-sensitive and aggressively rotates its feed URLs; if it
fails we report it and move on, exactly like every other source here.
"""

from __future__ import annotations

import re

from ..http_util import fetch
from .. import config
from .base import SourceResult, STATUS_ERROR, STATUS_OK, STATUS_PARTIAL

FLASHSCORE_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.flashscore.com/",
    "Origin": "https://www.flashscore.com",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "x-fsign": "SW9D1eZo",  # static "signing" key Flashscore expects
}

FLASHSCORE_LIVE = "https://d.flashscore.com/x/feed/f_2_0_3_en_1"


# Field tags in the Flashscore feed; the ones we care about per match:
TAGS = {
    "AA": "id",             # match id (Flashscore internal)
    "AC": "stage",          # tournament/stage
    "AD": "start_unix",     # tipoff epoch
    "AE": "home_team",
    "AF": "away_team",
    "AG": "home_score",
    "AH": "away_score",
    "AS": "status_id",      # numeric status (1=sched, 2=live, 3=finished, ...)
    "AT": "status_text",
}


def _split_blocks(payload: str) -> list[dict]:
    """Split the feed into per-match dicts."""
    rows = payload.split("¬~AA÷")
    out: list[dict] = []
    for raw in rows[1:]:
        block = {}
        chunks = raw.split("¬")
        # Re-prefix the first chunk; we stripped the AA÷ above.
        chunks[0] = "AA÷" + chunks[0]
        for c in chunks:
            if "÷" not in c:
                continue
            key, _, val = c.partition("÷")
            if key in TAGS:
                block[TAGS[key]] = val
        if block:
            out.append(block)
    return out


def _match_filter(blocks: list[dict], home: dict, away: dict) -> dict | None:
    """Pick the block whose names match our target game."""
    for b in blocks:
        h = (b.get("home_team") or "").lower()
        a = (b.get("away_team") or "").lower()
        if (any(al in h for al in home["aliases"])
                and any(al in a for al in away["aliases"])):
            return b
    return None


def fetch_game(home: dict | None = None, away: dict | None = None) -> SourceResult:
    """Pull the matched NBA game from Flashscore's live feed."""
    home = home or config.GAME["home"]
    away = away or config.GAME["away"]
    res = fetch(FLASHSCORE_LIVE, headers=FLASHSCORE_HEADERS)
    if not res.ok or not res.body:
        return SourceResult("flashscore", STATUS_ERROR, error=res.error)

    blocks = _split_blocks(res.body)
    if not blocks:
        return SourceResult("flashscore", STATUS_PARTIAL,
                             error="no matches parsed from feed")
    target = _match_filter(blocks, home, away)
    if not target:
        return SourceResult("flashscore", STATUS_PARTIAL,
                             error="target game not in feed today",
                             meta={"sampled_pairs":
                                   [(b.get("home_team"), b.get("away_team"))
                                    for b in blocks[:8]]})

    state_map = {"1": "pre", "2": "in", "3": "post"}
    game = {
        "id": target.get("id"),
        "name": f"{target.get('away_team')} @ {target.get('home_team')}",
        "state": state_map.get(target.get("status_id"), "pre"),
        "status_detail": target.get("status_text"),
        "home": {"name": target.get("home_team"),
                  "score": _to_int(target.get("home_score"))},
        "away": {"name": target.get("away_team"),
                  "score": _to_int(target.get("away_score"))},
    }
    return SourceResult("flashscore", STATUS_OK, records=[],
                         meta={"game": game, "blocks_seen": len(blocks)})


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
