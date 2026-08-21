"""Wire the real tools into a full end-to-end run.

`run_assessment` assembles the production pieces (Claude via `AnthropicLLM`, the three
real tools, a safety budget) and runs the agent on a single posting. Every dependency
is injectable, so a test drives the whole path with a scripted model and mock tools —
no network, no key.
"""

from __future__ import annotations

from collections.abc import Callable

from apply_scout import config
from apply_scout.agent import Agent, AgentConfig, AgentResult
from apply_scout.budget import Budget
from apply_scout.fetch import Extractor, Fetcher
from apply_scout.github import GitHubClient
from apply_scout.llm import AnthropicLLM, LLMClient
from apply_scout.structuring import Structurer
from apply_scout.tools.fetch_job_posting import FetchJobPosting
from apply_scout.tools.real import real_tools
from apply_scout.tools.registry import ToolRegistry
from apply_scout.tools.submit_report import SubmitReport
from apply_scout.trajectory import TrajectoryStep


def build_task(*, job_url: str, cv_path: str, github_user: str) -> str:
    """The instruction the agent works from — the concrete inputs it needs to call tools."""
    return (
        "Assess how well the candidate fits this job posting, using only verifiable evidence.\n"
        f"- Posting URL: {job_url}\n"
        f"- CV file path: {cv_path}\n"
        f"- GitHub username: {github_user}\n"
        "Fetch the posting, read the CV, gather GitHub evidence for each requirement, then "
        "produce a match report: rate every requirement strong / weak / none and cite the "
        "evidence (with its link) that justifies the rating."
    )


def run_assessment(
    *,
    job_url: str,
    cv_path: str,
    github_user: str,
    llm: LLMClient | None = None,
    tools: ToolRegistry | None = None,
    budget: Budget | None = None,
    model: str = config.DEFAULT_MODEL,
    on_step: Callable[[TrajectoryStep], None] | None = None,
    fetcher: Fetcher | None = None,
    structurer: Structurer | None = None,
    github: GitHubClient | None = None,
    extractor: Extractor | None = None,
    submit: SubmitReport | None = None,
    fetch: FetchJobPosting | None = None,
) -> AgentResult:
    """Run one fit assessment. Returns the result (including the trajectory to persist).

    `fetcher` / `structurer` / `github` / `extractor` are forwarded to the real toolset when
    no ready `tools` registry is given — that is how a cassette session substitutes its
    recording or replaying collaborators without the caller re-assembling the tools by hand.

    `submit` and `fetch` are the two tool instances a caller may want to keep: one holds the
    deliverable the run produced, the other the posting it was built from. Scoring one against
    the other is what `requirement_grounding` does."""
    llm = llm or AnthropicLLM()
    tools = tools or ToolRegistry(
        real_tools(
            fetcher=fetcher,
            structurer=structurer,
            github=github,
            extractor=extractor,
            submit=submit,
            fetch=fetch,
        )
    )
    agent = Agent(
        llm,
        tools,
        agent_config=AgentConfig(model=model, budget=budget or Budget()),
        on_step=on_step,
    )
    return agent.run(build_task(job_url=job_url, cv_path=cv_path, github_user=github_user))
