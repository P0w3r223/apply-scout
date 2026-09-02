"""Record the README demo, and render it.

Two steps, deliberately separate:

    python scripts/demo.py capture --url ... --cv ... --github-user ... --cassette-mode record
    python scripts/demo.py render

`capture` runs a real assessment and writes a *cast* (docs/demo-cast.json): every printed
step with the wall-clock second it appeared. `render` turns a cast into docs/demo.svg and
touches nothing else — so the picture can be regenerated, restyled, or re-trimmed without
spending a cent.

Because the run goes through the same cassette seams as everything else, capturing with
`--cassette-mode record` leaves a `run.jsonl` behind, and the identical command with
`--cassette-mode replay` reproduces the demo offline, with no API key. That is the point:
the demo is an artifact of the recorded run, not a screenshot somebody has to trust.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from demo_svg import Cast, Frame, render_svg

from apply_scout import config
from apply_scout.budget import Budget
from apply_scout.cassette import CassetteMode, CassetteSession, default_cassette_path
from apply_scout.env import load_dotenv
from apply_scout.formatting import format_step, format_summary, step_style
from apply_scout.github import GitHubClient
from apply_scout.runner import run_assessment
from apply_scout.trajectory import StepKind, TrajectoryStep

DOCS_DIR = config.PROJECT_ROOT / "docs"
CAST_PATH = DOCS_DIR / "demo-cast.json"
SVG_PATH = DOCS_DIR / "demo.svg"
GIF_PATH = DOCS_DIR / "demo.gif"
# The final report is pages long; the demo shows its opening and says so.
REPORT_PREVIEW_LINES = 14


def _command_line(args: argparse.Namespace) -> str:
    return (
        f"apply-scout run --url {args.url} --cv {args.cv} "
        f"--github-user {args.github_user} --verbose"
    )


def _summary_frames(summary: str, at: float) -> list[Frame]:
    """The end-of-run block, with the report body trimmed to a preview."""
    head, _, report = summary.partition("--- report ---\n")
    frames = [Frame(t=at, text="\n" + head.rstrip(), style="bold green")]
    body = report.rstrip().split("\n")
    shown = body[:REPORT_PREVIEW_LINES]
    if len(body) > REPORT_PREVIEW_LINES:
        shown.append(f"... {len(body) - REPORT_PREVIEW_LINES} more line(s) — full report above")
    frames.append(Frame(t=at, text="--- report ---\n" + "\n".join(shown), style=""))
    return frames


def capture(args: argparse.Namespace) -> int:
    load_dotenv()
    started = time.monotonic()
    frames: list[Frame] = []

    def on_step(step: TrajectoryStep) -> None:
        text = format_step(step)
        print(text, flush=True)
        frames.append(
            Frame(
                t=time.monotonic() - started,
                text=text,
                style=step_style(step),
                group=step.tool_name if step.kind is StepKind.TOOL_RESULT else None,
            )
        )

    session = (
        None
        if args.cassette_mode == "off"
        else CassetteSession.open(
            Path(args.cassette) if args.cassette else default_cassette_path("run"),
            CassetteMode(args.cassette_mode),
        )
    )
    wiring = (
        {}
        if session is None
        else {
            "llm": session.llm(),
            "fetcher": session.fetcher(),
            "structurer": session.structurer(),
            "extractor": session.extractor(),
            "github": GitHubClient(cache=session.github_cache()),
        }
    )

    result = run_assessment(
        job_url=args.url,
        cv_path=args.cv,
        github_user=args.github_user,
        model=args.model,
        budget=Budget(max_steps=args.max_steps, max_cost_usd=args.max_cost),
        on_step=on_step,
        **wiring,
    )
    frames.extend(_summary_frames(format_summary(result), time.monotonic() - started))

    if session is not None:
        print(session.summary())
        saved = session.save()
        if saved is not None:
            print(f"cassette written: {saved}")

    trajectory_path = config.RESULTS_DIR / "demo-trajectory.jsonl"
    result.trajectory.write(trajectory_path)

    cast = {
        "command": _command_line(args),
        "title": f"apply-scout run — {args.model}",
        "frames": [
            {"t": round(f.t, 3), "text": f.text, "style": f.style, "group": f.group}
            for f in frames
        ],
    }
    cast_path = Path(args.cast)
    cast_path.parent.mkdir(parents=True, exist_ok=True)
    cast_path.write_text(json.dumps(cast, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"cast written: {cast_path}\ntrajectory: {trajectory_path}")
    return 0 if args.expect is None else _compare(cast, Path(args.expect))


def _compare(cast: dict, expected_path: Path) -> int:
    """Fail loudly when a replay stops reproducing the recording it claims to reproduce.

    Only the printed text is compared: wall-clock timings are a property of the machine,
    not of the run, and a replay is three hundred times faster by design.
    """
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    actual_text = [frame["text"] for frame in cast["frames"]]
    expected_text = [frame["text"] for frame in expected["frames"]]
    if actual_text == expected_text:
        print(f"reproduced {expected_path} exactly ({len(actual_text)} frames)")
        return 0
    print(
        f"REPLAY DRIFT vs {expected_path}: {len(actual_text)} frames now, "
        f"{len(expected_text)} recorded — the cassette or the run has moved on.",
        file=sys.stderr,
    )
    return 1


def render(args: argparse.Namespace) -> int:
    cast = Cast.load(Path(args.cast))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_svg(cast) + "\n", encoding="utf-8")
    print(f"svg written: {out} ({len(cast.frames)} frames)")
    return 0


def gif(args: argparse.Namespace) -> int:
    """The same cast as a GIF, for the places an SVG is shown but never animated.

    Pillow is a dev dependency rather than a runtime one: this renders the picture, it is
    not part of the agent. Imported here so `capture` and `render` still work without it.
    """
    from demo_gif import render_gif  # noqa: PLC0415 — optional, dev-only dependency

    cast = Cast.load(Path(args.cast))
    out = Path(args.out)
    frames = render_gif(cast, out)
    print(f"gif written: {out} ({frames} frames, {out.stat().st_size / 1024:.0f} KB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demo", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="Run an assessment and write the cast.")
    cap.add_argument("--url", required=True)
    cap.add_argument("--cv", required=True)
    cap.add_argument("--github-user", required=True)
    cap.add_argument("--model", default=config.DEFAULT_MODEL)
    cap.add_argument("--max-steps", type=int, default=config.DEFAULT_MAX_STEPS)
    cap.add_argument("--max-cost", type=float, default=config.DEFAULT_MAX_COST_USD)
    cap.add_argument("--cassette-mode", choices=("off", "record", "replay", "auto"), default="off")
    cap.add_argument("--cassette", default=None)
    # Redirectable so a replay can be diffed against the recording without overwriting it.
    cap.add_argument("--cast", default=str(CAST_PATH))
    cap.add_argument(
        "--expect",
        default=None,
        help="Compare the printed stream against this cast and exit non-zero on drift.",
    )
    cap.set_defaults(func=capture)

    ren = sub.add_parser("render", help="Turn a cast into an animated SVG.")
    ren.add_argument("--cast", default=str(CAST_PATH))
    ren.add_argument("--out", default=str(SVG_PATH))
    ren.set_defaults(func=render)

    gif_cmd = sub.add_parser("render-gif", help="Turn a cast into an animated GIF.")
    gif_cmd.add_argument("--cast", default=str(CAST_PATH))
    gif_cmd.add_argument("--out", default=str(GIF_PATH))
    gif_cmd.set_defaults(func=gif)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
