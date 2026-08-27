"""Resolve a settled gate shell's branch-keyed follow-up policy.

The envelope's ``shell`` block is the single source of truth for follow-up
policy (member metadata never duplicates it -- see ``gate_shell/member.py``),
so every function here re-parses the already-validated block through
:class:`~sase.notification_gates.model_shell.GateShellSpec` rather than
hand-walking raw JSON. A malformed or absent ``shell`` block always resolves
to "no policy" -- this runs at settlement time, well after creation-time
validation would have rejected a bad block, so raising here would turn a
settlement into a crash instead of a quiet no-follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.gate_shell.models import GateShellState
from sase.notification_gates.model_shell import GateShellSpec

#: ``gate_state`` values whose branch key is the joined selection.
_ANSWERED_STATES = frozenset({"answered", "completed"})

#: ``gate_state`` -> reserved branch key for the explicit-only axis. A lost
#: gate is judged as a failed gate for follow-up-policy purposes.
_RESERVED_STATE_KEYS = {
    "timeout": "timeout",
    "stopped": "stopped",
    "failed": "failed",
    "lost": "failed",
}


@dataclass(frozen=True, slots=True)
class GateFollowupPolicy:
    """Resolved follow-up policy for one gate-shell settlement."""

    branch_key: str
    prompt: str
    output: tuple[str, ...]
    fork: str
    model: str | None
    suffix: str | None = None
    role: str | None = None
    raw_prompt: bool = False
    status: str | None = None
    accent: str | None = None


def _settlement_branch_key(
    envelope: dict[str, Any],
    *,
    gate_state: GateShellState,
    response: dict[str, Any],
) -> str:
    """Return the branch key this settlement resolves policy against."""
    if gate_state in _ANSWERED_STATES:
        selected = response.get("selected_option_ids")
        if isinstance(selected, list):
            return "+".join(str(option_id) for option_id in selected)
        return ""
    return _RESERVED_STATE_KEYS.get(gate_state, "failed")


def resolve_gate_followup(
    envelope: dict[str, Any],
    *,
    gate_state: GateShellState,
    response: dict[str, Any],
) -> GateFollowupPolicy | None:
    """Resolve the effective follow-up policy for a settled gate shell.

    The answered axis (``answered``/``completed``) inherits the top-level
    ``shell.next`` when the matched branch does not declare its own -- or is
    not declared at all. The unanswered axis (``timeout``/``stopped``/
    ``failed``/``lost``) is explicit-only: an undeclared reserved key resolves
    to ``None`` rather than inheriting, so a gate that nobody answered never
    silently spawns an agent. ``prompt: null`` at either level suppresses
    follow-up outright.
    """
    shell = _parse_shell(envelope)
    if shell is None:
        return None
    key = _settlement_branch_key(envelope, gate_state=gate_state, response=response)
    branch = shell.branches.get(key)
    if gate_state in _ANSWERED_STATES:
        if branch is not None:
            prompt, output, fork, model, suffix, role, raw_prompt = (
                branch.prompt,
                branch.output,
                branch.fork,
                branch.model,
                branch.suffix,
                branch.role,
                branch.raw_prompt,
            )
            status, accent = branch.status, branch.accent
        else:
            prompt, output, fork, model, suffix, role, raw_prompt = (
                shell.next.prompt,
                shell.next.output,
                shell.next.fork,
                shell.next.model,
                shell.next.suffix,
                shell.next.role,
                shell.next.raw_prompt,
            )
            status, accent = None, None
    else:
        if branch is None:
            return None
        prompt, output, fork, model, suffix, role, raw_prompt = (
            branch.prompt,
            branch.output,
            branch.fork,
            branch.model,
            branch.suffix,
            branch.role,
            branch.raw_prompt,
        )
        status, accent = branch.status, branch.accent
    if not prompt:
        return None
    return GateFollowupPolicy(
        branch_key=key,
        prompt=prompt,
        output=output,
        fork=fork,
        model=model,
        suffix=suffix,
        role=role,
        raw_prompt=raw_prompt,
        status=status,
        accent=accent,
    )


def resolve_gate_branch_presentation(
    envelope: dict[str, Any],
    *,
    gate_state: GateShellState,
    response: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return the ``(status, accent)`` override for this settlement's branch."""
    shell = _parse_shell(envelope)
    if shell is None:
        return None, None
    key = _settlement_branch_key(envelope, gate_state=gate_state, response=response)
    branch = shell.branches.get(key)
    if branch is None:
        return None, None
    return branch.status, branch.accent


def _parse_shell(envelope: dict[str, Any]) -> GateShellSpec | None:
    raw_shell = envelope.get("shell")
    if not isinstance(raw_shell, dict):
        return None
    raw_branches = envelope.get("branches")
    if not isinstance(raw_branches, list):
        return None
    try:
        branches = tuple(
            tuple(str(option_id) for option_id in branch) for branch in raw_branches
        )
        return GateShellSpec.from_mapping(raw_shell, branches=branches)
    except Exception:
        return None


__all__ = [
    "GateFollowupPolicy",
    "resolve_gate_branch_presentation",
    "resolve_gate_followup",
]
