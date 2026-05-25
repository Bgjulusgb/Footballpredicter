"""Prediction mathematics.

Several independent formulas, then an ensemble:

  1. Odds  -> implied probability + DE-VIG (remove bookmaker margin)
  2. Elo / log5 win probability (with home-court advantage)
  3. Sentiment-adjusted probability (bounded, never dominates the market)
  4. Heat / Hype / Toxicity meters (0..100)
  5. Live momentum + scoring-run detection (exponential time decay)
  6. Sentiment-spike detection (rolling z-score)
  7. Ensemble win probability + cross-source confidence
  8. Series-clinch probability given the 3-0 lead

Everything is pure Python (math/statistics only).
"""

import math
import statistics

from . import config

# --- Elo seeds (refined by Basketball Reference SRS when available) --------
ELO_SEED = {"home": 1600.0, "away": 1612.0}   # CLE / NYK baseline
HOME_COURT_ELO = 100.0                         # ~ +100 Elo for the home side
ELO_PER_SRS = 28.0                             # Elo points per SRS point

# Ensemble weights for market vs Elo (sum to 1). Sentiment is a bounded add-on.
W_MARKET = 0.65
W_ELO = 0.35
SENT_MAX_DELTA = 0.06                          # max +-6 pts from sentiment
SENT_K = 1.5                                   # sentiment differential gain


# ===========================================================================
# 1. Odds -> implied probability + de-vig
# ===========================================================================
def american_to_decimal(american):
    if american is None:
        return None
    a = float(american)
    if a > 0:
        return 1.0 + a / 100.0
    return 1.0 + 100.0 / abs(a)


def decimal_to_implied(decimal):
    if not decimal or decimal <= 1.0:
        return None
    return 1.0 / decimal


# NBA single-game margin standard deviation (points). Used to turn a point
# spread into a win probability via the normal CDF.
MARGIN_SIGMA = 12.0


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def prob_from_spread(spread, sigma=MARGIN_SIGMA):
    """Favorite win probability implied by a point spread magnitude."""
    if spread is None:
        return None
    return _norm_cdf(abs(spread) / sigma)


def devig_two_way(home_ml, away_ml):
    """Remove the bookmaker margin from a two-way moneyline.

    Returns {'home', 'away', 'overround'} where probs sum to 1. Accepts
    American odds (the format ESPN returns).
    """
    dh = american_to_decimal(home_ml)
    da = american_to_decimal(away_ml)
    ph = decimal_to_implied(dh)
    pa = decimal_to_implied(da)
    if ph is None or pa is None:
        return None
    overround = ph + pa                  # > 1 because of the vig
    return {
        "home": ph / overround,
        "away": pa / overround,
        "overround": overround,
        "margin_pct": round((overround - 1.0) * 100, 2),
    }


# ===========================================================================
# 2. Elo / log5
# ===========================================================================
def elo_expected(rating_home, rating_away, home_court=HOME_COURT_ELO):
    """Expected score (= win probability) for the home team."""
    diff = (rating_home + home_court) - rating_away
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))


def log5(p_a, p_b):
    """log5: probability A beats B given each team's base win rate."""
    denom = p_a * (1 - p_b) + (1 - p_a) * p_b
    if denom == 0:
        return 0.5
    return (p_a * (1 - p_b)) / denom


def elo_from_history(bref_meta):
    """Refine Elo seeds using Basketball Reference SRS if present."""
    home = dict(home=ELO_SEED["home"])
    ratings = {"home": ELO_SEED["home"], "away": ELO_SEED["away"]}
    teams = (bref_meta or {}).get("teams", {})
    for side in ("home", "away"):
        srs = (teams.get(side) or {}).get("srs")
        if srs is not None:
            ratings[side] = 1500.0 + srs * ELO_PER_SRS
    return ratings


