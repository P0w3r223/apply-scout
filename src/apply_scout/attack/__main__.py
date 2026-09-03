"""`python -m apply_scout.attack [--out PATH]` — run the grid and write the table.

No key, no network, no cassette: the attacker's server is a transport and the reader is a
function, so the same grid produces the same table on any machine."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from apply_scout.attack import report, suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apply-scout attack", description=__doc__)
    parser.add_argument("--out", type=Path, help="Write the table here instead of stdout.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as workspace:
        attempts = suite.run(Path(workspace))

    table = report.markdown(attempts)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(table, encoding="utf-8", newline="\n")
    else:
        print(table)
    # Non-zero when the harness did something the record does not predict — that is the run's
    # point, and a CI job that only diffed the file would report it as a formatting change.
    return 1 if report.surprises(attempts) else 0


if __name__ == "__main__":
    sys.exit(main())
