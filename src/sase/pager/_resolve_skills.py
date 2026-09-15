"""Resolve xprompt skill references to canonical source files."""

from __future__ import annotations

from pathlib import Path

from sase.core.xprompt_skill_definition_facade import (
    XpromptSkillDefinitionResolution,
    resolve_xprompt_skill_definition,
)
from sase.pager._resolve_common import link_target_for_existing_path
from sase.pager.link_context import LinkResolutionContext, default_link_context
from sase.pager.targets import LinkResolution

_RETRYABLE_STATUSES = frozenset({"catalog_load_failure"})


def resolve_xprompt_skill_link(
    reference: str,
    *,
    context: LinkResolutionContext | None = None,
) -> LinkResolution:
    """Resolve one explicit or slash skill reference through Rust catalog rules."""
    resolved_context = context or default_link_context()
    result = resolve_xprompt_skill_definition(
        reference,
        project=(
            None
            if resolved_context.owner is None
            else resolved_context.owner.project_key
        ),
        root_dir=(
            None
            if not resolved_context.anchors
            else resolved_context.anchors[0].directory
        ),
    )
    if result.status != "success":
        return _unresolved_skill(result)
    if result.definition_path is None:
        return _unresolved_skill(result)
    target = link_target_for_existing_path(
        Path(result.definition_path),
        requested_line=None,
        context=resolved_context,
    )
    if target is None:
        return LinkResolution(
            unresolved_message=(
                result.diagnostic or f"skill {reference} source could not be opened"
            )
        )
    return LinkResolution(target=target)


def is_skill_lookup_candidate(reference: str) -> bool:
    """Return whether *reference* can be parsed as a skill lookup request."""
    return _is_explicit_skill_reference(reference) or _is_slash_skill_reference(
        reference
    )


def is_slash_skill_candidate(reference: str) -> bool:
    """Return whether *reference* is an unqualified single-segment slash token."""
    return _is_slash_skill_reference(reference)


def _unresolved_skill(
    result: XpromptSkillDefinitionResolution,
) -> LinkResolution:
    message = result.diagnostic or f"{result.authored_reference} could not be resolved"
    return LinkResolution(
        unresolved_message=message,
        retryable=result.status in _RETRYABLE_STATUSES,
    )


def _is_explicit_skill_reference(reference: str) -> bool:
    value = reference.strip()
    if not value.startswith("#"):
        return False
    token = value[1:].split("(", 1)[0].replace("__", "/")
    parts = token.split("/")
    return (len(parts) == 2 and parts[0] == "skill" and bool(parts[1])) or (
        len(parts) == 3 and parts[1] == "skill" and bool(parts[0]) and bool(parts[2])
    )


def _is_slash_skill_reference(reference: str) -> bool:
    value = reference.strip()
    if not value.startswith("/") or value.startswith("@/"):
        return False
    skill = value[1:]
    return (
        bool(skill)
        and "/" not in skill
        and all(
            character.isascii()
            and (character.isalnum() or character in {"_", "-", "."})
            for character in skill
        )
    )


__all__ = [
    "is_skill_lookup_candidate",
    "is_slash_skill_candidate",
    "resolve_xprompt_skill_link",
]
