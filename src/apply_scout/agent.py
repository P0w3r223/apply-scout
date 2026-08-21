"""The agent loop — written from scratch, on purpose (see docs/decisions/0001).

The whole loop is here and it is small: call the model, run whatever tools it asks
for, feed the results back, repeat, until the model stops asking for tools or a safety
budget is reached. Owning this loop is what makes budgets, the trajectory log, and the
eval harness possible — there is no framework hiding the control flow.

The loop depends only on the `LLMClient` protocol and a `ToolRegistry`, so it runs
under a scripted fake model with no network and no API key (that is how it is tested).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from apply_scout import config
from apply_scout.budget import Budget, BudgetBreach, BudgetTracker
from apply_scout.llm import LLMClient
from apply_scout.prompts import CONTINUE_INSTRUCTION, DEFAULT_SYSTEM_PROMPT
from apply_scout.tools.registry import ToolRegistry
from apply_scout.trajectory import StepKind, TrajectoryLogger, TrajectoryStep


class RunStatus(StrEnum):
    COMPLETED = "completed"  # the model finished on its own
    BUDGET_STOPPED = "budget_stopped"  # a safety ceiling ended the run early
    TRUNCATED = "truncated"  # the answer still hit the output cap after every continuation


@dataclass(frozen=True)
class AgentConfig:
    model: str = config.DEFAULT_MODEL
    budget: Budget = field(default_factory=Budget)
    max_continuations: int = config.MAX_CONTINUATIONS


@dataclass(frozen=True)
class AgentResult:
    """The outcome of a run: the final text, the trajectory, and what it cost.

    On a budget stop this still carries whatever the last model turn produced — a
    partial report, not nothing."""

    status: RunStatus
    final_text: str
    trajectory: TrajectoryLogger
    steps: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    breach: BudgetBreach | None = None


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        *,
        agent_config: AgentConfig | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        on_step: Callable[[TrajectoryStep], None] | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.cfg = agent_config or AgentConfig()
        self.system_prompt = system_prompt
        self._on_step = on_step  # called after each recorded step (e.g. --verbose printing)

    def run(self, task: str) -> AgentResult:
        traj = TrajectoryLogger()

        def record(step: TrajectoryStep) -> None:
            traj.record(step)
            if self._on_step is not None:
                self._on_step(step)

        tracker = BudgetTracker(self.cfg.budget)
        messages: list[dict] = [{"role": "user", "content": task}]
        step_index = 0
        # An answer cut off by the output cap arrives in pieces; `answer` collects them so
        # the caller sees one report rather than the last fragment of it.
        answer: list[str] = []
        continuing = False
        continuations = 0

        while True:
            # Budget is checked *before* each model call, so the run makes at most
            # `max_steps` calls and then stops with whatever report it has so far.
            breach = tracker.breach()
            if breach is not None:
                record(
                    TrajectoryStep(
                        index=step_index,
                        kind=StepKind.BUDGET_STOP,
                        note=f"stopped: {breach.value}",
                    )
                )
                return self._result(
                    RunStatus.BUDGET_STOPPED, "".join(answer), traj, tracker, breach
                )

            tracker.record_step()
            response = self.llm.complete(
                system=self.system_prompt,
                messages=messages,
                tools=self.tools.specs(),
                model=self.cfg.model,
            )
            tracker.record_usage(
                response.usage.input_tokens, response.usage.output_tokens, response.model
            )
            # A continuation extends the answer in progress; anything else starts a new one.
            answer = [*answer, response.text] if continuing else [response.text]
            record(
                TrajectoryStep(
                    index=step_index,
                    kind=StepKind.MODEL_CALL,
                    model=response.model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cost_usd=config.token_cost(
                        response.usage.input_tokens, response.usage.output_tokens, response.model
                    ),
                    tool_calls_requested=len(response.tool_calls),
                    text=response.text or None,
                )
            )
            step_index += 1
            messages.append({"role": "assistant", "content": response.raw_content})

            # No tool calls -> the model is done; that is the normal exit.
            if response.stop_reason != "tool_use" or not response.tool_calls:
                truncated = response.stop_reason == "max_tokens"
                if truncated and response.tool_calls:
                    # The cap landed inside a tool_use block. Asking for a continuation here
                    # would append a user turn after an unanswered tool_use — a request the
                    # API rejects outright, losing the trajectory and the money already spent.
                    # Partial JSON has nothing to continue, so stop and say so.
                    record(
                        TrajectoryStep(
                            index=step_index,
                            kind=StepKind.FINAL,
                            note="max_tokens inside a tool call — nothing to continue",
                        )
                    )
                    return self._result(RunStatus.TRUNCATED, "".join(answer), traj, tracker, None)
                if truncated and continuations < self.cfg.max_continuations:
                    # The answer is unfinished, not the run. Ask for the rest in a *user*
                    # turn — prefilling the assistant's own turn is rejected by this model
                    # family — and let the budget check at the top of the loop bound it.
                    continuations += 1
                    continuing = True
                    messages.append({"role": "user", "content": CONTINUE_INSTRUCTION})
                    record(
                        TrajectoryStep(
                            index=step_index,
                            kind=StepKind.CONTINUATION,
                            note=f"output cap reached; continuing ({continuations}"
                            f"/{self.cfg.max_continuations})",
                        )
                    )
                    step_index += 1
                    continue
                # Out of continuations while still truncated: say so. Reporting a partial
                # report as `completed` is exactly the failure this status exists to prevent.
                status = RunStatus.TRUNCATED if truncated else RunStatus.COMPLETED
                record(
                    TrajectoryStep(index=step_index, kind=StepKind.FINAL, note=response.stop_reason)
                )
                return self._result(status, "".join(answer), traj, tracker, None)
            continuing = False

            # Run every requested tool and return all results in one user turn (splitting
            # them would quietly train the model to stop calling tools in parallel).
            tool_result_blocks: list[dict] = []
            for call in response.tool_calls:
                result = self.tools.dispatch(call.name, call.input)
                record(
                    TrajectoryStep(
                        index=step_index,
                        kind=StepKind.TOOL_RESULT,
                        tool_name=call.name,
                        tool_input=call.input,
                        tool_ok=result.ok,
                        tool_summary=result.summary,
                    )
                )
                step_index += 1
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": result.content,
                        "is_error": not result.ok,
                    }
                )
            messages.append({"role": "user", "content": tool_result_blocks})

    @staticmethod
    def _result(
        status: RunStatus,
        final_text: str,
        traj: TrajectoryLogger,
        tracker: BudgetTracker,
        breach: BudgetBreach | None,
    ) -> AgentResult:
        return AgentResult(
            status=status,
            final_text=final_text,
            trajectory=traj,
            steps=tracker.steps,
            input_tokens=tracker.input_tokens,
            output_tokens=tracker.output_tokens,
            cost_usd=tracker.cost_usd,
            breach=breach,
        )
