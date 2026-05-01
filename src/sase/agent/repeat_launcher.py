"""Fan out a ``%r:N``-decorated prompt into N independent agents.

This module is the shared entry point for both the TUI launch path
(``sase ace``) and the CLI ``sase run`` daemon path.  Given a prompt
containing a ``%repeat:N`` (or ``%r:N``) directive, :func:`spawn_repeat_batch`
resolves a unique name base, constructs one :class:`RepeatAgentSpec` per
iteration, and invokes a caller-supplied ``base_spawn_fn`` to spawn each
agent independently.  The ``%r`` and ``%n`` tokens are stripped from each
per-agent prompt — callers are expected to re-emit the per-slot name via
env vars and/or an injected ``%n:<base>.<k>`` line.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sase.agent.names import NameCollisionError, reserve_repeat_name_base
from sase.agent.names import (
    agent_name_allocation_lock,
    allocate_resume_names,
    first_resume_agent_name,
)

__all__ = [
    "NameCollisionError",
    "REPEAT_ITERATION_ENV",
    "REPEAT_NAME_ENV",
    "REPEAT_TOTAL_ENV",
    "RepeatAgentSpec",
    "extract_repeat_and_name",
    "spawn_repeat_batch",
]

log = logging.getLogger(__name__)

REPEAT_NAME_ENV = "SASE_REPEAT_NAME"
REPEAT_ITERATION_ENV = "SASE_REPEAT_ITERATION"
REPEAT_TOTAL_ENV = "SASE_REPEAT_TOTAL"


@dataclass
class RepeatAgentSpec:
    """One repeat agent's per-slot parameters."""

    name: str
    iteration: int
    total: int
    prompt: str
    timestamp: str | None = None


def extract_repeat_and_name(
    prompt: str,
) -> tuple[int | None, str | None, str]:
    """Return ``(repeat_count, explicit_base_name, prompt_without_r_or_n)``.

    Parses and strips ``%r``/``%repeat`` and ``%n``/``%name`` directives
    from *prompt* (in either canonical or short-alias form) while leaving
    every other directive intact.  Fenced code blocks and disabled regions
    are preserved.

    Returns ``(None, None, prompt)`` when the prompt carries no repeat
    directive or when the parsed count is ``<= 1`` — both are "no fan-out
    needed", and the original prompt is returned unchanged so callers can
    dispatch it through the single-agent path.
    """
    from sase.core.agent_launch_facade import plan_agent_launch_fanout

    plan = plan_agent_launch_fanout(prompt, launch_kind="repeat")
    if not plan.slots:
        return None, None, prompt
    return len(plan.slots), plan.slots[0].repeat_name, plan.slots[0].prompt


def spawn_repeat_batch(
    prompt: str,
    *,
    base_spawn_fn: Callable[[RepeatAgentSpec], None],
    sleep_between: float = 1.0,
    timestamps: list[str] | None = None,
) -> list[RepeatAgentSpec]:
    """Resolve names + call *base_spawn_fn* once per repeat slot.

    *base_spawn_fn* receives a :class:`RepeatAgentSpec` and is responsible
    for every launch-site concern (workspace claim, timestamp, env-var
    injection).  Returns the specs actually spawned, or an empty list when
    *prompt* has no ``%r:N`` directive (or ``N <= 1``).

    Iterations 2..N have a ``%wait:<prev_name>`` directive prepended to
    their prompt so each agent blocks until its predecessor completes —
    turning the fan-out into a sequential chain coordinated at the agent
    level, not in the launcher.

    Raises :class:`NameCollisionError` if an explicit base name collides
    with a currently-active agent.
    """
    count, explicit_base, prompt_stripped = extract_repeat_and_name(prompt)
    if count is None:
        return []
    if timestamps is not None and len(timestamps) != count:
        raise ValueError(
            f"repeat timestamp batch has {len(timestamps)} timestamps for {count} slots"
        )

    resume_target = (
        None if explicit_base is not None else first_resume_agent_name(prompt_stripped)
    )
    if resume_target is not None:
        with agent_name_allocation_lock():
            names = allocate_resume_names(resume_target, count)
    else:
        base = reserve_repeat_name_base(explicit_base, count)
        names = [f"{base}.{k}" for k in range(1, count + 1)]

    specs = [
        RepeatAgentSpec(
            name=names[k - 1],
            iteration=k,
            total=count,
            prompt=(
                f"%n:{names[k - 1]}\n{prompt_stripped}"
                if k == 1
                else f"%n:{names[k - 1]}\n%wait:{names[k - 2]}\n{prompt_stripped}"
            ),
            timestamp=None if timestamps is None else timestamps[k - 1],
        )
        for k in range(1, count + 1)
    ]

    from sase.agent.launch_timing import LaunchTimingRecorder

    timer = LaunchTimingRecorder(
        "agent_launch_repeat_batch",
        {"slot_count": len(specs), "sleep_between": sleep_between},
    )
    for i, spec in enumerate(specs):
        if i > 0 and sleep_between > 0:
            with timer.stage("fanout_sleep_skipped", seconds=0.0, slot_index=i):
                pass
        with timer.stage("slot_spawn", slot_index=i):
            base_spawn_fn(spec)

    timer.finish(outcome="ok")
    return specs
