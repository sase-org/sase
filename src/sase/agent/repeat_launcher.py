"""Fan out a ``%r:N``-decorated prompt into N independent agents.

This module is the shared entry point for both the TUI launch path
(``sase ace``) and the CLI ``sase run`` path. Given a prompt
containing a ``%repeat:N`` (or ``%r:N``) directive, :func:`spawn_repeat_batch`
resolves a unique name base, constructs one :class:`RepeatAgentSpec` per
iteration, and invokes a caller-supplied ``base_spawn_fn`` to spawn each
agent independently.  The ``%r`` and ``%i`` tokens are stripped from each
per-agent prompt — callers are expected to re-emit the per-slot name via
env vars and/or an injected ``%i:<base>.<k>`` line.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sase.agent.names import (
    NameCollisionError,
    is_agent_name_template,
    reserve_repeat_name_base,
)
from sase.agent.names import (
    agent_name_allocation_lock,
    allocate_resume_names,
    allocate_wait_names,
    single_wait_agent_name,
    sole_resume_agent_name,
)
from sase.core.agent_tribe import parse_tribe_reference
from sase.xprompt._exceptions import DirectiveError

__all__ = [
    "NameCollisionError",
    "REPEAT_ITERATION_ENV",
    "REPEAT_NAME_ENV",
    "REPEAT_PREV_NAME_ENV",
    "REPEAT_TOTAL_ENV",
    "RepeatAgentSpec",
    "extract_repeat_and_name",
    "spawn_repeat_batch",
]

log = logging.getLogger(__name__)

REPEAT_NAME_ENV = "SASE_REPEAT_NAME"
REPEAT_ITERATION_ENV = "SASE_REPEAT_ITERATION"
REPEAT_TOTAL_ENV = "SASE_REPEAT_TOTAL"
REPEAT_PREV_NAME_ENV = "SASE_REPEAT_PREV_NAME"


@dataclass
class RepeatAgentSpec:
    """One repeat agent's per-slot parameters.

    ``prev_name`` is the resolved name of this slot's chain predecessor
    (the agent it ``%wait``s on), or ``None`` for the first slot.  It is the
    already-allocated name, not ``<base>.<k-1>`` string surgery, so it stays
    correct for resume- and wait-derived names such as ``foo.f1`` or
    ``foo.w2``.  Launch surfaces forward it as ``SASE_REPEAT_PREV_NAME`` so a
    woken slot can detect a predecessor's ``STOP`` output variable.
    """

    name: str
    iteration: int
    total: int
    prompt: str
    timestamp: str | None = None
    prev_name: str | None = None


def extract_repeat_and_name(
    prompt: str,
) -> tuple[int | None, str | None, str]:
    """Return ``(repeat_count, explicit_base_name, prompt_without_r_or_i)``.

    Parses and strips ``%r``/``%repeat`` and ``%i``/``%id`` directives
    from *prompt* (in either canonical or short-alias form) while leaving
    every other directive intact.  Fenced code blocks and disabled regions
    are preserved.

    Returns ``(None, None, prompt)`` when the prompt carries no repeat
    directive or when the parsed count is ``<= 1`` — both are "no fan-out
    needed", and the original prompt is returned unchanged so callers can
    dispatch it through the single-agent path.
    """
    count, explicit_name, _bead_id, stripped = _extract_repeat_identity(prompt)
    if count is None:
        return None, None, prompt
    return count, explicit_name, stripped


def _extract_repeat_identity(
    prompt: str,
) -> tuple[int | None, str | None, str | None, str]:
    """Return repeat count, name, bead association, and stripped prompt."""
    from sase.core.agent_launch_facade import plan_agent_launch_fanout

    _validate_repeat_prompt_directives(prompt)
    plan = plan_agent_launch_fanout(prompt, launch_kind="repeat")
    if not plan.slots:
        return None, None, None, prompt
    first = plan.slots[0]
    return len(plan.slots), first.repeat_name, first.bead_id, first.prompt


def _validate_repeat_prompt_directives(prompt: str) -> None:
    """Surface Python directive migrations before the Rust repeat prepass."""
    from sase.xprompt._directive_collect import collect_prompt_directive_matches
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)
    collect_prompt_directive_matches(protected)


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
    count, explicit_base, bead_id, prompt_stripped = _extract_repeat_identity(prompt)
    if count is None:
        return []
    if timestamps is not None and len(timestamps) != count:
        raise ValueError(
            f"repeat timestamp batch has {len(timestamps)} timestamps for {count} slots"
        )
    template_base = _agent_name_template_in_prompt(prompt)
    if template_base is None and explicit_base is not None:
        template_base = explicit_base if is_agent_name_template(explicit_base) else None
    if template_base is not None:
        raise DirectiveError(
            "Cannot combine %repeat with agent name template "
            f"'%id:{template_base}'; choose a concrete repeat base name "
            "or remove %repeat."
        )

    resume_target = (
        None if explicit_base is not None else sole_resume_agent_name(prompt_stripped)
    )
    if resume_target is not None:
        with agent_name_allocation_lock():
            names = allocate_resume_names(resume_target, count)
    else:
        wait_target = (
            None
            if explicit_base is not None
            else single_wait_agent_name(prompt_stripped)
        )
        if wait_target is not None and parse_tribe_reference(wait_target) is not None:
            wait_target = None
        if wait_target is not None:
            with agent_name_allocation_lock():
                names = allocate_wait_names(wait_target, count)
        else:
            base = reserve_repeat_name_base(explicit_base, count)
            names = [f"{base}.{k}" for k in range(1, count + 1)]

    specs = [
        RepeatAgentSpec(
            name=names[k - 1],
            iteration=k,
            total=count,
            prompt=(
                f"{_repeat_id_directive(names[k - 1], bead_id)}\n{prompt_stripped}"
                if k == 1
                else (
                    f"{_repeat_id_directive(names[k - 1], bead_id)}\n"
                    f"%wait:{names[k - 2]}\n{prompt_stripped}"
                )
            ),
            timestamp=None if timestamps is None else timestamps[k - 1],
            prev_name=None if k == 1 else names[k - 2],
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


def _repeat_id_directive(name: str, bead_id: str | None) -> str:
    if bead_id is None:
        return f"%i:{name}"
    return f"%i({name}, bead={bead_id})"


def _agent_name_template_in_prompt(prompt: str) -> str | None:
    if "%i" not in prompt:
        return None

    from sase.agent.multi_prompt_references import extract_static_name_directive

    explicit_name = extract_static_name_directive(prompt)
    if explicit_name is None:
        return None
    return explicit_name if is_agent_name_template(explicit_name) else None
