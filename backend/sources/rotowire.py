"""Rotowire NBA lineups + injuries (HTML scrape).

Rotowire publishes daily lineups + injury statuses on a public page. They
don't expose a free JSON API, so we scrape the HTML with a tiny regex
parser. Output records have kind='lineup' and kind='injury' so the
categorizer can route them.

The HTML format on Rotowire changes occasionally; the regexes here are kept
intentionally loose so a minor markup change doesn't blank the panel.
"""

from __future__ import annotations

import html
import re

from .. import config
from ..http_util import fetch
from .base import SourceResult, STATUS_ERROR, STATUS_OK, STATUS_PARTIAL

ROTOWIRE_LINEUPS = "https://www.rotowire.com/basketball/nba-lineups.php"
ROTOWIRE_INJURIES = "https://www.rotowire.com/basketball/injury-report.php"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Loose patterns — we accept noise rather than risk parsing nothing on a
# minor markup change.
_TEAM_BLOCK = re.compile(
    r'data-team-id="[^"]*"[^>]*>\s*<a[^>]*>([^<]+)</a>', re.IGNORECASE)
_PLAYER_LINK = re.compile(
    r'<a[^>]*href="/basketball/player\.php[^"]*"[^>]*>([^<]+)</a>',
    re.IGNORECASE)
_POSITION_TAG = re.compile(
    r'class="lineup__pos"[^>]*>([^<]+)<', re.IGNORECASE)
_INJURY_ROW = re.compile(
    r'<tr[^>]*>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*'
    r'<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>',
    re.IGNORECASE)


def _strip(s: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def fetch_lineups() -> SourceResult:
    """Best-effort scrape of today's projected lineups."""
    res = fetch(ROTOWIRE_LINEUPS, headers=HEADERS)
    if not res.ok or not res.body:
        return SourceResult("rotowire_lineups", STATUS_ERROR, error=res.error)
    body = res.body
    # Just pull every player link + adjacent position; pair them positionally.
    players = _PLAYER_LINK.findall(body)
    positions = _POSITION_TAG.findall(body)
    teams = _TEAM_BLOCK.findall(body)

    records: list[dict] = []
    pos_iter = iter(positions)
    for name in players:
        try:
            pos = next(pos_iter)
        except StopIteration:
            pos = ""
        records.append({
            "id": f"rotowire_lineup:{_strip(name)}",
            "source": "rotowire_lineups",
            "kind": "lineup",
            "title": _strip(name),
            "text": f"{_strip(pos)} {_strip(name)}",
            "url": ROTOWIRE_LINEUPS,
            "published": None,
            "engagement": 0,
            "team_hint": None,
            "position": _strip(pos),
            "player": _strip(name),
        })
    status_flag = STATUS_OK if records else STATUS_PARTIAL
    return SourceResult("rotowire_lineups", status_flag, records=records,
                         meta={"teams_seen": [_strip(t) for t in teams[:60]]})


def fetch_injuries() -> SourceResult:
    """Scrape Rotowire's injury report table."""
    res = fetch(ROTOWIRE_INJURIES, headers=HEADERS)
    if not res.ok or not res.body:
        return SourceResult("rotowire_injuries", STATUS_ERROR, error=res.error)
    body = res.body
    rows = _INJURY_ROW.findall(body)
    records: list[dict] = []
    for player, position, status, ret in rows:
        player_s = _strip(re.sub(r"<[^>]+>", "", player))
        if not player_s:
            continue
        records.append({
            "id": f"rotowire_injury:{player_s}",
            "source": "rotowire_injuries",
            "kind": "injury",
            "title": f"{player_s}: {_strip(status)}",
            "text": f"{player_s} ({_strip(position)}) status: {_strip(status)}"
                    f" — return: {_strip(ret)}",
            "url": ROTOWIRE_INJURIES,
            "published": None,
            "engagement": 0,
            "team_hint": None,
            "player": player_s,
            "status_text": _strip(status),
            "expected_return": _strip(ret),
        })
    return SourceResult("rotowire_injuries",
                         STATUS_OK if records else STATUS_PARTIAL,
                         records=records)
