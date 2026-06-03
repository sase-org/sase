"""Shared naming helpers for plan/question/feedback/coder handoff agents."""

from __future__ import annotations

import re
from collections.abc import Mapping

AGENT_FAMILY_SEPARATOR = "--"
PLAN_CHAIN_PLAN_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}plan"
PLAN_CHAIN_QUESTION_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}q"
PLAN_CHAIN_CODER_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}code"
PLAN_CHAIN_EPIC_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}epic"
PLAN_CHAIN_LEGEND_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}legend"
PLAN_CHAIN_COMMIT_SUFFIX = f"{AGENT_FAMILY_SEPARATOR}commit"
PLAN_CHAIN_PARENT_TIMESTAMP_FIELD = "plan_chain_parent_timestamp"
PLAN_CHAIN_ROOT_FIELD = "plan_chain_root"
AGENT_FAMILY_FIELD = "agent_family"
AGENT_FAMILY_ROLE_FIELD = "agent_family_role"

_FEEDBACK_SUFFIX_RE = re.compile(r"^(?:--|[-.])(\d+)$")
_KNOWN_SUFFIXES = {
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_EPIC_SUFFIX,
    PLAN_CHAIN_LEGEND_SUFFIX,
    PLAN_CHAIN_COMMIT_SUFFIX,
}
_LEGACY_DOTTED_SUFFIX_MAP = {
    ".plan": PLAN_CHAIN_PLAN_SUFFIX,
    ".q": PLAN_CHAIN_QUESTION_SUFFIX,
    ".code": PLAN_CHAIN_CODER_SUFFIX,
    ".epic": PLAN_CHAIN_EPIC_SUFFIX,
    ".legend": PLAN_CHAIN_LEGEND_SUFFIX,
    ".commit": PLAN_CHAIN_COMMIT_SUFFIX,
}
_LEGACY_DASH_SUFFIX_MAP = {
    "-plan": PLAN_CHAIN_PLAN_SUFFIX,
    "-q": PLAN_CHAIN_QUESTION_SUFFIX,
    "-code": PLAN_CHAIN_CODER_SUFFIX,
    "-epic": PLAN_CHAIN_EPIC_SUFFIX,
    "-legend": PLAN_CHAIN_LEGEND_SUFFIX,
    "-commit": PLAN_CHAIN_COMMIT_SUFFIX,
}
_LEGACY_SUFFIX_MAP = {**_LEGACY_DOTTED_SUFFIX_MAP, **_LEGACY_DASH_SUFFIX_MAP}


def plan_chain_feedback_suffix(feedback_round: int) -> str:
    """Return the visible suffix for a one-based feedback round."""
    if feedback_round < 1:
        raise ValueError("feedback_round must be one-based")
    return f"{AGENT_FAMILY_SEPARATOR}{feedback_round + 1}"


def _plan_chain_feedback_round_from_raw_suffix(suffix: object) -> int | None:
    if not isinstance(suffix, str):
        return None
    match = _FEEDBACK_SUFFIX_RE.match(suffix)
    if match is None:
        return None
    round_number = int(match.group(1))
    return round_number if round_number >= 2 else None


def canonical_plan_chain_suffix(suffix: object) -> str | None:
    """Return the canonical plan-chain suffix, or ``None`` if unrecognized."""
    if not isinstance(suffix, str):
        return None
    if suffix in _LEGACY_SUFFIX_MAP:
        return _LEGACY_SUFFIX_MAP[suffix]
    if suffix in _KNOWN_SUFFIXES:
        return suffix
    feedback_round = _plan_chain_feedback_round_from_raw_suffix(suffix)
    if feedback_round is not None:
        return f"{AGENT_FAMILY_SEPARATOR}{feedback_round}"
    return None


def plan_chain_feedback_round(suffix: object) -> int | None:
    """Return the visible feedback round number for a known feedback suffix."""
    canonical = canonical_plan_chain_suffix(suffix)
    if canonical is None:
        return None
    return _plan_chain_feedback_round_from_raw_suffix(canonical)


def agent_family_phase_name(base_name: str, suffix: str) -> str:
    """Return the visible agent-family phase name for *base_name* and *suffix*."""
    canonical = canonical_plan_chain_suffix(suffix)
    if canonical is None:
        raise ValueError(f"not a plan-chain suffix: {suffix!r}")
    return f"{base_name}{canonical}"


def plan_chain_agent_name(base_name: str, suffix: str) -> str:
    """Return the visible agent name for *base_name* and a plan-chain suffix."""
    return agent_family_phase_name(base_name, suffix)


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


def is_agent_family_member(name: object, *, include_legacy_dash: bool = False) -> bool:
    """Return whether *name* has a known agent-family suffix."""
    return (
        _split_agent_family_name(name, include_legacy_dash=include_legacy_dash)
        is not None
    )


def agent_family_role_for_suffix(suffix: object) -> str | None:
    """Return the metadata role for a known plan-chain suffix."""
    canonical = canonical_plan_chain_suffix(suffix)
    if canonical is None:
        return None
    if canonical == PLAN_CHAIN_PLAN_SUFFIX:
        return "plan"
    if canonical == PLAN_CHAIN_QUESTION_SUFFIX:
        return "q"
    if canonical == PLAN_CHAIN_CODER_SUFFIX:
        return "code"
    if canonical == PLAN_CHAIN_EPIC_SUFFIX:
        return "epic"
    if canonical == PLAN_CHAIN_LEGEND_SUFFIX:
        return "legend"
    if canonical == PLAN_CHAIN_COMMIT_SUFFIX:
        return "commit"
    if plan_chain_feedback_round(canonical) is not None:
        return "feedback"
    return None


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
