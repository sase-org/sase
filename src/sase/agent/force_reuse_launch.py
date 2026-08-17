"""Shared forced agent-name-reuse launch pipeline.

Both ACE (the trusted TUI surface that confirms forced reuse) and the durable
``sase run`` child process it submits need to run the same two-phase
pipeline: plan (parse + validate, no mutation) then apply (wipe the reserved
names). Keeping all parsing and syntax validation in the planning half before
anything destructive runs means a malformed prompt or a name collision is
rejected before an existing agent's name is ever released.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _ForceReuseLaunchPlan:
    """A validated, not-yet-applied forced-name-reuse launch."""

    rewritten_prompt: str
    owner_names: list[str]
    segment_envs: list[dict[str, str] | None]


class _ForceReuseLaunchFanoutError(RuntimeError):
    """Raised when a forced ``!`` name survives an alt/repeat fan-out prompt.

    ``rewrite_force_reuse_name_directives()`` strips the ``!`` from every
    ``%id``/``%i`` directive regardless of fan-out, but
    ``force_reuse_owner_names()`` bails out via ``_prompt_has_launch_fanout()``
    for alt (``%{...}``) and similar fan-out prompts and resolves no owner
    name. Left unhandled, the ``!``-stripped prompt would reach the child with
    a name still owned by the killed agent, producing the same confusing
    "confirmation is required" rejection this pipeline exists to fix.
    """

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt
        super().__init__(
            "Forced agent-name reuse ('!') cannot be combined with alt/fan-out "
            "directives in the same launch segment; split the launch or drop "
            "the forced name."
        )


def plan_force_reuse_launch(prompt: str) -> _ForceReuseLaunchPlan | None:
    """Plan a forced-name-reuse launch without mutating any name state.

    Returns ``None`` when *prompt* requests no forced reuse (the common case,
    so callers pay nothing beyond one rewrite check). Otherwise runs the full
    syntax/authorization preflight and returns a plan describing the
    ``!``-stripped prompt, the owner names :func:`apply_force_reuse_launch`
    must wipe, and the per-segment child-process env overlays carrying the
    one-shot force-reuse bead marker.

    Raises whatever ``sase.agent.launch_validation`` raises for an invalid
    prompt (a name collision, syntax error, or ambiguous bead authorization),
    plus :class:`_ForceReuseLaunchFanoutError` for the fan-out contradiction.
    """
    from sase.agent.force_reuse_bead import force_reuse_bead_env
    from sase.agent.launch_validation import (
        force_reuse_bead_associations_by_prompt,
        force_reuse_owner_names,
        preflight_launch_name_requests,
        rewrite_force_reuse_name_directives,
    )
    from sase.agent.multi_prompt import parse_multi_prompt

    rewritten_prompt = rewrite_force_reuse_name_directives(prompt)
    if rewritten_prompt == prompt:
        return None

    segments = parse_multi_prompt(prompt).segments
    preflight_launch_name_requests(segments, allow_force_reuse=True)

    owner_names = force_reuse_owner_names(segments)
    if not owner_names:
        raise _ForceReuseLaunchFanoutError(prompt)

    bead_associations = force_reuse_bead_associations_by_prompt(segments)
    segment_envs = [
        force_reuse_bead_env(association) or None for association in bead_associations
    ]
    return _ForceReuseLaunchPlan(
        rewritten_prompt=rewritten_prompt,
        owner_names=owner_names,
        segment_envs=segment_envs,
    )


def apply_force_reuse_launch(plan: _ForceReuseLaunchPlan) -> None:
    """Wipe the reserved owner names described by *plan*."""
    from sase.agent.launch_validation import wipe_names_for_forced_reuse

    wipe_names_for_forced_reuse(plan.owner_names)


__all__ = [
    "apply_force_reuse_launch",
    "plan_force_reuse_launch",
]
