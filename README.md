# NBA Mood Mirror & Press Review

A free, no-API-key sentiment analyzer, press review ("Presse Spiegel") and
prediction dashboard for an NBA game. It blends **analyst/press coverage**,
**fan social sentiment**, **betting odds** and **historical strength** into one
mood picture and a win-probability prediction, and switches into a **live mode**
during the game that detects scoring runs, momentum swings and fan-sentiment
spikes.

Built around: **New York Knicks @ Cleveland Cavaliers — Eastern Conference
Finals, Game 4** (Mon May 25, 2026, 8:00 PM ET, Rocket Arena; Knicks lead 3-0).
The target game is configurable in `backend/config.py`.

Everything is **English-only** and uses **free, keyless** data sources — no API
costs.

---

## Architecture

```
 free web sources ──►  Python backend (stdlib only)  ──►  data/*.json  ──►  index.html (React dashboard)
 (ESPN, Google News,    fetch → enrich → math → write       snapshot.json       reads JSON, auto-refresh
  Reddit, NBA.com,                                          live.json
  Basketball Ref.)
```

- **Backend — Python 3, standard library only** (`urllib`, `json`,
  `xml.etree`, `re`, `math`, `statistics`). No `pip install`, no keys, no cost.
  Does all scraping, sentiment and prediction math, and writes JSON files.
- **Frontend — single static `index.html`** (React 17 + Recharts via CDN, no
  build step). Reads `data/snapshot.json` and `data/live.json` same-origin and
  auto-refreshes.
- **Serving — your choice (both free):** `python3 -m http.server` **or** the
  included zero-dependency `node server.js`.

Why Python-primary (not a heavier Node + Playwright stack): every source we use
is JSON or RSS, which the Python stdlib parses directly. Headless browsers would
add fragility and downloads without improving these sources. `server.js` is
provided so a Node-based setup is still a one-command option.

---

## Quick start

```bash
# 1. Generate the pre-game snapshot
python3 -m backend.run snapshot

# 2. Serve the dashboard (pick one)
python3 -m http.server 8000        # then open http://localhost:8000/
#   or:  node server.js

# 3. During the game, run live mode in another terminal
python3 -m backend.run live        # polls every 25s, writes data/live.json
#   one-shot:        python3 -m backend.run live --once
#   test it now:     python3 -m backend.run live --fixture data/fixture_pbp.json

# auto: snapshot, then start live mode automatically if the game is on
python3 -m backend.run auto

# run the tests
python3 -m unittest backend.tests
```

> Open the dashboard **over HTTP**, not by double-clicking the file —
> `file://` blocks the JSON `fetch`.

---

## Data sources (all free / keyless)

| Layer | Source | Endpoint | Status in this sandbox |
|-------|--------|----------|------------------------|
| Live + Odds | **ESPN** hidden scoreboard | `site.api.espn.com/.../nba/scoreboard?dates=` | works |
| Press review | **Google News RSS** + ESPN NBA RSS | `news.google.com/rss/search?q=` | works |
| Historical / Elo | **Basketball Reference** | team season page (record + SRS) | works |
| Fan sentiment | **Reddit** `.json` (r/nba, team subs, r/sportsbook) | `reddit.com/r/<sub>/hot.json` | blocked by egress policy here* |
| Live play-by-play | **NBA.com** live CDN | `cdn.nba.com/static/json/liveData/...` | flaky / bot-protected* |

\* These two are best-effort. Each source is fully isolated, so if one is
unreachable the run still succeeds and the dashboard shows its status
(`ok` / `partial` / `error`). Reddit/NBA.com work from a normal machine (or with
a more permissive network policy); when Reddit is blocked the system simply
falls back to **news-only** sentiment.

Twitter/X and YouTube live chat are intentionally **excluded** — they no longer
have a free, keyless API and would break the no-cost rule.

Per-source scrapers live in `backend/sources/` — each is "individually tailored"
to its website (URL shape, headers, parser, retry/backoff) and returns the same
normalised record so adding a new site only means writing one module.