# ===========================================================================
# 3. Sentiment-adjusted probability (bounded)
# ===========================================================================
def sentiment_delta(team_sentiment):
    """Bounded probability nudge for the home team from sentiment differential.

    team_sentiment: {'home': mean_compound, 'away': mean_compound} in [-1,1].
    Returns a delta in [-SENT_MAX_DELTA, +SENT_MAX_DELTA].
    """
    diff = team_sentiment.get("home", 0.0) - team_sentiment.get("away", 0.0)
    return SENT_MAX_DELTA * math.tanh(SENT_K * diff)


# ===========================================================================
# 4. Heat / Hype / Toxicity meters (0..100)
# ===========================================================================
def _saturate(x, scale):
    """Map [0, inf) -> [0, 100) with a saturating curve."""
    return 100.0 * (1.0 - math.exp(-x / scale))


def mood_meters(records):
    """Compute Heat Index, Hype Meter, Toxicity Meter from social/article recs."""
    if not records:
        return {"heat": 0.0, "hype": 0.0, "toxicity": 0.0, "volume": 0,
                "mean_sentiment": 0.0}

    comps = [r["sentiment"]["compound"] for r in records if "sentiment" in r]
    toxes = [r["sentiment"]["toxicity"] for r in records if "sentiment" in r]
    engagement = sum(max(0, r.get("engagement", 0)) for r in records)
    volume = len(records)

    mean_comp = statistics.fmean(comps) if comps else 0.0
    var_comp = statistics.pvariance(comps) if len(comps) > 1 else 0.0
    mean_tox = statistics.fmean(toxes) if toxes else 0.0

    # Heat = how much is being said + emotional spread (engagement + variance).
    # Scale chosen so a heavily-covered marquee game sits in the 70-90 band
    # rather than pinning at 100, keeping the meter discriminative.
    heat = _saturate(volume + engagement / 200.0 + var_comp * 60.0, scale=260.0)

    # Hype = mean positive emotional energy per item, with a bounded volume
    # bonus, so it reflects intensity rather than raw article count.
    n = len(records)
    pos_energy = sum(max(0.0, r["sentiment"]["compound"]) *
                     (1 + max(0, r.get("engagement", 0)) / 100.0)
                     for r in records if "sentiment" in r)
    mean_pos = pos_energy / n if n else 0.0
    hype = min(100.0, mean_pos * 130.0 + _saturate(volume, scale=400.0) * 0.35)

    # Toxicity = mean toxicity boosted by negative-sentiment density.
    neg_density = sum(1 for c in comps if c <= -0.35) / max(1, len(comps))
    toxicity = min(100.0, (mean_tox * 70.0) + neg_density * 60.0)

    return {
        "heat": round(heat, 1),
        "hype": round(hype, 1),
        "toxicity": round(toxicity, 1),
        "volume": volume,
        "engagement": engagement,
        "mean_sentiment": round(mean_comp, 4),
        "sentiment_variance": round(var_comp, 4),
    }


def team_sentiment(records):
    """Mean compound sentiment per team ('home'/'away'), engagement-weighted."""
    buckets = {"home": [], "away": []}
    weights = {"home": [], "away": []}
    for r in records:
        team = r.get("team")
        if team not in ("home", "away"):
            continue
        comp = r.get("sentiment", {}).get("compound", 0.0)
        w = 1.0 + max(0, r.get("engagement", 0)) / 100.0
        buckets[team].append(comp * w)
        weights[team].append(w)

    out = {}
    for side in ("home", "away"):
        if buckets[side]:
            out[side] = round(sum(buckets[side]) / sum(weights[side]), 4)
        else:
            out[side] = 0.0
    out["count_home"] = len(buckets["home"])
    out["count_away"] = len(buckets["away"])
    return out


