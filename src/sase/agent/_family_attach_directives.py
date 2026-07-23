"""Directive parsing helpers for ``%id(suffix, family=parent)`` attach."""

from __future__ import annotations

import re
from typing import Any

from sase.agent import _family_attach_types as _types
from sase.plan_chain import AGENT_FAMILY_SEPARATOR

_SUFFIX_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")
_NAME_DIRECTIVE_KEYWORDS = frozenset({"bead", "clan", "family", "tribe"})
_NAME_MEMBERSHIP_KEYWORDS = frozenset({"clan", "family", "tribe"})


def parse_name_directive_args(
    positional_args: list[str],
    named_args: dict[str, str],
    *,
    source: str,
) -> _types.ParsedNameDirective:
    """Classify ``%id`` / ``%i`` arguments as plain naming or family attach."""

    unknown_keys = sorted(
        key for key in named_args if key not in _NAME_DIRECTIVE_KEYWORDS
    )
    if unknown_keys:
        keys = ", ".join(f"{key}=" for key in unknown_keys)
        raise ValueError(
            f"Unsupported keyword on {source}: {keys}. Only bead=, clan=, "
            "family=, and tribe= are supported."
        )
    selected_keywords = sorted(
        key for key in _NAME_MEMBERSHIP_KEYWORDS if key in named_args
    )
    if len(selected_keywords) > 1:
        raise ValueError(
            "The clan=, family=, and tribe= keywords on %id are mutually "
            "exclusive; set at most one."
        )
    if len(positional_args) > 1:
        raise ValueError(
            "The positional family form on %id is no longer supported; use "
            "%id(<suffix>, family=<parent>) instead."
        )

    bead_id = named_args.get("bead")
    if bead_id is not None and (not bead_id or re.fullmatch(r"\S+", bead_id) is None):
        raise ValueError(
            "The bead= keyword on %id requires a non-empty, whitespace-free bead ID."
        )

    clan = named_args.get("clan")
    if clan is not None:
        if len(positional_args) != 1:
            raise ValueError(
                f"The clan= keyword on {source} requires exactly one positional "
                "member id, e.g. %id(worker, clan=research)."
            )
        member_id = positional_args[0].strip()
        force_reuse = member_id.startswith("!")
        if force_reuse:
            member_id = member_id[1:]
        if not member_id:
            raise ValueError(
                f"The clan= keyword on {source} requires a non-empty member id."
            )
        if not clan.strip():
            raise ValueError(
                f"The clan= keyword on {source} requires a non-empty clan name."
            )
        return _types.ParsedNameDirective(
            plain_name=member_id,
            bead_id=bead_id,
            clan=clan,
            force_reuse=force_reuse,
        )

    family = named_args.get("family")
    if family is not None:
        if len(positional_args) != 1:
            raise ValueError(
                f"The family= keyword on {source} requires exactly one positional "
                "suffix; use %id(<suffix>, family=<family>) or "
                "%id(@, family=<family>)."
            )
        parent = family.strip()
        suffix = positional_args[0].strip()
        force_reuse = suffix.startswith("!")
        if force_reuse:
            suffix = suffix[1:]
        if not parent:
            raise ValueError(
                f"The family= keyword on {source} requires a non-empty family name."
            )
        if not suffix:
            raise ValueError(
                f"The family= keyword on {source} requires a non-empty suffix."
            )
        normalize_family_suffix_arg(suffix)
        return _types.ParsedNameDirective(
            bead_id=bead_id,
            force_reuse=force_reuse,
            family_parent=parent,
            family_suffix=suffix,
        )

    tribe = named_args.get("tribe")
    if tribe is not None:
        plain_name = positional_args[0].strip() if positional_args else ""
        force_reuse = plain_name.startswith("!")
        if force_reuse:
            plain_name = plain_name[1:]
        if positional_args and not plain_name:
            raise ValueError(
                f"The tribe= keyword on {source} requires a non-empty id when "
                "a positional id is supplied."
            )
        return _types.ParsedNameDirective(
            plain_name=plain_name,
            bead_id=bead_id,
            tribe=tribe,
            force_reuse=force_reuse,
        )

    return _types.ParsedNameDirective(
        plain_name=positional_args[0] if positional_args else "",
        bead_id=bead_id,
    )


