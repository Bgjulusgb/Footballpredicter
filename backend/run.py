"""Command-line entrypoint for the NBA Mood Mirror backend.

Usage:
    python -m backend.run snapshot          # build pre-game data/snapshot.json
    python -m backend.run live              # poll live during the game
    python -m backend.run live --once       # one live iteration
    python -m backend.run live --fixture data/fixture_pbp.json   # test live
    python -m backend.run auto              # snapshot, then live if game is on
"""

import argparse
import json
import sys

from . import config, live, pipeline
from .sources import espn


def _cmd_snapshot(_args):
    snap, path = pipeline.write_snapshot()
    pred = snap["prediction"]["ensemble"]
    print(f"Wrote {path}")
    print(f"  mode={snap['mode']}  articles={len(snap['press_review'])}  "
          f"social={len(snap['social'])}")
    print(f"  import_stats={snap['import_stats']}")
    print(f"  ensemble home={pred['home']} away={pred['away']} "
          f"confidence={snap['prediction']['confidence']}")
    print("  sources: " + ", ".join(
        f"{s['name']}={s['status']}" for s in snap["sources"]))
    return 0


def _cmd_live(args):
    if args.fixture:
        with open(args.fixture, encoding="utf-8") as f:
            fixture = json.load(f)
        snap, path = live.write_live(
            pbp_events=fixture.get("events", []),
            social_records=fixture.get("social", []),
            game=fixture.get("game"),
        )
        print(f"Wrote {path} (fixture)")
        print(f"  run={snap['live']['current_run']} "
              f"momentum={snap['live']['momentum']} "
              f"spike={snap['live']['sentiment_spike']}")
        print(f"  alerts={[a['text'] for a in snap['alerts']]}")
        return 0
    if args.once:
        snap, path = live.write_live()
        print(f"Wrote {path}  mode={snap['mode']}")
        return 0
    live.run_live_loop(max_iterations=args.max_iterations)
    return 0


def _cmd_evaluate(args):
    from . import backtest
    with open(args.results, encoding="utf-8") as f:
        results = json.load(f)
    metrics = backtest.evaluate(results)
    print("Calibration metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    return 0


def _cmd_auto(args):
    res = espn.fetch_game()
    game = res.meta.get("game") if res.meta else None
    state = game.get("state") if game else "pre"
    pipeline.write_snapshot()
    print(f"Snapshot written. ESPN game state = {state}")
    if state == "in":
        print("Game is live -> starting live loop.")
        live.run_live_loop(max_iterations=args.max_iterations)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="NBA Mood Mirror backend")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="build pre-game snapshot.json")

    p_live = sub.add_parser("live", help="live mode")
    p_live.add_argument("--once", action="store_true", help="single iteration")
    p_live.add_argument("--fixture", help="path to a synthetic PBP fixture")
    p_live.add_argument("--max-iterations", type=int, default=None,
                        dest="max_iterations")

    p_auto = sub.add_parser("auto", help="snapshot then live if game is on")
    p_auto.add_argument("--max-iterations", type=int, default=None,
                        dest="max_iterations")

    p_eval = sub.add_parser("evaluate", help="score predictions vs outcomes")
    p_eval.add_argument("--results", required=True,
                        help="JSON list of {prob_home, home_won}")

    args = parser.parse_args(argv)
    return {"snapshot": _cmd_snapshot, "live": _cmd_live, "auto": _cmd_auto,
            "evaluate": _cmd_evaluate}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
