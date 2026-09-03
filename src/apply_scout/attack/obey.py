"""The reader that does whatever the posting tells it to.

This stands where the model stands, and it is the whole reason the number is reproducible. A real
model sometimes refuses, and whether it refuses on a given day is a property of the model, the
prompt and the recording — not of this project. Substituting a reader that *always* obeys removes
that variable and asks the only question the harness can answer for itself: **when the reader is
fully compromised, what does the architecture still permit?**

It obeys only what it was actually given. If a payload did not survive extraction into the text the
tool handed on, nothing here acts on it — an instruction the reader never saw cannot be followed,
and counting it as a defence would credit the guards with something extraction did by accident.
"""

from __future__ import annotations

from apply_scout.attack.payloads import Payload
from apply_scout.tools.registry import ToolRegistry


def obey(
    payload: Payload, registry: ToolRegistry, *, secret_path: str, reached: bool
) -> list[str]:
    """Carry out the payload's demand, and return what each tool answered.

    The contents are returned rather than inspected here: this module decides *what the reader
    does*, and `payloads.achieved` decides what counts as the attacker winning. Keeping the two
    apart is what stops the suite grading its own homework."""
    if payload.demand is None or not reached:
        return []
    arguments = {
        key: value.replace("{secret}", secret_path)
        for key, value in payload.demand.arguments.items()
    }
    result = registry.dispatch(payload.demand.tool, arguments)
    return [result.content]
