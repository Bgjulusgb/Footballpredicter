"""ESPN hidden scoreboard API: live score + status + odds + leaders.

Free, keyless, reliable. One endpoint covers the Live layer and the Odds
layer. We query by date and pick the event whose teams match the target game.

URL: https://site.api.espn.com/.../nba/scoreboard?dates=YYYYMMDD
"""

from .. import config
from ..http_util import fetch_json
from .base import SourceResult, STATUS_OK, STATUS_PARTIAL, STATUS_ERROR


def _matches(competitors, home, away):
    abbrs = {c.get("team", {}).get("abbreviation", "").upper() for c in competitors}
    names = " ".join(c.get("team", {}).get("displayName", "").lower()
                     for c in competitors)
    want = {home["espn_abbr"].upper(), away["espn_abbr"].upper()}
    if want & abbrs == want:
        return True
    # Fallback to name aliases when abbreviations differ across feeds.
    home_ok = any(a in names for a in home["aliases"])
    away_ok = any(a in names for a in away["aliases"])
    return home_ok and away_ok


def _ml_from_block(block):
    """Pull an American moneyline int from a {close/open: {odds: '+110'}} block."""
    if not block:
        return None
    for when in ("close", "current", "open"):
        leg = block.get(when) or {}
        raw = leg.get("odds")
        if raw is None:
            continue
        try:
            return int(str(raw).replace("+", ""))
        except (TypeError, ValueError):
            continue
    return None


def _extract_odds(competition):
    odds_list = competition.get("odds") or []
    if not odds_list:
        return None
    o = odds_list[0]
    home_odds = o.get("homeTeamOdds", {}) or {}
    away_odds = o.get("awayTeamOdds", {}) or {}
    # Moneyline lives either flat on *TeamOdds.moneyLine or nested under
    # odds[].moneyline.{home,away}.close.odds depending on the feed shape.
    ml = o.get("moneyline") or {}
    home_ml = home_odds.get("moneyLine")
    if home_ml is None:
        home_ml = _ml_from_block(ml.get("home"))
    away_ml = away_odds.get("moneyLine")
    if away_ml is None:
        away_ml = _ml_from_block(ml.get("away"))
    return {
        "provider": (o.get("provider") or {}).get("name", "consensus"),
        "details": o.get("details"),
        "over_under": o.get("overUnder"),
        "spread": o.get("spread"),
        "home_moneyline": home_ml,
        "away_moneyline": away_ml,
        "home_favorite": home_odds.get("favorite"),
        "away_favorite": away_odds.get("favorite"),
    }


def _extract_leaders(competition):
    out = []
    for comp in competition.get("competitors", []):
        team = comp.get("team", {}).get("abbreviation")
        for cat in comp.get("leaders", []) or []:
            for ldr in cat.get("leaders", [])[:1]:
                ath = ldr.get("athlete", {})
                out.append({
                    "team": team,
                    "category": cat.get("name"),
                    "name": ath.get("shortName") or ath.get("displayName"),
                    "value": ldr.get("displayValue"),
                })
    return out


def fetch_game(date=None, home=None, away=None):
    """Return a SourceResult whose meta['game'] holds the structured game."""
    date = (date or config.GAME["date_et"]).replace("-", "")
    home = home or config.GAME["home"]
    away = away or config.GAME["away"]
    url = f"{config.ESPN_SCOREBOARD}?dates={date}"

    data, res = fetch_json(url)
    if not res.ok or data is None:
        return SourceResult("espn", STATUS_ERROR, error=res.error)

    events = data.get("events", [])
    target = None
    for ev in events:
        comps = (ev.get("competitions") or [{}])[0].get("competitors", [])
        if _matches(comps, home, away):
            target = ev
            break

    if target is None:
        return SourceResult(
            "espn", STATUS_PARTIAL,
            error=f"target game not found among {len(events)} events on {date}",
            meta={"events_seen": [e.get("shortName") for e in events]},
        )

    comp = target["competitions"][0]
    status = comp.get("status", {}) or target.get("status", {})
    stype = status.get("type", {}) or {}
    competitors = {c.get("homeAway"): c for c in comp.get("competitors", [])}

    def side(key):
        c = competitors.get(key, {})
        t = c.get("team", {})
        return {
            "name": t.get("displayName"),
            "abbr": t.get("abbreviation"),
            "score": _to_int(c.get("score")),
            "record": (c.get("records") or [{}])[0].get("summary"),
        }

    game = {
        "id": target.get("id"),
        "name": target.get("shortName"),
        "date": target.get("date"),
        "state": stype.get("state"),         # pre | in | post
        "detail": stype.get("detail"),
        "completed": stype.get("completed", False),
        "period": status.get("period"),
        "clock": status.get("displayClock"),
        "home": side("home"),
        "away": side("away"),
        "odds": _extract_odds(comp),
        "leaders": _extract_leaders(comp),
    }
    status_flag = STATUS_OK if game["odds"] else STATUS_PARTIAL
    return SourceResult("espn", status_flag, records=[], meta={"game": game})


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
