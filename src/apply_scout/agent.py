"""The agent loop — written from scratch, on purpose (see docs/decisions/0001).

The whole loop is here and it is small: call the model, run whatever tools it asks
for, feed the results back, repeat, until the model stops asking for tools or a safety
budget is reached. Owning this loop is what makes budgets, the trajectory log, and the
eval harness possible — there is no framework hiding the control flow.

The loop depends only on the `LLMClient` protocol and a `ToolRegistry`, so it runs
under a scripted fake model with no network and no API key (that is how it is tested).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from apply_scout import config
from apply_scout.budget import Budget, BudgetBreach, BudgetTracker
from apply_scout.llm import LLMClient
from apply_scout.prompts import DEFAULT_SYSTEM_PROMPT
from apply_scout.tools.registry import ToolRegistry
from apply_scout.trajectory import StepKind, TrajectoryLogger, TrajectoryStep


class RunStatus(StrEnum):
    COMPLETED = "completed"  # the model finished on its own
    BUDGET_STOPPED = "budget_stopped"  # a safety ceiling ended the run early


@dataclass(frozen=True)
class AgentConfig:
    model: str = config.DEFAULT_MODEL
    budget: Budget = field(default_factory=Budget)


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
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.cfg = agent_config or AgentConfig()
        self.system_prompt = system_prompt

    def run(self, task: str) -> AgentResult:
        traj = TrajectoryLogger()
        tracker = BudgetTracker(self.cfg.budget)
        messages: list[dict] = [{"role": "user", "content": task}]
        step_index = 0
        last_text = ""

        while True:
            # Budget is checked *before* each model call, so the run makes at most
            # `max_steps` calls and then stops with whatever report it has so far.
            breach = tracker.breach()
            if breach is not None:
                traj.record(
                    TrajectoryStep(
                        index=step_index,
                        kind=StepKind.BUDGET_STOP,
                        note=f"stopped: {breach.value}",
                    )
                )
                return self._result(RunStatus.BUDGET_STOPPED, last_text, traj, tracker, breach)

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
            last_text = response.text
            traj.record(
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
                )
            )
            step_index += 1
            messages.append({"role": "assistant", "content": response.raw_content})

            # No tool calls -> the model is done; that is the normal exit.
            if response.stop_reason != "tool_use" or not response.tool_calls:
                traj.record(
                    TrajectoryStep(index=step_index, kind=StepKind.FINAL, note=response.stop_reason)
                )
                return self._result(RunStatus.COMPLETED, last_text, traj, tracker, None)

            # Run every requested tool and return all results in one user turn (splitting
            # them would quietly train the model to stop calling tools in parallel).
            tool_result_blocks: list[dict] = []
            for call in response.tool_calls:
                result = self.tools.dispatch(call.name, call.input)
                traj.record(
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
