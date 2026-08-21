"""Central configuration: models, pricing, safety-budget defaults, paths.

No I/O and no secrets here — only constants. The API key is read from the
environment by the Anthropic SDK at call time (see llm.py), never stored here.

Two models are wired for the eval bake-off: a cheap one and a strong one, so the
harness can answer "when is the cheaper model enough?" (see the plan). Nothing in
the agent hardcodes a model — the choice flows in through `AgentConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# --- Paths -------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = PROJECT_ROOT / "eval"
RESULTS_DIR = EVAL_DIR / "results"  # trajectory JSONL + metric tables land here
# Recorded LLM / HTTP / GitHub responses. Unlike RESULTS_DIR these are *committed*:
# they are what lets the evaluation replay offline, in CI, with no API key.
CASSETTE_DIR = EVAL_DIR / "cassettes"

# --- Models ------------------------------------------------------------------
# Exact model IDs (no date suffixes). The cheap/strong split is the whole point of
# the cost analysis — do not collapse them to one model.
MODEL_CHEAP = "claude-haiku-4-5"  # $1.00 / $5.00 per 1M tokens (in / out)
MODEL_STRONG = "claude-opus-4-8"  # $5.00 / $25.00 per 1M tokens (in / out)
DEFAULT_MODEL = MODEL_STRONG

# Haiku 4.5 rejects adaptive thinking and the `effort` control with a 400; the Opus /
# Sonnet-5 tier accepts them. List the models that can't take them, so the agent loop
# (llm.py) omits those params per model instead of assuming every model supports them.
NO_ADAPTIVE_THINKING_MODELS: frozenset[str] = frozenset({MODEL_CHEAP})


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1,000,000 tokens. Base rates only — cache-read/write repricing is a
    later-milestone refinement once the harness measures real cache behaviour."""

    input_per_mtok: float
    output_per_mtok: float


# Source: Anthropic pricing at the time of writing. Kept next to the model IDs so a
# price change is a one-line edit, and the cost accounting has a single source.
PRICING: dict[str, ModelPrice] = {
    MODEL_CHEAP: ModelPrice(input_per_mtok=1.00, output_per_mtok=5.00),
    MODEL_STRONG: ModelPrice(input_per_mtok=5.00, output_per_mtok=25.00),
}

# --- Safety budget defaults --------------------------------------------------
# Hard ceilings for a single agent run. Exceeding any of them is NOT an error: the
# loop stops in a controlled way and returns whatever partial report it has. These
# are the defaults; a caller can tighten them per run (the eval harness deliberately
# starves the budget to prove graceful termination).
DEFAULT_MAX_STEPS = 12  # one step == one model call (plus the tools it triggers)
DEFAULT_MAX_TOKENS = 200_000  # cumulative input + output tokens across the run
DEFAULT_MAX_COST_USD = 0.50  # cumulative USD across the run

# --- Model request settings --------------------------------------------------
# Per-response output cap (an enforced ceiling the model is not aware of), distinct
# from the run-wide DEFAULT_MAX_TOKENS budget above.
MAX_OUTPUT_TOKENS = 4096
# Adaptive thinking + effort are the current controls (no budget_tokens on Opus 4.8
# / Haiku 4.5). "high" is a sensible default for multi-step tool reasoning.
DEFAULT_EFFORT = "high"

# --- HTTP / content extraction (fetch_job_posting) ---------------------------
# Honest, descriptive UA — we identify the agent rather than impersonate a browser.
HTTP_USER_AGENT = "apply-scout/0.1 (+https://github.com/P0w3r223/apply-scout)"
HTTP_TIMEOUT_S = 15.0
HTTP_MAX_HTML_CHARS = 2_000_000  # ignore absurdly large pages defensively

# --- Structuring (turning free text into a contract via an LLM) --------------
# Structuring is a simpler task than the agent's own reasoning, so it defaults to the
# cheap model — part of the "when is the cheaper model enough?" story.
STRUCTURE_MODEL = MODEL_CHEAP
STRUCTURE_MAX_CHARS = 20_000  # cap the text handed to the model, to bound token cost
STRUCTURE_MAX_ATTEMPTS = 3  # validate-and-retry attempts before giving up

# --- GitHub (github_evidence) ------------------------------------------------
GITHUB_API_BASE = "https://api.github.com"
GITHUB_PER_PAGE = 100
GITHUB_MAX_REPOS = 30  # cap README scans per lookup — rate-limit friendly
# On-disk cache for GitHub API responses (gitignored). Respects rate limits and makes
# repeated runs cheap. GITHUB_TOKEN (if set in the env) raises the rate limit.
CACHE_DIR = PROJECT_ROOT / ".cache"


def token_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    """USD cost of a call, from the per-model base rates above.

    Single source of truth for cost accounting (the budget tracker and the trajectory
    both use it). An unknown model costs 0.0 — reported by the harness, never guessed."""
    price = PRICING.get(model)
    if price is None:
        return 0.0
    return (
        input_tokens / 1_000_000 * price.input_per_mtok
        + output_tokens / 1_000_000 * price.output_per_mtok
    )
