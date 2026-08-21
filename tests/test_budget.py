"""The budget tracker: accounting is right, and each ceiling trips when it should."""

from __future__ import annotations

import pytest

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


def test_a_dated_snapshot_id_is_priced_like_its_alias():
    """The API echoes back `claude-haiku-4-5-20251001` for a request that named
    `claude-haiku-4-5`. Callers price the response, so an id that misses the rate card
    reads as $0.00 — which also disables the cost ceiling, since a run that never spends
    anything can never breach it."""
    dated = f"{config.MODEL_CHEAP}-20251001"
    assert config.token_cost(1_000_000, 0, dated) == config.token_cost(
        1_000_000, 0, config.MODEL_CHEAP
    )
    assert config.token_cost(10_000, 5_000, dated) > 0.0

    tracker = BudgetTracker(Budget(max_steps=99, max_tokens=10**9, max_cost_usd=0.01))
    tracker.record_usage(1_000_000, 0, dated)  # $1.00 of input on the cheap model
    assert tracker.breach() is BudgetBreach.COST


def test_an_unpriced_model_costs_zero_rather_than_a_guess():
    assert config.token_cost(1_000, 1_000, "some-other-vendor-model") == 0.0


def test_only_a_dated_suffix_is_treated_as_the_same_model():
    """A bare prefix match would price a future `...-turbo` at today's rates — a silent
    wrong number, which is the class of bug price_for exists to remove."""
    strong = config.PRICING[config.MODEL_STRONG]
    assert config.price_for(f"{config.MODEL_STRONG}-20260101") is strong
    assert config.price_for(f"{config.MODEL_STRONG}-turbo") is None
    assert config.price_for(f"{config.MODEL_STRONG}x") is None


def test_cached_tokens_are_cheaper_but_not_free():
    """A cache read bills at a tenth of the input rate and a write at 1.25x. Treating
    either as free would make a run look cheaper than the invoice."""
    plain = config.token_cost(1_000_000, 0, config.MODEL_STRONG)
    read = config.token_cost(0, 0, config.MODEL_STRONG, cache_read_tokens=1_000_000)
    write = config.token_cost(0, 0, config.MODEL_STRONG, cache_write_tokens=1_000_000)

    assert read == pytest.approx(plain * 0.10)
    assert write == pytest.approx(plain * 1.25)
    assert read > 0  # cheaper, never free


def test_a_budget_counts_cached_tokens_too():
    """With caching on, the API reports `input_tokens` as the *uncached remainder*. A
    tracker that ignored the rest would stop bounding the spend it exists to bound."""
    tracker = BudgetTracker(Budget(max_steps=99, max_tokens=10**9, max_cost_usd=10**9))
    tracker.record_usage(100, 50, config.MODEL_STRONG, cache_read_tokens=20_000)

    assert tracker.input_tokens == 20_100  # the whole prompt, not just what was billed full
    assert tracker.cost_usd == pytest.approx(
        config.token_cost(100, 50, config.MODEL_STRONG, cache_read_tokens=20_000)
    )
    assert tracker.cost_usd > config.token_cost(100, 50, config.MODEL_STRONG)