def extract_family_attach_directive(
    prompt: str,
) -> _types.FamilyAttachDirective | None:
    """Return the first top-level family attach directive in *prompt*."""

    if "%" not in prompt:
        return None

    from sase.xprompt._directive_types import _DIRECTIVE_ALIASES, _DIRECTIVE_PATTERN
    from sase.xprompt._disabled_regions import protect_disabled_regions
    from sase.xprompt._fenced_blocks import protect_fenced_blocks
    from sase.xprompt._parsing import find_matching_paren_for_args, parse_args

    fenced: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced)
    disabled: list[str] = []
    protected = protect_disabled_regions(protected, disabled)

    for match in re.finditer(_DIRECTIVE_PATTERN, protected, re.MULTILINE):
        raw_name = match.group(1)
        if _DIRECTIVE_ALIASES.get(raw_name, raw_name) != "id":
            continue
        if match.group(2) is None:
            continue
        paren_start = match.end() - 1
        paren_end = find_matching_paren_for_args(protected, paren_start)
        if paren_end is None:
            continue
        positional_args, named_args = parse_args(protected[paren_start + 1 : paren_end])
        parsed = parse_name_directive_args(
            positional_args,
            named_args,
            source=f"%{raw_name}",
        )
        if parsed.family_parent is not None and parsed.family_suffix is not None:
            return _types.FamilyAttachDirective(
                parsed.family_parent,
                parsed.family_suffix,
                force_reuse=parsed.force_reuse,
            )
    return None


def _family_attach_parent_from_prompt(prompt: str) -> str | None:
    """Return the parent named by a top-level ``%id(suffix, family=parent)``."""
    directive = extract_family_attach_directive(prompt)
    return None if directive is None else directive.parent


def default_with_feedback_parent_from_family_attach(
    workflow_name: str,
    args: dict[str, Any],
    *,
    prompt: str,
    reference_offset: int | None = None,
    fenced_ranges: list[tuple[int, int]] | None = None,
) -> None:
    """Default ``#with_feedback``'s parent from a co-occurring family attach."""
    if workflow_name != "with_feedback" or args.get("parent"):
        return
    if reference_offset is not None:
        prompt = _prompt_segment_at_offset(
            prompt,
            reference_offset,
            fenced_ranges or [],
        )
    parent = _family_attach_parent_from_prompt(prompt)
    if parent:
        args["parent"] = parent


def _prompt_segment_at_offset(
    prompt: str,
    offset: int,
    fenced_ranges: list[tuple[int, int]],
) -> str:
    """Return the top-level ``---`` segment containing *offset*."""
    from sase.xprompt._parsing import _SEGMENT_SEPARATOR_RE

    start = 0
    end = len(prompt)
    for match in _SEGMENT_SEPARATOR_RE.finditer(prompt):
        if any(
            range_start <= match.start() < range_end
            for range_start, range_end in fenced_ranges
        ):
            continue
        if match.end() <= offset:
            start = match.end()
            continue
        end = match.start()
        break
    return prompt[start:end]


def normalize_family_suffix_arg(suffix: str) -> str:
    if suffix == "@":
        return f"{AGENT_FAMILY_SEPARATOR}@"
    if suffix.startswith((".", "-")) or AGENT_FAMILY_SEPARATOR in suffix:
        raise ValueError(
            f"Invalid %i family suffix '{suffix}'. Pass the bare suffix "
            "without a family separator, e.g. %i(reviewer, family=parent)."
        )
    if not _SUFFIX_TOKEN_RE.fullmatch(suffix):
        raise ValueError(
            f"Invalid %i family suffix '{suffix}'. Use letters, numbers, "
            "and underscores only, or @ to allocate the next free suffix."
        )
    return f"{AGENT_FAMILY_SEPARATOR}{suffix}"


__all__ = [
    "default_with_feedback_parent_from_family_attach",
    "extract_family_attach_directive",
    "normalize_family_suffix_arg",
    "parse_name_directive_args",
]
