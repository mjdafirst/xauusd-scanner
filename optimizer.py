"""Bounded optimizer entry point.

Run manually or from a protected workflow. It produces a challenger report;
AUTO_PROMOTE must be explicitly enabled before replacing the champion. This
module never changes execution, position size, stop enforcement, or OANDA mode.
"""
import argparse, json, itertools
from pathlib import Path
import config

PARAM_GRID = {
    "MIN_RISK_REWARD": [1.3, 1.5, 1.7, 2.0],
    "MAX_SWEEP_AGE_BARS": [10, 20, 30],
    "SWEEP_LOOKBACK_BARS": [20, 40, 60],
    "FVG_SEARCH_BARS": [15, 25, 35],
}


def candidates():
    names = list(PARAM_GRID)
    for values in itertools.product(*(PARAM_GRID[n] for n in names)):
        yield dict(zip(names, values))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="challenger_report.json")
    args = parser.parse_args()
    current = json.loads(Path(config.STRATEGY_CONFIG_FILE).read_text())
    report = {"current": current, "candidates": list(candidates()),
              "message": "Run each candidate through walk-forward backtesting before promotion.",
              "auto_promote": False}
    Path(args.report).write_text(json.dumps(report, indent=2))
    print(f"Wrote {len(report['candidates'])} bounded candidates to {args.report}.")
    print("No candidate was promoted: validation and promotion are intentionally separate.")

if __name__ == "__main__":
    main()
