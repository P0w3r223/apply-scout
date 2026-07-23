"""The budget tracker: accounting is right, and each ceiling trips when it should."""

from __future__ import annotations

from apply_scout import config
from apply_scout.budget import Budget, BudgetBreach, BudgetTracker


def test_no_breach_when_under_all_ceilings():
    tracker = BudgetTracker(Budget(max_steps=3, max_tokens=1_000, max_cost_usd=1.0))
    tracker.record_step()
    tracker.record_usage(100, 50, config.MODEL_STRONG)
    assert tracker.breach() is None


def test_step_ceiling_trips():
    tracker = BudgetTracker(Budget(max_steps=2, max_tokens=10**9, max_cost_usd=10**9))
    tracker.record_step()
    tracker.record_step()
    assert tracker.breach() is BudgetBreach.STEPS


def test_token_ceiling_trips():
    tracker = BudgetTracker(Budget(max_steps=10**9, max_tokens=120, max_cost_usd=10**9))
    tracker.record_usage(100, 50, config.MODEL_STRONG)  # 150 > 120
    assert tracker.breach() is BudgetBreach.TOKENS


def test_cost_matches_pricing():
    tracker = BudgetTracker(Budget())
    # 1,000,000 input + 1,000,000 output on the strong model = 5.00 + 25.00 USD.
    tracker.record_usage(1_000_000, 1_000_000, config.MODEL_STRONG)
    assert tracker.cost_usd == 30.0


def test_unknown_model_costs_zero_but_counts_tokens():
    tracker = BudgetTracker(Budget())
    tracker.record_usage(1_000_000, 1_000_000, "some-unlisted-model")
    assert tracker.cost_usd == 0.0
    assert tracker.total_tokens == 2_000_000
