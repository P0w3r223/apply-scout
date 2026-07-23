"""apply-scout: an LLM agent that matches a job posting against a candidate's CV
and GitHub evidence, with a from-scratch tool loop, safety budgets, and a
trajectory-evaluation harness.

Portfolio project P3 (the flagship). The public surface is intentionally small in
this first milestone: the data contracts, the safety budget, the trajectory log,
and the agent loop that ties tools together. Real tools and the evaluation harness
arrive in later milestones.
"""

from __future__ import annotations

__version__ = "0.1.0"
