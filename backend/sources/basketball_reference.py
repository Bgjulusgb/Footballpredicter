"""Basketball Reference: historical record scrape to refine Elo seeds.

Best-effort HTML scrape (BBRef rate-limits and hides tables in comments). We
only pull the season win-loss summary via regex; if anything fails, the model
falls back to its built-in Elo seeds, so this never blocks a run.
"""

import re

from .. import config
from ..http_util import fetch
from .base import SourceResult, STATUS_OK, STATUS_PARTIAL, STATUS_ERROR

# BBRef team-page abbreviations differ from ESPN/NBA tricodes.
_BREF_ABBR = {"CLE": "CLE", "NYK": "NYK", "NY": "NYK"}

_RECORD_RE = re.compile(r"Record:\s*</strong>\s*([0-9]+)-([0-9]+)", re.I)
_SRS_RE = re.compile(r"SRS</a>:\s*</strong>\s*(-?[0-9.]+)", re.I)


def _scrape_team(abbr):
    bref = _BREF_ABBR.get(abbr.upper(), abbr.upper())
    url = config.BREF_TEAM_PAGE.format(abbr=bref)
    res = fetch(url)
    if not res.ok:
        return None, res.error
    wins = losses = srs = None
    m = _RECORD_RE.search(res.body)
    if m:
        wins, losses = int(m.group(1)), int(m.group(2))
    m = _SRS_RE.search(res.body)
    if m:
        srs = float(m.group(1))
    if wins is None and srs is None:
        return None, "record/SRS not found in page"
    return {"abbr": abbr, "wins": wins, "losses": losses, "srs": srs}, None


def fetch_history(home=None, away=None):
    home = home or config.GAME["home"]
    away = away or config.GAME["away"]
    out = {}
    errors = []
    for side, team in (("home", home), ("away", away)):
        data, err = _scrape_team(team["abbr"])
        if data:
            out[side] = data
        else:
            errors.append(f"{team['abbr']}: {err}")

    if not out:
        return SourceResult("basketball_reference", STATUS_ERROR,
                            error="; ".join(errors))
    status = STATUS_OK if len(out) == 2 else STATUS_PARTIAL
    return SourceResult("basketball_reference", status,
                        meta={"teams": out}, error="; ".join(errors) or None)
