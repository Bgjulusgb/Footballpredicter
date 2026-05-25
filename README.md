# 🏀 NBA Mood Mirror & Press Review

> Real-time **sentiment analysis**, **press review** ("Presse Spiegel") and a
> multi-model **win-probability prediction** for an NBA game — built entirely on
> **free, keyless** data sources. No API keys, no paid services, no build step.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Dependencies](https://img.shields.io/badge/backend-stdlib%20only-informational)
![API keys](https://img.shields.io/badge/API%20keys-none-success)
![Cost](https://img.shields.io/badge/cost-%240-success)
![Tests](https://img.shields.io/badge/tests-27%20passing-brightgreen)
![Language](https://img.shields.io/badge/language-English-lightgrey)

It blends **analyst & press coverage**, **fan social sentiment**, **betting
odds** and **historical team strength** into one live mood picture and a
prediction, then switches into a **live in-game mode** that detects scoring
runs, momentum swings and fan-sentiment spikes ("AI detects fan panic after a
12-0 run").

Centred on **New York Knicks @ Cleveland Cavaliers — Eastern Conference Finals,
Game 4** (Mon May 25, 2026, 8 PM ET, Rocket Arena; Knicks lead 3-0). The target
game is fully configurable in [`backend/config.py`](backend/config.py).

---

## Table of contents

- [Features](#features)
- [How it looks](#how-it-looks)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Data sources](#data-sources-all-free--keyless)
- [Analytics & mathematics](#analytics--mathematics)
- [The "ok imports directly" rule](#the-ok-imports-directly-rule)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Configuration](#configuration)
- [Roadmap](#roadmap)
- [Keywords](#keywords)

---

## Features

**Data collection**
- Per-website tailored scrapers (one module each), fetched **concurrently** so a
  full refresh takes a couple of seconds and one broken source never aborts the run.
- 7 Google-News search angles + Yahoo + CBS + ESPN RSS for a broad press review.
- Live scores, game status **and odds** from one free ESPN endpoint.
- Best-effort Reddit and NBA.com live play-by-play with graceful fallback.

**Analysis**
- VADER-style **sentiment engine** with a custom NBA + toxicity lexicon
  (`clutch`, `washed`, `rigged`, `choke`, `MVP`, `refball`, …).
- **Emotion breakdown** (joy / anger / fear / sadness / anticipation).
- **Player-level sentiment & buzz** (roster-aware, avoids shared-surname collisions).
- **Narrative tracker** — trending storylines and the sentiment around each.
- **Heat / Hype / Toxicity** meters.

**Prediction (several independent models + ensemble)**
- Odds → implied probability with **de-vig**, spread→prob fallback,
  **Elo / log5**, bounded **sentiment adjustment**, **value-bet** edge + EV,
  cross-model **confidence**, and **series-clinch** probability.

**Live mode**
- Scoring-**run detection**, exponential-decay **momentum**, rolling-z-score
  **sentiment spikes**, and auto-generated alert headlines.

**History & UI**
- Every run is appended to a rolling history → real **movement charts** over time.
- Single-file React dashboard (Mood Mirror · Press Review · Prediction · Live)
  with auto-refresh, dark mode, search and filters.

---

## How it looks

Four tabs, all reading the JSON the backend writes:

| Tab | Shows |
|-----|-------|
| **Mood Mirror** | Heat/Hype/Toxicity meters, team & player sentiment, emotion breakdown, trending narratives, sentiment timeline |
| **Press Review** | Searchable, sentiment-scored article feed (outlet + timestamp + team) |
| **Prediction** | De-vigged market, Elo, ensemble win %, value bet, series-clinch, movement-across-runs chart |
| **Live** | Live score, current run, momentum, sentiment-spike, alerts, score progression |

> Tip: open over **HTTP** (`http://localhost:8000/`), not `file://` — browsers
> block the JSON `fetch` on the `file://` protocol.

---

## Architecture

```
 free web sources ─►  Python backend (stdlib only)  ─►  data/*.json  ─►  index.html (React + Recharts)
 ESPN · GoogleNews     fetch (parallel) → enrich →        snapshot.json     reads JSON, auto-refresh,
 Yahoo · CBS · Reddit   analyse → math → persist          live.json         no build step
 NBA.com · Bball-Ref                                       history.jsonl
```

- **Backend — Python 3, standard library only.** No `pip install`, no keys.
  Does all scraping, sentiment, analytics and prediction math, then writes JSON.
- **Frontend — one static `index.html`** (React 17 + Recharts via CDN).
- **Serving — your choice, both free:** `python3 -m http.server` **or** the
  bundled zero-dependency `node server.js`.

Why Python-primary instead of a heavy Node + headless-browser stack: every
source we use is JSON or RSS, which the Python stdlib parses directly — a
headless browser would add fragility and downloads without helping. `server.js`
is included so a Node-only setup remains a one-command option.

---

## Quick start

```bash
# 1) Build the pre-game snapshot (fetches sources, runs the analysis + math)
python3 -m backend.run snapshot

# 2) Serve the dashboard (pick one), then open http://localhost:8000/
python3 -m http.server 8000
#   or:  node server.js

# 3) During the game, run live mode in another terminal
python3 -m backend.run live                                  # polls every 25s
python3 -m backend.run live --once                           # single update
python3 -m backend.run live --fixture data/fixture_pbp.json  # demo it right now

# auto: snapshot, then start live mode automatically if the game is on
python3 -m backend.run auto

# tests
python3 -m unittest backend.tests
```

---

## Data sources (all free / keyless)

| Layer | Source | What we use | Reliability |
|-------|--------|-------------|-------------|
| Live + Odds | **ESPN** hidden scoreboard | score, status, leaders, moneyline/spread/total | ✅ solid |
| Press review | **Google News**, **Yahoo**, **CBS**, ESPN RSS | headlines + outlet + time | ✅ solid |
| Historical / Elo | **Basketball Reference** | season record + SRS → Elo seed | ✅ works |
| Fan sentiment | **Reddit** `.json` (r/nba, team subs, r/sportsbook) | posts, upvotes, comments | ⚠️ best-effort* |
| Live play-by-play | **NBA.com** live CDN | scoring events for run detection | ⚠️ best-effort* |

\* Reddit and NBA.com may be blocked by a restrictive network/egress policy; the
system detects this and **degrades gracefully** (news-only sentiment) — every
source's `ok / partial / error` status is shown live in the dashboard. They work
from a normal machine or with a more permissive network policy.

Twitter/X and YouTube live chat are intentionally **excluded** — they no longer
offer a free, keyless API, which would break the no-cost rule.

---

## Analytics & mathematics

All implemented from scratch in pure Python (`backend/model.py`,
`backend/analysis.py`) and covered by tests:

1. **Odds → de-vigged probability** — `1/decimal` per outcome, normalised to
   strip the bookmaker margin (American↔decimal conversion included).
2. **Spread → probability fallback** — `Φ(spread / σ)`, NBA margin `σ ≈ 12`.
3. **Elo / log5** — `1 / (1 + 10^(-(R_home + HCA − R_away)/400))`, Elo seeds
   refined by Basketball-Reference SRS.
4. **Sentiment-adjusted probability** — bounded `SENT_MAX · tanh(k · Δsentiment)`
   (±6 pts cap, so sentiment never overrides the market).
5. **Heat / Hype / Toxicity meters** — saturating combinations of volume,
   engagement, sentiment magnitude/variance and toxicity density.
6. **Emotion classification** — lexicon-based joy/anger/fear/sadness/anticipation.
7. **Player sentiment & narratives** — roster-aware mention/sentiment aggregation.
8. **Value bet** — model edge vs. market + expected value at the offered price.
9. **Live momentum + run detection** + **sentiment-spike z-score**.
10. **Ensemble + confidence** — `0.65·market + 0.35·Elo + sentiment nudge`,
    confidence from cross-model agreement and sample size.
11. **Series-clinch** — from 3-0, `1 − Π(1 − p_leader,game)` over remaining
    venue-adjusted games.

---

## The "ok imports directly" rule

`backend/enrich.py` scores every item (sentiment + team attribution) and assigns
a **status**:

- **`ok`** → complete record → **imported directly, with no second filtering
  pass** (the explicit project requirement).
- **`partial`** → one light **repair** pass, then imported (general NBA chatter
  is tagged `general` so it never pollutes this matchup's mood).
- **`error`** → dropped.

Every snapshot reports `import_stats` (`ok` / `partial` / `repaired` / `dropped`).

---

## Project layout

```
backend/
  config.py                 # target game, rosters, source URLs, tuning
  http_util.py              # urllib fetch (gzip, retry/backoff) + parallel runner
  sentiment.py              # VADER-style scorer + NBA/toxicity/emotion lexicons
  enrich.py                 # sentiment + attribution + status + import rule
  analysis.py               # players, narratives, emotions, value bet
  model.py                  # all prediction math
  history.py                # rolling history (data/history.jsonl) for trends
  pipeline.py               # pre-game: fetch(parallel) → enrich → analyse → snapshot.json
  live.py                   # live mode: runs/momentum/spikes → live.json
  run.py                    # CLI (snapshot | live | auto)
  tests.py                  # 27 unit tests
  sources/                  # one tailored scraper per website
    espn.py  google_news.py  reddit.py  nba_cdn.py  basketball_reference.py
data/
  snapshot.json             # generated pre-game data (committed as a live demo)
  live.json                 # generated live data (git-ignored, transient)
  history.jsonl             # rolling metric history (git-ignored)
  fixture_pbp.json          # synthetic play-by-play to demo live mode
index.html                  # the dashboard (Mood · Press · Prediction · Live)
server.js                   # optional zero-dependency Node static server
```

---

## Testing

```bash
python3 -m unittest backend.tests       # 27 tests, pure stdlib, no network
```

Covers the sentiment engine, emotion classifier, odds de-vig, Elo, ensemble
bounding, run/momentum/spike detection, series-clinch, player attribution,
narratives, value bet, the import rule and history round-trip.

---

## Configuration

Edit [`backend/config.py`](backend/config.py) to point at a different game:
`GAME` (teams, date, venue, series), `ROSTERS`, the source URLs/queries, and
tuning constants (Elo seeds, ensemble weights, sentiment cap, poll interval).

---

## Roadmap

- Reddit comment-thread descent for finer fan signal (when reachable).
- Calibrate the sentiment weight by back-testing against past outcomes.
- Compare multiple sportsbooks and flag the sharpest line.
- Auto-discover the live playoff game from the scoreboard.
- Optional WebSocket push instead of polling for sub-second live updates.

---

## Keywords

`NBA` · `sentiment analysis` · `sports analytics` · `press review` ·
`win probability` · `betting odds` · `de-vig` · `Elo` · `VADER` ·
`Reddit` · `ESPN API` · `Google News RSS` · `Basketball Reference` ·
`Python` · `React` · `Recharts` · `no API key` · `free` · `live scraper` ·
`Knicks` · `Cavaliers` · `Eastern Conference Finals`

> Suggested GitHub repo **topics** (set in the repo's *About* panel for
> discoverability): `nba`, `sentiment-analysis`, `sports-analytics`,
> `web-scraping`, `python`, `react`, `data-visualization`, `prediction`.
