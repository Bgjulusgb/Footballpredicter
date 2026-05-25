"""TheScore.com NBA scores (best-effort).

TheScore exposes a public JSON API at api.thescore.com used by their PWA. It
returns a list of basketball events; we pick our target and normalise it into
the same SourceResult shape the rest of the pipeline expects.

Used as a cross-check on ESPN / Sofascore for the live score + status.
"""

from __future__ import annotations

import datetime as dt

from .. import config
from ..http_util import fetch_json
from .base import SourceResult, STATUS_ERROR, STATUS_OK, STATUS_PARTIAL

THESCORE_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.thescore.com/",
}

THESCORE_DAILY = "https://api.thescore.com/nba/events/daily_events?date={date}"


def _matches(event: dict, home: dict, away: dict) -> bool:
    h = ((event.get("home_team") or {}).get("full_name") or "").lower()
    a = ((event.get("away_team") or {}).get("full_name") or "").lower()
    return (any(al in h for al in home["aliases"])
            and any(al in a for al in away["aliases"]))


def fetch_game(date: str | None = None,
               home: dict | None = None,
               away: dict | None = None) -> SourceResult:
    home = home or config.GAME["home"]
    away = away or config.GAME["away"]
    if not date:
        date = dt.datetime.utcnow().strftime("%Y-%m-%d")
    url = THESCORE_DAILY.format(date=date)
    data, res = fetch_json(url, headers=THESCORE_HEADERS)
    if not res.ok or data is None:
        return SourceResult("thescore", STATUS_ERROR, error=res.error)
    events = data if isinstance(data, list) else (data.get("events") or [])
    for ev in events:
        if _matches(ev, home, away):
            return _normalise(ev)
    return SourceResult("thescore", STATUS_PARTIAL,
                         error=f"target game not in TheScore feed on {date}",
                         meta={"sampled":
                               [((e.get('home_team') or {}).get('full_name'),
                                 (e.get('away_team') or {}).get('full_name'))
                                for e in events[:8]]})


def _normalise(ev: dict) -> SourceResult:
    status = (ev.get("status") or "").lower()
    state_map = {"pre_game": "pre", "in_progress": "in", "final": "post"}
    state = next((v for k, v in state_map.items() if k in status), "pre")
    game = {
        "id": ev.get("id"),
        "name": (ev.get("description") or "").strip(),
        "state": state,
        "status_detail": ev.get("status_string") or ev.get("status"),
        "period": ev.get("progress", {}).get("segment"),
        "clock": ev.get("progress", {}).get("clock"),
        "home": {
            "name": (ev.get("home_team") or {}).get("full_name"),
            "abbr": (ev.get("home_team") or {}).get("abbreviation"),
            "score": _to_int((ev.get("box_score") or {}).get("score", {})
                              .get("home", {}).get("score")),
        },
        "away": {
            "name": (ev.get("away_team") or {}).get("full_name"),
            "abbr": (ev.get("away_team") or {}).get("abbreviation"),
            "score": _to_int((ev.get("box_score") or {}).get("score", {})
                              .get("away", {}).get("score")),
        },
    }
    return SourceResult("thescore", STATUS_OK, records=[], meta={"game": game})


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
