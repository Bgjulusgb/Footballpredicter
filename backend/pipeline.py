"""Pre-game pipeline: fetch all sources -> enrich/import -> compute -> write.

Produces data/snapshot.json, the file the dashboard reads. Each source runs in
isolation; a failure degrades gracefully (e.g. Reddit blocked -> news-only
sentiment) and is reported in the snapshot's "sources" section.
"""

import datetime as dt
import json
import os

from . import analysis, config, enrich, history, model
from .http_util import run_parallel
from .sources import espn, google_news, reddit, basketball_reference
from .sources.base import SourceResult, STATUS_ERROR


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _mode_from_state(state):
    return {"pre": "pre", "in": "live", "post": "post"}.get(state, "pre")


def _sentiment_timeline(records):
    """Group imported records by calendar day -> mean sentiment + volume."""
    buckets = {}
    for r in records:
        pub = r.get("published")
        day = "undated"
        if pub:
            day = pub[:10]
        b = buckets.setdefault(day, {"comps": [], "count": 0})
        b["comps"].append(r["sentiment"]["compound"])
        b["count"] += 1
    timeline = []
    for day in sorted(d for d in buckets if d != "undated"):
        comps = buckets[day]["comps"]
        timeline.append({
            "date": day,
            "mean_sentiment": round(sum(comps) / len(comps), 4),
            "volume": buckets[day]["count"],
        })
    return timeline


def _per_game_series_probs(ratings, ensemble_away_g4):
    """Knicks (leader, away team) win prob for each remaining game.

    Game 4 uses the market-blended ensemble; games 5-7 use Elo by venue.
    Schedule from Game 4: CLE, NYK, CLE, NYK.
    """
    r_cle, r_nyk = ratings["home"], ratings["away"]
    # NYK at NYK (home): NYK favored by HCA. NYK at CLE (away): subtract HCA.
    nyk_home = model.elo_expected(r_nyk, r_cle)               # NYK home win %
    nyk_away = 1 - model.elo_expected(r_cle, r_nyk)           # NYK away win %
    return [
        {"game": 4, "venue": "CLE", "leader_win": round(ensemble_away_g4, 4)},
        {"game": 5, "venue": "NYK", "leader_win": round(nyk_home, 4)},
        {"game": 6, "venue": "CLE", "leader_win": round(nyk_away, 4)},
        {"game": 7, "venue": "NYK", "leader_win": round(nyk_home, 4)},
    ]


def _resolve_market(game):
    """Market home/away probabilities from moneyline, else from the spread.

    Returns the devig dict (with a 'method' tag) or None.
    """
    if not game or not game.get("odds"):
        return None
    odds = game["odds"]
    market = model.devig_two_way(odds.get("home_moneyline"),
                                 odds.get("away_moneyline"))
    if market:
        market["method"] = "moneyline_devig"
        return market
    # Fallback: derive from the point spread (normal-CDF heuristic).
    spread = odds.get("spread")
    if spread is None:
        return None
    p_fav = model.prob_from_spread(spread)
    home_fav = odds.get("home_favorite")
    p_home = p_fav if home_fav else (1 - p_fav)
    return {"home": round(p_home, 4), "away": round(1 - p_home, 4),
            "overround": None, "margin_pct": None, "method": "spread_normal_cdf"}


def build_snapshot():
    # --- 1. Fetch every source CONCURRENTLY, each fully isolated ----------
    fetched = run_parallel({
        "espn": espn.fetch_game,
        "press": google_news.fetch_press_review,
        "reddit": reddit.fetch_social,
        "bref": basketball_reference.fetch_history,
    })

    def _safe(name, source_name):
        r = fetched.get(name)
        if isinstance(r, Exception):
            return SourceResult(source_name, STATUS_ERROR, error=str(r))
        return r

    espn_res = _safe("espn", "espn")
    news_res = _safe("press", "press_review")
    reddit_res = _safe("reddit", "reddit")
    bref_res = _safe("bref", "basketball_reference")

    sources = [espn_res, news_res, reddit_res, bref_res]

    # --- 2. Enrich + import (ok bypasses re-filter) -----------------------
    raw = list(news_res.records) + list(reddit_res.records)
    imported, import_stats = enrich.enrich_and_import(raw)

    press_review = [r for r in imported if r["kind"] == "article"]
    social = [r for r in imported if r["kind"] == "social"]

    # --- 3. Mood meters + per-team sentiment ------------------------------
    # Only matchup-relevant records feed the mood; "general" NBA news is kept
    # in the dataset but excluded here so it doesn't distort this game's read.
    relevant = [r for r in imported if r.get("team") in ("home", "away", "both")]
    home_recs = [r for r in imported if r.get("team") in ("home", "both")]
    away_recs = [r for r in imported if r.get("team") in ("away", "both")]
    mood = {
        "overall": model.mood_meters(relevant),
        "home": model.mood_meters(home_recs),
        "away": model.mood_meters(away_recs),
        "team_sentiment": model.team_sentiment(relevant),
        "timeline": _sentiment_timeline(relevant),
        "emotions": analysis.emotion_profile(relevant),
    }

    # --- 3b. Deeper analysis: players, narratives -------------------------
    players = analysis.player_sentiment(imported)
    narratives = analysis.narratives(imported)

    # --- 4. Prediction math -----------------------------------------------
    game = espn_res.meta.get("game") if espn_res.meta else None
    market = _resolve_market(game)

    ratings = model.elo_from_history(bref_res.meta if bref_res.meta else None)
    p_elo_home = model.elo_expected(ratings["home"], ratings["away"])
    ts = mood["team_sentiment"]
    delta = model.sentiment_delta(ts)

    p_market_home = market["home"] if market else None
    ens = model.ensemble(p_market_home, p_elo_home, delta)
    conf = model.confidence(p_market_home, p_elo_home,
                            ts["count_home"] + ts["count_away"])

    per_game = _per_game_series_probs(ratings, ens["away"])
    clinch = model.series_clinch([g["leader_win"] for g in per_game])

    value = analysis.value_bet(market, ens, game.get("odds") if game else None)

    prediction = {
        "market": market,
        "elo": {
            "home": round(p_elo_home, 4),
            "away": round(1 - p_elo_home, 4),
            "ratings": {k: round(v, 1) for k, v in ratings.items()},
        },
        "sentiment_delta": round(delta, 4),
        "ensemble": ens,
        "confidence": conf,
        "value_bet": value,
        "series": {
            "leader": config.GAME["series"]["leader"],
            "lead": config.GAME["series"]["lead"],
            "leader_clinch_probability": clinch,
            "per_game": per_game,
        },
    }

    state = game.get("state") if game else "pre"
    snapshot = {
        "generated_at": _now_iso(),
        "mode": _mode_from_state(state),
        "game": game,
        "series": config.GAME["series"],
        "venue": config.GAME["venue"],
        "label": config.GAME["label"],
        "teams": {"home": config.GAME["home"], "away": config.GAME["away"]},
        "sources": [s.to_dict() for s in sources],
        "press_review": sorted(press_review,
                               key=lambda r: r.get("published") or "",
                               reverse=True),
        "social": sorted(social, key=lambda r: r.get("engagement", 0),
                         reverse=True),
        "mood": mood,
        "players": players,
        "narratives": narratives,
        "prediction": prediction,
        "import_stats": import_stats,
    }
    # Append to the rolling history, then attach the recent tail for trends.
    history.append(snapshot)
    snapshot["history"] = history.load_recent()
    return snapshot


def write_snapshot(path=None):
    path = path or config.SNAPSHOT_PATH
    snapshot = build_snapshot()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    return snapshot, path