---

## Enrichment & the "ok imports directly" rule

`backend/enrich.py` scores every article/post (sentiment + team attribution) and
assigns a **status**:

- **`ok`** → has a title, URL, team attribution and timestamp → **imported
  directly, with no second filtering pass** (this is the explicit requirement).
- **`partial`** → missing attribution/timestamp → one light **repair** pass,
  then imported (general NBA chatter is tagged `general` so it does not pollute
  this matchup's mood).
- **`error`** → no title/URL → dropped.

The snapshot reports `import_stats` (`ok` / `partial` / `repaired` / `dropped`).

---

## The mathematics (`backend/model.py`)

Several independent formulas, then an ensemble:

1. **Odds → implied probability + de-vig** — `1/decimal` per outcome,
   normalised to remove the bookmaker margin (American↔decimal conversion
   included).
2. **Spread → probability fallback** — when only a point spread is published,
   `Φ(spread / σ)` with NBA margin `σ ≈ 12`.
3. **Elo / log5** — `1 / (1 + 10^(-(R_home + HCA − R_away)/400))`, home-court
   bump, Elo seeds refined by Basketball-Reference SRS.
4. **Sentiment-adjusted probability** — bounded nudge
   `SENT_MAX · tanh(k · (sent_home − sent_away))`, capped at ±6 pts so sentiment
   never overrides the market.
5. **Heat / Hype / Toxicity meters (0–100)** — saturating combinations of
   volume, engagement, sentiment magnitude/variance and toxicity density.
6. **Live momentum + run detection** — current uninterrupted scoring run, plus
   exponential-time-decay scoring differential.
7. **Sentiment-spike detection** — rolling z-score of bucketed comment
   sentiment (drives "fan panic / hype surge" alerts).
8. **Ensemble + confidence** — `0.65·market + 0.35·Elo + sentiment nudge`, with
   a confidence score from cross-model agreement and sample size.
9. **Series-clinch probability** — from a 3-0 lead, `1 − Π(1 − p_leader,game)`
   over the remaining venue-adjusted games.

All formulas are covered by `backend/tests.py` (20 tests).

---

## Project layout

```
backend/
  config.py                 # target game + source URLs + tuning
  http_util.py              # urllib fetch with UA, gzip, retry/backoff
  sentiment.py              # VADER-style lexicon scorer + NBA/toxicity lexicons
  enrich.py                 # sentiment + attribution + status + import rule
  model.py                  # all prediction math
  pipeline.py               # pre-game: fetch → enrich → compute → snapshot.json
  live.py                   # live mode: momentum/runs/spikes → live.json
  run.py                    # CLI (snapshot | live | auto)
  tests.py                  # unit tests
  sources/                  # one tailored scraper per website
    espn.py  google_news.py  reddit.py  nba_cdn.py  basketball_reference.py
data/
  snapshot.json             # generated pre-game data
  live.json                 # generated live data
  fixture_pbp.json          # synthetic play-by-play to test live mode
index.html                  # the dashboard (Mood / Press / Prediction / Live)
server.js                   # optional zero-dependency Node static server
```

---

## Roadmap / extension ideas

Practical, still-free next steps:

- **Persist history** — append each snapshot to a local SQLite/JSONL log to get
  real odds-movement and sentiment trends over time (today's timeline is press
  coverage only).
- **Reddit comment-level sentiment** — when reachable, descend into top comment
  threads for finer fan signal and per-player sentiment.
- **Player-level entity extraction** — attribute sentiment to individual players
  (Brunson, Mitchell, …) for a per-player heat map.
- **Calibrated sentiment weight** — backtest the sentiment nudge against past
  game outcomes to tune the cap/weights empirically.
- **More odds books** — ESPN exposes several providers; compare lines and flag
  the best value bet (de-vig vs. market consensus).
- **WebSocket push** — replace polling with a small live server if sub-second
  updates are ever needed.
- **Auto-discover the game** — pick the live NBA playoff game from the scoreboard
  automatically instead of hard-coding the matchup.
