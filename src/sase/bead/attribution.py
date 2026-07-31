"""Resolve the SASE agent responsible for creating a bead.

Attribution *policy* — how a phase inherits from its parent epic and when the
store owner is used — lives in the Rust core. This module is the host half: it
discovers the running agent from the process environment and reads a plan
file's recorded proposer, then hands core an explicit creator (or nothing).
"""

from __future__ import annotations

from pathlib import Path

from sase.agent.identity import discover_agent_identity
from sase.bead.model import IssueType
from sase.core.agent_identity_facade import (
    globalize_owned_agent_name,
    validate_new_agent_name,
)
from sase.sdd.frontmatter import parse_frontmatter

# ``discover_agent_identity`` already ignores the bare ``SASE_AGENT`` launcher
# flag (``SASE_AGENT=1``) and falls through to ``agent_meta.json`` on its own
# (bead ``sase-bp``, commit ``14d66229a``), so this resolver does not need to
# re-filter identity sources.


def acting_agent_name() -> str | None:
    """Return the running agent's durable global name, if there is one.

    Returns ``None`` — never raises — when no agent is running or the
    discovered identity is unusable, so bead creation degrades to the store
    owner instead of failing.
    """
    try:
        identity = discover_agent_identity()
        if identity is None:
            return None
        validate_new_agent_name(identity.name)
        return globalize_owned_agent_name(identity.name)
    except Exception:
        return None


def plan_proposed_by(plan_path: Path | str) -> str | None:
    """Return the ``proposed_by`` frontmatter value of *plan_path*, if any.

    Deliberately reads frontmatter instead of running full plan validation, so
    callers stay cheap and keep working on a plan that would not validate.
    """
    try:
        content = Path(plan_path).read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter, _, had_frontmatter = parse_frontmatter(content)
    if not had_frontmatter:
        return None
    value = frontmatter.get("proposed_by")
    if not isinstance(value, str):
        return None
    return value.strip() or None


def resolve_bead_creator(
    *,
    issue_type: IssueType | str,
    plan_proposed_by: str | None = None,
) -> str | None:
    """Return the explicit creator Python supplies for a new bead.

    ``phase`` beads return ``None`` so the Rust core inherits the creator from
    their parent epic; a ``plan`` bead prefers the plan's recorded proposer;
    everything else is attributed to the acting agent. ``None`` always means
    "core decides", which ends at the store owner.
    """
    type_value = issue_type.value if isinstance(issue_type, IssueType) else issue_type
    if type_value == IssueType.PHASE.value:
        return None
    if type_value == IssueType.PLAN.value:
        proposer = (plan_proposed_by or "").strip()
        if proposer:
            return proposer
    return acting_agent_name()


__all__ = [
    "acting_agent_name",
    "plan_proposed_by",
    "resolve_bead_creator",
]