# ===========================================================================
# 5. Live momentum + run detection
# ===========================================================================
def detect_current_run(scoring_events):
    """Find the active scoring run from ordered scoring events.

    scoring_events: list of {'team': tricode, 'points': int} in time order.
    Returns {'team', 'points'} for the most recent uninterrupted run.
    """
    run_team = None
    run_points = 0
    for ev in reversed(scoring_events):
        if ev.get("points", 0) <= 0:
            continue
        team = ev.get("team")
        if run_team is None:
            run_team, run_points = team, ev["points"]
        elif team == run_team:
            run_points += ev["points"]
        else:
            break
    return {"team": run_team, "points": run_points}


def momentum(scoring_events, half_life=6):
    """Exponentially-weighted recent scoring differential (home minus away).

    Positive => home momentum. `half_life` is measured in scoring events.
    """
    decay = math.log(2) / half_life
    home_tri = config.GAME["home"]["abbr"]
    score = 0.0
    weight_sum = 0.0
    n = len(scoring_events)
    for i, ev in enumerate(scoring_events):
        pts = ev.get("points", 0)
        if pts <= 0:
            continue
        age = n - 1 - i
        w = math.exp(-decay * age)
        signed = pts if ev.get("team") == home_tri else -pts
        score += signed * w
        weight_sum += w * pts
    if weight_sum == 0:
        return 0.0
    return round(score / weight_sum, 4)        # in [-1, 1]


# ===========================================================================
# 6. Sentiment-spike detection (rolling z-score over time buckets)
# ===========================================================================
def sentiment_spike(bucket_values):
    """z-score of the latest bucket vs the rolling history.

    bucket_values: chronological list of per-bucket metric (e.g. mean
    sentiment or volume). Returns z-score of the last bucket (0 if too few).
    """
    if len(bucket_values) < 3:
        return 0.0
    history = bucket_values[:-1]
    mu = statistics.fmean(history)
    sigma = statistics.pstdev(history)
    if sigma == 0:
        return 0.0
    return round((bucket_values[-1] - mu) / sigma, 3)


# ===========================================================================
# 7. Ensemble + confidence
# ===========================================================================
def ensemble(p_market, p_elo, sent_delta):
    """Blend market + Elo, then apply the bounded sentiment nudge.

    All probabilities are for the HOME team. Returns home/away + components.
    """
    components = {}
    parts = []
    weight = 0.0
    if p_market is not None:
        parts.append(W_MARKET * p_market)
        weight += W_MARKET
        components["market"] = round(p_market, 4)
    if p_elo is not None:
        parts.append(W_ELO * p_elo)
        weight += W_ELO
        components["elo"] = round(p_elo, 4)

    base = (sum(parts) / weight) if weight else 0.5
    home = base + (sent_delta or 0.0)
    home = max(0.01, min(0.99, home))
    components["sentiment_delta"] = round(sent_delta or 0.0, 4)
    return {"home": round(home, 4), "away": round(1 - home, 4),
            "components": components}


def confidence(p_market, p_elo, n_sentiment):
    """0..100 confidence from model agreement + sentiment sample size."""
    preds = [p for p in (p_market, p_elo) if p is not None]
    if len(preds) >= 2:
        spread = abs(preds[0] - preds[1])
        agreement = max(0.0, 1.0 - spread / 0.25)     # 0 spread -> 1
    else:
        agreement = 0.5
    data_factor = min(1.0, n_sentiment / 40.0)
    return round(100.0 * (0.7 * agreement + 0.3 * data_factor), 1)


# ===========================================================================
# 8. Series-clinch probability (best-of-7, leader at 3-0)
# ===========================================================================
def series_clinch(leader_game_probs):
    """Probability the 3-0 leader wins the series.

    The leader needs ONE more win, so the trailer must win EVERY remaining
    game. leader_game_probs: list of P(leader wins) for each remaining game
    (already venue-adjusted). Series-win = 1 - P(trailer sweeps the rest).
    """
    p_trailer_wins_all = 1.0
    for p in leader_game_probs:
        p_trailer_wins_all *= (1 - p)
    return round(1 - p_trailer_wins_all, 4)
