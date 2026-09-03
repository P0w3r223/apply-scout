"""`python -m apply_scout.attack [--out PATH]` — run the grid, write the claim, print the machine.

No key, no network, no cassette: the attacker's server is a transport and the reader is a function.

Two outputs, because they have different lifetimes. `--out` gets the **approved claim** — what the
guards permitted, with the extractor divided out, which is the same on every machine and is the file
CI diffs. Standard output always gets the **environment section** as well: how much of the page each
extractor let through here, and the trafilatura and libxml2 that decided it. That half legitimately
differs between machines, so it is printed into the log rather than frozen into a file.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from apply_scout.attack import report, suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apply-scout attack", description=__doc__)
    parser.add_argument("--out", type=Path, help="Write the approved claim here instead of stdout.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as workspace:
        attempts = suite.run(Path(workspace))

    claim = report.markdown(attempts)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(claim, encoding="utf-8", newline="\n")
    else:
        print(claim)
    print(report.environment(attempts))

    # Non-zero when the harness did something the record does not predict, or when a payload landed
    # nowhere at all — a table of zeros produced by an extractor that dropped every attack reads
    # exactly like a table of zeros produced by working guards, and only this tells them apart.
    return 1 if report.surprises(attempts) or report.unlanded(attempts) else 0


if __name__ == "__main__":
    sys.exit(main())
