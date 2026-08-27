"""Resolve a settled gate shell's branch-keyed follow-up policy.

The envelope's ``shell`` block is the single source of truth for follow-up
policy (member metadata never duplicates it -- see ``gate_shell/member.py``),
so every function here re-parses the already-validated block through
:class:`~sase.notification_gates.model_shell.GateShellSpec` rather than
hand-walking raw JSON. Settlement must parse with the same branch-key policy
as gate creation; a present-but-unparseable shell block is a bug report to log
and surface on the shell metadata, not an expected no-follow-up branch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sase.gate_shell.models import GateShellState
from sase.notification_gates.model_shell import (
    GateShellBranchSpec,
    GateShellNext,
    GateShellSpec,
    subset_branches_allowed,
)

logger = logging.getLogger(__name__)

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


@dataclass(frozen=True, slots=True)
class _ShellParseResult:
    """Parsed gate-shell spec plus whether a present block failed to parse."""

    shell: GateShellSpec | None
    unparseable: bool = False


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
    next_policy: GateShellBranchSpec | GateShellNext
    if gate_state in _ANSWERED_STATES and branch is None:
        status, accent = None, None
        next_policy = shell.next
    elif branch is None:
        return None
    else:
        status, accent = branch.status, branch.accent
        next_policy = branch

    if not next_policy.prompt:
        return None
    return GateFollowupPolicy(
        branch_key=key,
        prompt=next_policy.prompt,
        output=next_policy.output,
        fork=next_policy.fork,
        model=next_policy.model,
        suffix=next_policy.suffix,
        role=next_policy.role,
        raw_prompt=next_policy.raw_prompt,
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


def shell_block_unparseable(envelope: dict[str, Any]) -> bool:
    """Return whether a present shell block could not parse at settlement."""
    return _parse_shell_result(envelope, log_error=False).unparseable


def _parse_shell(envelope: dict[str, Any]) -> GateShellSpec | None:
    return _parse_shell_result(envelope).shell


def _parse_shell_result(
    envelope: dict[str, Any], *, log_error: bool = True
) -> _ShellParseResult:
    """Parse the envelope's shell block with settlement-time diagnostics."""
    raw_shell = envelope.get("shell")
    if not isinstance(raw_shell, dict):
        return _ShellParseResult(None)
    raw_branches = envelope.get("branches")
    if not isinstance(raw_branches, list):
        return _ShellParseResult(None, unparseable=True)
    try:
        branches = tuple(
            tuple(str(option_id) for option_id in branch) for branch in raw_branches
        )
        kind = envelope.get("kind")
        return _ShellParseResult(
            GateShellSpec.from_mapping(
                raw_shell,
                branches=branches,
                allow_branch_subsets=subset_branches_allowed(kind),
            )
        )
    except Exception:
        if log_error:
            logger.warning(
                "failed to parse gate shell block at settlement (kind=%r, branches=%r)",
                envelope.get("kind"),
                raw_branches,
                exc_info=True,
            )
        return _ShellParseResult(None, unparseable=True)


__all__ = [
    "GateFollowupPolicy",
    "resolve_gate_branch_presentation",
    "resolve_gate_followup",
    "shell_block_unparseable",
]
