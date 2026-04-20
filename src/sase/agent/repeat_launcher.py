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
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from sase.agent.names import (
    NameCollisionError,
    reserve_repeat_name_base,
    wait_for_agent_completion,
)
from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)
from sase.xprompt._fenced_blocks import (
    protect_fenced_blocks,
    unprotect_fenced_blocks,
)
from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

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


_REPEAT_NAME_PATTERN = re.compile(
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"%(repeat|r|name|n)"
    r"(?:(\()|:(`[^`]*`|[a-zA-Z0-9_#/.()-]*[a-zA-Z0-9_#/()-])|(\+))?"
)


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
    if "%" not in prompt:
        return None, None, prompt

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    repeat_count: int | None = None
    explicit_name: str | None = None
    regions: list[tuple[int, int]] = []

    for match in _REPEAT_NAME_PATTERN.finditer(protected):
        directive = match.group(1)
        canonical = "repeat" if directive in ("r", "repeat") else "name"

        has_paren = match.group(2) is not None
        colon_arg = match.group(3)
        plus_suffix = match.group(4)
        match_end = match.end()

        if has_paren:
            paren_start = match.end() - 1
            paren_end = find_matching_paren_for_args(protected, paren_start)
            if paren_end is not None:
                paren_content = protected[paren_start + 1 : paren_end]
                positional_args, _ = parse_args(paren_content)
                raw_arg = positional_args[0] if positional_args else ""
                match_end = paren_end + 1
            else:
                raw_arg = ""
        elif colon_arg is not None:
            if colon_arg.startswith("`") and colon_arg.endswith("`"):
                raw_arg = colon_arg[1:-1]
            else:
                raw_arg = colon_arg
        elif plus_suffix is not None:
            raw_arg = "true"
        else:
            raw_arg = ""

        regions.append((match.start(), match_end))

        if canonical == "repeat":
            if raw_arg:
                try:
                    repeat_count = int(raw_arg)
                except ValueError:
                    repeat_count = None
        else:
            explicit_name = raw_arg if raw_arg else None

    if repeat_count is None or repeat_count <= 1:
        return None, None, prompt

    cleaned = protected
    for start, end in reversed(regions):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = re.sub(r"^\s*\n", "", cleaned)

    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    cleaned = strip_disabled_region_markers(cleaned)
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)

    return repeat_count, explicit_name, cleaned


def spawn_repeat_batch(
    prompt: str,
    *,
    base_spawn_fn: Callable[[RepeatAgentSpec], None],
    sleep_between: float = 0.25,
) -> list[RepeatAgentSpec]:
    """Resolve names + call *base_spawn_fn* once per repeat slot, sequentially.

    *base_spawn_fn* receives a :class:`RepeatAgentSpec` and is responsible
    for every launch-site concern (workspace claim, timestamp, env-var
    injection).  After each spawn, blocks on
    :func:`wait_for_agent_completion` until the just-spawned agent writes
    ``done.json`` or its PID dies — only then is the next spec spawned.
    Returns the specs actually spawned, or an empty list when *prompt*
    has no ``%r:N`` directive (or ``N <= 1``).

    Raises :class:`NameCollisionError` if an explicit base name collides
    with a currently-active agent.
    """
    count, explicit_base, prompt_stripped = extract_repeat_and_name(prompt)
    if count is None:
        return []

    base = reserve_repeat_name_base(explicit_base, count)

    specs = [
        RepeatAgentSpec(
            name=f"{base}.{k}",
            iteration=k,
            total=count,
            prompt=f"%n:{base}.{k}\n{prompt_stripped}",
        )
        for k in range(1, count + 1)
    ]

    last = len(specs) - 1
    for i, spec in enumerate(specs):
        base_spawn_fn(spec)
        if i < last:
            wait_for_agent_completion(spec.name)
            if sleep_between > 0:
                time.sleep(sleep_between)

    return specs
