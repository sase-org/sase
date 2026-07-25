"""Strict shape guards for agent names the runtime generates itself.

Classification of names already on disk is total: a legacy spelling such as
``fi--code.f0`` is read rather than rejected. Generation is the opposite side
of that contract — every name SASE composes must satisfy the strict rule that
a ``--<role>`` family suffix appears at most once, in the final dot-separated
segment. Historical names such as ``4x--epic.f-0`` and ``fi--code.f0--code``
exist because family attachment and resume-derived naming appended to a base
that already carried a role suffix; these helpers close that door.
"""

from __future__ import annotations

from sase.plan_chain import AGENT_FAMILY_SEPARATOR

__all__ = [
    "GeneratedAgentNameError",
    "ensure_generated_agent_name",
    "generated_agent_name_is_valid",
    "generated_child_name_base",
]


class GeneratedAgentNameError(RuntimeError):
    """Raised when the runtime would compose a structurally invalid name."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"Cannot generate agent name '{name}': {reason}")


def generated_agent_name_is_valid(name: str) -> bool:
    """Return whether *name* is valid as a newly created agent name."""
    from sase.core.agent_identity_facade import validate_new_agent_name

    try:
        validate_new_agent_name(name)
    except ValueError:
        return False
    return True


def ensure_generated_agent_name(name: str, *, reason: str) -> None:
    """Raise :class:`GeneratedAgentNameError` unless *name* is strictly valid."""
    if not generated_agent_name_is_valid(name):
        raise GeneratedAgentNameError(name, reason)


def generated_child_name_base(name: str) -> str:
    """Return the base a generated ``<base>.<suffix>`` child must hang off of.

    Appending a dotted segment to a family member such as ``fi--code`` would
    push its ``--code`` suffix out of the final segment, so the child hangs off
    the family name (``fi``) instead. A legacy base that still carries a family
    marker after that step (``fi--code.f0``) falls back to its top-level hood.
    Names that can already parent a dotted child are returned unchanged.
    """
    from sase.core.agent_identity_facade import (
        AgentFamilyNameKind,
        agent_local_hood,
        parse_agent_family_name,
    )

    base = name
    try:
        parsed = parse_agent_family_name(name)
    except ValueError:
        return name
    if parsed.kind is AgentFamilyNameKind.MEMBER:
        base = parsed.family_name
    if AGENT_FAMILY_SEPARATOR not in base:
        return base
    try:
        return agent_local_hood(name)
    except ValueError:
        return base
