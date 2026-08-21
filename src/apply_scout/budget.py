"""Safety budgets: the hard ceilings that keep an agent run bounded.

The rule (see CLAUDE.md): exceeding a budget is a *controlled stop with a partial
report*, never an exception. The agent checks the tracker before each model call and
bows out gracefully when a ceiling is reached. That behaviour is directly tested by
the harness, which deliberately starves the budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from apply_scout import config


class BudgetBreach(StrEnum):
    """Which ceiling was hit. Recorded in the trajectory and returned to the caller."""

    STEPS = "max_steps"
    TOKENS = "max_tokens"
    COST = "max_cost"


@dataclass(frozen=True)
class Budget:
    """Immutable per-run ceilings. Defaults come from config; a caller may tighten them."""

    max_steps: int = config.DEFAULT_MAX_STEPS
    max_tokens: int = config.DEFAULT_MAX_TOKENS
    max_cost_usd: float = config.DEFAULT_MAX_COST_USD


class BudgetTracker:
    """Mutable accumulator for one run: steps taken, tokens spent, USD spent.

    Token cost is derived from the per-model pricing in config, so the cost ceiling
    is meaningful across a mixed-model run. An unknown model contributes tokens but
    zero cost (and is surfaced by the harness rather than silently trusted)."""

    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        self.steps = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def record_step(self) -> None:
        self.steps += 1

    def record_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
        *,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        """Account for one model call. Cached tokens are counted and priced too — they are
        cheaper, not free, and a ceiling that ignored them would stop bounding the spend it
        exists to bound."""
        self.input_tokens += input_tokens + cache_read_tokens + cache_write_tokens
        self.output_tokens += output_tokens
        self.cost_usd += config.token_cost(
            input_tokens,
            output_tokens,
            model,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

    def breach(self) -> BudgetBreach | None:
        """Return the first ceiling that is met or exceeded, else None.

        Checked at the *start* of each loop iteration, before a new model call, so the
        run performs exactly `max_steps` calls and then stops with what it has."""
        if self.steps >= self.budget.max_steps:
            return BudgetBreach.STEPS
        if self.total_tokens >= self.budget.max_tokens:
            return BudgetBreach.TOKENS
        if self.cost_usd >= self.budget.max_cost_usd:
            return BudgetBreach.COST
        return None
