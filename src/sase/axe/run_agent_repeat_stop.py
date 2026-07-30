"""Repeat-chain ``STOP`` detection for the agent runner.

``%repeat`` / ``%r`` fan-out is launch-time, not a runtime loop: all slots are
spawned up front and slots 2..N are parked behind an injected
``%wait:<predecessor>`` directive.  An agent stops the remaining slots by
writing the reserved ``STOP`` output variable (``sase var set STOP=1``) before
it completes.  When a downstream slot wakes, :func:`detect_repeat_stop` reads
its chain predecessor's output variables (the predecessor name arrives via
``SASE_REPEAT_PREV_NAME``).  If ``STOP`` is truthy the runner finalizes the
slot as a successful skipped repeat slot instead of running the prompt; because
the slot still reports ``outcome: "completed"``, the stop cascades down the
already-spawned chain through the generic ``%wait`` resolution.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sase.agent.repeat_launcher import REPEAT_PREV_NAME_ENV
from sase.core.output_variable_values import VarValue

# Reserved, case-sensitive output-variable name interpreted by repeat
# orchestration only.  ``sase var set`` itself stays generic.
STOP_OUTPUT_VARIABLE = "STOP"

# Conservative falsy set (case-insensitive) so a templated ``STOP=0`` /
# ``STOP=false`` is a safe no-op.  Any other value is truthy.
_FALSE_STOP_VALUES = frozenset({"", "0", "false", "no", "off"})


def _is_stop_value(value: VarValue) -> bool:
    """Return whether *value* counts as a truthy ``STOP`` signal."""
    if isinstance(value, str):
        return value.strip().lower() not in _FALSE_STOP_VALUES
    return bool(value)


@dataclass(frozen=True)
class RepeatStopDecision:
    """A resolved decision to stop the current repeat slot.

    ``producer_name`` is the chain predecessor that set ``STOP``;
    ``stop_value`` is the raw value to propagate into this slot's own output
    variables so the cascade continues.
    """

    producer_name: str
    stop_value: VarValue


def detect_repeat_stop() -> RepeatStopDecision | None:
    """Return a stop decision when this repeat slot's predecessor set ``STOP``.

    Returns ``None`` when the agent is not a repeat-chain member (no
    ``SASE_REPEAT_PREV_NAME``), when the predecessor cannot be resolved, or
    when the predecessor has no truthy ``STOP`` output variable.
    """
    prev_name = os.environ.get(REPEAT_PREV_NAME_ENV)
    if not prev_name:
        return None

    from sase.agent.output_variable_context import (
        read_waited_agent_output_variables,
    )

    variables = read_waited_agent_output_variables(prev_name)
    if not variables:
        return None

    stop_value = variables.get(STOP_OUTPUT_VARIABLE)
    if not _is_stop_value(stop_value):
        return None

    return RepeatStopDecision(producer_name=prev_name, stop_value=stop_value)


__all__ = [
    "STOP_OUTPUT_VARIABLE",
    "RepeatStopDecision",
    "detect_repeat_stop",
]
