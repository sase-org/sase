"""Shared naming helpers for plan/feedback/coder handoff agents."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

AGENT_FAMILY_SEPARATOR = "--"
PLAN_CHAIN_PLAN_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}plan"
PLAN_CHAIN_CODER_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}code"
PLAN_CHAIN_EPIC_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}epic"
PLAN_CHAIN_COMMIT_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}commit"
PLAN_CHAIN_MONITOR_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}mon"
PLAN_CHAIN_GATE_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}gate"
PLAN_CHAIN_PARENT_TIMESTAMP_FIELD = "plan_chain_parent_timestamp"
PLAN_CHAIN_ROOT_FIELD = "plan_chain_root"
AGENT_FAMILY_FIELD = "agent_family"
AGENT_FAMILY_ROLE_FIELD = "agent_family_role"
AGENT_FAMILY_PARALLEL_FIELD = "agent_family_parallel"

_FEEDBACK_SUFFIX_RE = re.compile(r"^(?:--|[-.])(\d+)$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")
_ROOT_TOKEN_SUFFIX_RE = re.compile(r"^--([A-Za-z0-9_]+)$")
_PLAN_FEEDBACK_SUFFIX_RE = re.compile(r"^--plan-([A-Za-z0-9_]+)$")
_MONITOR_SEQUENCE_SUFFIX_RE = re.compile(r"^--mon-([A-Za-z0-9_]+)$")
_GATE_SEQUENCE_SUFFIX_RE = re.compile(r"^--gate-([A-Za-z0-9_]+)$")
_KNOWN_SUFFIXES = {
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
    PLAN_CHAIN_MONITOR_SUFFIX,
    PLAN_CHAIN_GATE_SUFFIX,
}
_LEGACY_DOTTED_SUFFIX_MAP = {
    ".plan": PLAN_CHAIN_PLAN_SUFFIX,
    ".code": PLAN_CHAIN_CODER_SUFFIX,
    ".epic": PLAN_CHAIN_EPIC_SUFFIX,
    ".commit": PLAN_CHAIN_COMMIT_SUFFIX,
}
_LEGACY_DASH_SUFFIX_MAP = {
    "-plan": PLAN_CHAIN_PLAN_SUFFIX,
    "-code": PLAN_CHAIN_CODER_SUFFIX,
    "-epic": PLAN_CHAIN_EPIC_SUFFIX,
    "-commit": PLAN_CHAIN_COMMIT_SUFFIX,
}
_LEGACY_SUFFIX_MAP = {**_LEGACY_DOTTED_SUFFIX_MAP, **_LEGACY_DASH_SUFFIX_MAP}
_PHASE_SUFFIX_ROLES = {
    PLAN_CHAIN_PLAN_SUFFIX: "plan",
    PLAN_CHAIN_CODER_SUFFIX: "code",
    PLAN_CHAIN_EPIC_SUFFIX: "epic",
    PLAN_CHAIN_COMMIT_SUFFIX: "commit",
    PLAN_CHAIN_MONITOR_SUFFIX: "monitor",
    PLAN_CHAIN_GATE_SUFFIX: "gate",
}
_EXPLICIT_FAMILY_ROLES = {
    "plan",
    "code",
    "epic",
    "commit",
    "feedback",
    "monitor",
    "gate",
}


@dataclass(frozen=True)
class _PlanChainSuffixInfo:
    """Structured classification for a plan-chain family suffix."""

    suffix: str
    role: str
    kind: str
    token: str | None = None
    legacy: bool = False

    @property
    def is_feedback(self) -> bool:
        return self.role == "feedback"


def _plan_chain_feedback_suffix(feedback_round: int) -> str:
    """Return the visible suffix for a one-based feedback round."""
    if feedback_round < 1:
        raise ValueError("feedback_round must be one-based")
    return f"{AGENT_FAMILY_SEPARATOR}{feedback_round + 1}"


def _stored_family_role(role: object) -> str | None:
    if not isinstance(role, str):
        return None
    if role in _EXPLICIT_FAMILY_ROLES:
        return role
    return role if _TOKEN_RE.match(role) else None


def _plan_chain_feedback_round_from_raw_suffix(suffix: object) -> int | None:
    if not isinstance(suffix, str):
        return None
    match = _FEEDBACK_SUFFIX_RE.match(suffix)
    if match is None:
        return None
    round_number = int(match.group(1))
    return round_number if round_number >= 2 else None


def _canonical_plan_chain_suffix(suffix: str) -> str | None:
    if suffix in _LEGACY_SUFFIX_MAP:
        return _LEGACY_SUFFIX_MAP[suffix]
    if suffix in _KNOWN_SUFFIXES:
        return suffix
    match = _PLAN_FEEDBACK_SUFFIX_RE.match(suffix)
    if match is not None:
        return suffix
    match = _MONITOR_SEQUENCE_SUFFIX_RE.match(suffix)
    if match is not None:
        return suffix
    match = _GATE_SEQUENCE_SUFFIX_RE.match(suffix)
    if match is not None:
        return suffix
    match = _ROOT_TOKEN_SUFFIX_RE.match(suffix)
    if match is not None:
        return suffix
    feedback_round = _plan_chain_feedback_round_from_raw_suffix(suffix)
    if feedback_round is not None:
        return _plan_chain_feedback_suffix(feedback_round - 1)
    return None


def canonical_plan_chain_suffix(suffix: object) -> str | None:
    """Return the canonical plan-chain suffix, or ``None`` if unrecognized."""
    if not isinstance(suffix, str):
        return None
    return _canonical_plan_chain_suffix(suffix)


def _parse_plan_chain_suffix(
    suffix: object,
    *,
    agent_family_role: object = None,
) -> _PlanChainSuffixInfo | None:
    """Return structured suffix metadata for new and legacy plan-chain rows."""
    if not isinstance(suffix, str):
        return None

    stored_role = _stored_family_role(agent_family_role)
    legacy_suffix = suffix in _LEGACY_SUFFIX_MAP
    if legacy_suffix:
        suffix = _LEGACY_SUFFIX_MAP[suffix]

    if suffix in _PHASE_SUFFIX_ROLES:
        role = _PHASE_SUFFIX_ROLES[suffix]
        return _PlanChainSuffixInfo(
            suffix=suffix,
            role=role,
            kind="phase",
            legacy=legacy_suffix,
        )

    match = _PLAN_FEEDBACK_SUFFIX_RE.match(suffix)
    if match is not None:
        return _PlanChainSuffixInfo(
            suffix=suffix,
            role="feedback",
            kind="feedback",
            token=match.group(1),
        )

    match = _MONITOR_SEQUENCE_SUFFIX_RE.match(suffix)
    if match is not None:
        return _PlanChainSuffixInfo(
            suffix=suffix,
            role="monitor",
            kind="phase",
            token=match.group(1),
        )

    match = _GATE_SEQUENCE_SUFFIX_RE.match(suffix)
    if match is not None:
        return _PlanChainSuffixInfo(
            suffix=suffix,
            role="gate",
            kind="phase",
            token=match.group(1),
        )

    match = _ROOT_TOKEN_SUFFIX_RE.match(suffix)
    if match is not None:
        token = match.group(1)
        if stored_role is not None:
            return _PlanChainSuffixInfo(
                suffix=suffix,
                role=stored_role,
                kind="legacy_feedback" if stored_role == "feedback" else "phase",
                token=token,
                legacy=legacy_suffix or stored_role == "feedback",
            )
        feedback_round = _plan_chain_feedback_round_from_raw_suffix(suffix)
        if feedback_round is not None:
            return _PlanChainSuffixInfo(
                suffix=suffix,
                role="feedback",
                kind="legacy_feedback",
                token=token,
                legacy=True,
            )
        return None

    legacy_feedback_round = _plan_chain_feedback_round_from_raw_suffix(suffix)
    if legacy_feedback_round is not None:
        canonical = _plan_chain_feedback_suffix(legacy_feedback_round - 1)
        return _PlanChainSuffixInfo(
            suffix=canonical,
            role="feedback",
            kind="legacy_feedback",
            token=str(legacy_feedback_round),
            legacy=True,
        )
    return None


def plan_chain_feedback_round(
    suffix: object,
    *,
    agent_family_role: object = None,
) -> int | None:
    """Return the visible feedback round number for a known feedback suffix."""
    info = _parse_plan_chain_suffix(suffix, agent_family_role=agent_family_role)
    if info is None or not info.is_feedback:
        return None
    if info.kind == "legacy_feedback":
        return _plan_chain_feedback_round_from_raw_suffix(info.suffix)
    if info.token is None:
        return None
    try:
        return int(info.token) + 2
    except ValueError:
        return None


def agent_family_phase_name(base_name: str, suffix: str) -> str:
    """Return the visible agent-family phase name for *base_name* and *suffix*."""
    canonical = canonical_plan_chain_suffix(suffix)
    if canonical is None:
        raise ValueError(f"not a plan-chain suffix: {suffix!r}")
    return f"{base_name}{canonical}"


def plan_chain_agent_name(base_name: str, suffix: str) -> str:
    """Return the visible agent name for *base_name* and a plan-chain suffix."""
    return agent_family_phase_name(base_name, suffix)


def planner_row_name(name: object, *, include_legacy_dash: bool = False) -> str | None:
    """Return the canonical ``<base>--plan`` row name for a plan-phase member.

    Returns ``None`` unless *name* is a plan-chain family member whose suffix
    canonicalizes to the planner ``--plan`` phase. Legacy spellings such as
    ``base.plan`` (and ``base-plan`` when *include_legacy_dash* is set) map onto
    the same canonical planner-row name, so a ``%wait`` on either form resolves
    to the canonical planner row.
    """
    split = _split_agent_family_name(name, include_legacy_dash=include_legacy_dash)
    if split is None:
        return None
    base, suffix = split
    if suffix != PLAN_CHAIN_PLAN_SUFFIX:
        return None
    return agent_family_phase_name(base, PLAN_CHAIN_PLAN_SUFFIX)


def _split_agent_family_name(
    name: object, *, include_legacy_dash: bool = False
) -> tuple[str, str] | None:
    if not isinstance(name, str) or not name:
        return None
    separators = [AGENT_FAMILY_SEPARATOR, "."]
    if include_legacy_dash:
        separators.append("-")
    for separator in separators:
        head, sep, tail = name.rpartition(separator)
        if not sep or not head or not tail:
            continue
        suffix = canonical_plan_chain_suffix(f"{sep}{tail}")
        if suffix is None and separator == AGENT_FAMILY_SEPARATOR:
            suffix = f"{separator}{tail}" if _TOKEN_RE.match(tail) else None
        if suffix is not None:
            return head, suffix
    return None


def agent_family_base(name: object, *, include_legacy_dash: bool = False) -> str | None:
    """Return the base family name for a known family member name."""
    split = _split_agent_family_name(name, include_legacy_dash=include_legacy_dash)
    return split[0] if split is not None else None


def _agent_family_suffix(
    name: object, *, include_legacy_dash: bool = False
) -> str | None:
    """Return the canonical suffix for a known family member name."""
    split = _split_agent_family_name(name, include_legacy_dash=include_legacy_dash)
    return split[1] if split is not None else None


def agent_family_suffix_token(suffix: object) -> str | None:
    """Return the bare token from an agent-family suffix."""
    if not isinstance(suffix, str):
        return None
    for separator in (AGENT_FAMILY_SEPARATOR, ".", "-"):
        if suffix.startswith(separator):
            token = suffix[len(separator) :]
            return token or None
    return None


def is_agent_family_member(name: object, *, include_legacy_dash: bool = False) -> bool:
    """Return whether *name* has a known agent-family suffix."""
    return (
        _split_agent_family_name(name, include_legacy_dash=include_legacy_dash)
        is not None
    )


def agent_family_role_for_suffix(
    suffix: object,
    *,
    agent_family_role: object = None,
) -> str | None:
    """Return the metadata role for a known plan-chain suffix."""
    info = _parse_plan_chain_suffix(suffix, agent_family_role=agent_family_role)
    return info.role if info is not None else None


def is_plan_feedback_suffix(
    suffix: object,
    *,
    agent_family_role: object = None,
) -> bool:
    """Return whether *suffix* identifies a plan-feedback row."""
    info = _parse_plan_chain_suffix(suffix, agent_family_role=agent_family_role)
    return bool(info and info.is_feedback)


def _reserved_agent_family_names(
    base_name: str,
    *,
    extra_suffixes: list[str] | tuple[str, ...] = (),
) -> set[str]:
    from sase.agent.names import get_reserved_agent_names

    reserved = get_reserved_agent_names()
    reserved.add(base_name)
    for suffix in (PLAN_CHAIN_PLAN_SUFFIX, f"{AGENT_FAMILY_SEPARATOR}0"):
        reserved.add(f"{base_name}{suffix}")
    for suffix in extra_suffixes:
        canonical = canonical_plan_chain_suffix(suffix) or suffix
        reserved.add(f"{base_name}{canonical}")
    return reserved


def _allocate_agent_family_child_name(
    base_name: str,
    suffix_template: str,
    *,
    extra_reserved_suffixes: list[str] | tuple[str, ...] = (),
) -> str:
    """Allocate a concrete family child name from a suffix template."""
    if not base_name:
        raise ValueError("base_name is required")
    if "@" not in suffix_template:
        raise ValueError("suffix_template must contain '@'")
    from sase.agent.names import allocate_agent_name_template

    reserved = _reserved_agent_family_names(
        base_name,
        extra_suffixes=extra_reserved_suffixes,
    )
    return allocate_agent_name_template(
        f"{base_name}{suffix_template}", reserved=reserved
    )


def allocate_agent_family_child_suffix(
    base_name: str,
    suffix_template: str,
    *,
    extra_reserved_suffixes: list[str] | tuple[str, ...] = (),
) -> str:
    """Allocate and return only the suffix portion for a family child name."""
    name = _allocate_agent_family_child_name(
        base_name,
        suffix_template,
        extra_reserved_suffixes=extra_reserved_suffixes,
    )
    if not name.startswith(base_name):
        raise AssertionError("allocated family name did not preserve base")
    return name[len(base_name) :]


def _plan_chain_suffix_from_meta(meta: Mapping[str, object]) -> str | None:
    """Infer a canonical plan-chain suffix from artifact metadata.

    ``role_suffix`` is authoritative for new artifacts. Name suffix inference
    keeps older artifacts classifiable when they only have ``name`` and
    ``workflow_name``.
    """
    suffix = canonical_plan_chain_suffix(meta.get("role_suffix"))
    if suffix is not None:
        return suffix

    name = meta.get("name")
    workflow_name = meta.get("workflow_name")
    if isinstance(name, str) and isinstance(workflow_name, str):
        if name.startswith(workflow_name):
            suffix = canonical_plan_chain_suffix(name[len(workflow_name) :])
            if suffix is not None:
                return suffix

    if isinstance(name, str):
        for candidate in (*_KNOWN_SUFFIXES, *_LEGACY_DOTTED_SUFFIX_MAP):
            if name.endswith(candidate):
                return canonical_plan_chain_suffix(candidate)
        suffix = _agent_family_suffix(name)
        if suffix is not None:
            return suffix

    return None


def is_plan_chain_artifact_meta(meta: Mapping[str, object]) -> bool:
    """Return whether artifact metadata describes a plan-chain phase."""
    return _plan_chain_suffix_from_meta(meta) is not None
