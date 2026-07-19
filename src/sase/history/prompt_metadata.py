"""Presentation metadata extracted from stored prompt-history text."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
import re

from sase.xprompt import extract_project_from_vcs_tag, extract_vcs_workflow_tag
from sase.xprompt._directive_types import (
    _DEPRECATED_DIRECTIVES,
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
)
from sase.xprompt._exceptions import XPromptError
from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.xprompt._parsing import find_matching_paren_for_args
from sase.xprompt._parsing_references import XPromptReference, iter_xprompt_references
from sase.xprompt._parsing_vcs_refs import (
    _GENERIC_PROJECT_VCS_REF_PATTERN,
    _KNOWN_FALLBACK_VCS_PREFIXES,
)
from sase.xprompt._parsing_vcs_tags import _DIRECTIVE_PREFIX_RE
from sase.xprompt.directives import extract_prompt_directives


@dataclass(frozen=True)
class PromptListSummary:
    """Compact prompt metadata for a prompt-history list row."""

    project_prefix: str
    project_ref_display: str
    xprompts: tuple[str, ...]
    directive_token: str
    clean_preview: str


@dataclass(frozen=True)
class PromptPreviewSummary:
    """Verbose prompt metadata for the highlighted prompt preview."""

    vcs_tag: str | None
    xprompts: tuple[str, ...]
    directives: tuple[str, ...]


@dataclass(frozen=True)
class _DirectiveToken:
    """Known directive occurrence with enough span data for cleanup."""

    name: str
    start: int
    end: int
    suffix: str


_DIRECTIVE_RE = re.compile(_DIRECTIVE_PATTERN, re.MULTILINE)
_ALIAS_BY_DIRECTIVE = {
    directive: alias for alias, directive in _DIRECTIVE_ALIASES.items()
}
_DIRECTIVE_SUMMARY_ALIAS_SORT_KEYS = {
    # Keep model/id/auto in their familiar compact-summary order.
    "i": "n",
    "a": "p",
}


@cache
def _workflow_names() -> frozenset[str]:
    """Return cached VCS workflow names for metadata classification."""
    from sase.workspace_provider import get_workflow_names

    return frozenset(get_workflow_names()) | _KNOWN_FALLBACK_VCS_PREFIXES


def summarize_prompt_for_list(text: str) -> PromptListSummary:
    """Return compact metadata and cleaned preview text for a history row."""
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(text, fenced_blocks)
    directives = _scan_known_directives(protected)
    refs = iter_xprompt_references(protected)
    workflow_names = _workflow_names()
    vcs_tag = _extract_vcs_tag(text)
    project_prefix, project_ref_display = _project_columns(vcs_tag, workflow_names)
    intervals = [(directive.start, directive.end) for directive in directives]
    intervals.extend((ref.start, ref.end) for ref in refs)

    return PromptListSummary(
        project_prefix=project_prefix,
        project_ref_display=project_ref_display,
        xprompts=_embedded_xprompt_chips(refs, workflow_names),
        directive_token=_directive_summary_token(directives),
        clean_preview=_clean_preview_from_protected(
            protected,
            fenced_blocks,
            intervals,
        ),
    )


def summarize_prompt_for_preview(text: str) -> PromptPreviewSummary:
    """Return detailed metadata for the highlighted prompt preview."""
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(text, fenced_blocks)
    workflow_names = _workflow_names()
    refs = iter_xprompt_references(protected)
    directives = _scan_known_directives(protected)

    # Exercise the full directive extractor for preview-only metadata so any
    # current parser behavior stays represented here. Historical prompts can
    # contain stale or duplicate directives, so display falls back to the
    # side-effect-free token scan when extraction rejects them.
    try:
        extract_prompt_directives(text)
    except XPromptError:
        pass

    return PromptPreviewSummary(
        vcs_tag=_extract_vcs_tag(text),
        xprompts=_embedded_xprompt_refs(refs, workflow_names),
        directives=_preview_directive_tokens(directives),
    )


def clean_prompt_preview(text: str) -> str:
    """Strip prompt control tokens and return a collapsed first-line preview."""
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(text, fenced_blocks)
    directives = _scan_known_directives(protected)
    refs = iter_xprompt_references(protected)
    intervals = [(directive.start, directive.end) for directive in directives]
    intervals.extend((ref.start, ref.end) for ref in refs)
    return _clean_preview_from_protected(protected, fenced_blocks, intervals)


def _scan_known_directives(protected: str) -> tuple[_DirectiveToken, ...]:
    """Scan already fence-protected text for known directives."""
    if "%" not in protected:
        return ()

    tokens: list[_DirectiveToken] = []
    for match in _DIRECTIVE_RE.finditer(protected):
        raw_name = match.group(1)
        name = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if name not in _KNOWN_DIRECTIVES and name not in _DEPRECATED_DIRECTIVES:
            continue

        end = match.end()
        if match.group(2) is not None:
            paren_end = find_matching_paren_for_args(protected, match.end() - 1)
            if paren_end is not None:
                end = paren_end + 1

        tokens.append(
            _DirectiveToken(
                name=name,
                start=match.start(),
                end=end,
                suffix=protected[match.end(1) : end],
            )
        )
    return tuple(tokens)


def _directive_summary_token(directives: tuple[_DirectiveToken, ...]) -> str:
    """Collapse directives into a compact list-row token."""
    names = {directive.name for directive in directives}
    aliases = sorted(
        (
            alias
            for name in names
            if (alias := _ALIAS_BY_DIRECTIVE.get(name)) is not None
        ),
        key=lambda alias: _DIRECTIVE_SUMMARY_ALIAS_SORT_KEYS.get(alias, alias),
    )
    full_names = sorted(name for name in names if name not in _ALIAS_BY_DIRECTIVE)

    tokens: list[str] = []
    if aliases:
        tokens.append(f"%{''.join(aliases)}")
    tokens.extend(f"%{name}" for name in full_names)
    return " ".join(tokens)


def _preview_directive_tokens(
    directives: tuple[_DirectiveToken, ...],
) -> tuple[str, ...]:
    """Return canonical directive tokens, including argument syntax."""
    return tuple(f"%{directive.name}{directive.suffix}" for directive in directives)


def _embedded_xprompt_chips(
    refs: list[XPromptReference],
    workflow_names: frozenset[str],
) -> tuple[str, ...]:
    """Return deduplicated xprompt chips without arguments."""
    chips: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if _is_vcs_reference(ref, workflow_names):
            continue
        chip = f"{ref.marker.value}{ref.name}"
        if chip in seen:
            continue
        seen.add(chip)
        chips.append(chip)
    return tuple(chips)


def _embedded_xprompt_refs(
    refs: list[XPromptReference],
    workflow_names: frozenset[str],
) -> tuple[str, ...]:
    """Return deduplicated xprompt references with arguments preserved."""
    values: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if _is_vcs_reference(ref, workflow_names):
            continue
        value = ref.raw.strip()
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return tuple(values)


def _is_vcs_reference(
    ref: XPromptReference,
    workflow_names: frozenset[str],
) -> bool:
    """Return True when an xprompt reference is actually a VCS workflow ref."""
    if ref.name in workflow_names:
        return True
    return any(ref.name.startswith(f"{workflow}_") for workflow in workflow_names)


def _project_columns(
    vcs_tag: str | None,
    workflow_names: frozenset[str],
) -> tuple[str, str]:
    """Return the list-row project prefix and basename display ref."""
    if not vcs_tag:
        return "", ""

    workflow = _workflow_from_vcs_tag(vcs_tag, workflow_names)
    if workflow is None:
        return "", ""

    project = extract_project_from_vcs_tag(vcs_tag) or _underscore_ref_from_vcs_tag(
        vcs_tag,
        workflow,
    )
    if project:
        return f"{workflow}:", _basename_ref(project)
    return workflow, ""


def _extract_vcs_tag(text: str) -> str | None:
    """Extract a leading VCS tag, including known fallback VCS prefixes."""
    return extract_vcs_workflow_tag(text) or _extract_fallback_vcs_tag(text)


def _extract_fallback_vcs_tag(text: str) -> str | None:
    """Extract leading generic VCS tags like ``#gh:sase`` without a provider."""
    directive_match = _DIRECTIVE_PREFIX_RE.match(text)
    stripped = text[directive_match.end() :] if directive_match else text
    match = _GENERIC_PROJECT_VCS_REF_PATTERN.match(stripped)
    if match is None or match.group("workflow") not in _KNOWN_FALLBACK_VCS_PREFIXES:
        return None

    end = match.end()
    if end < len(stripped) and stripped[end].isspace():
        end += 1
    return stripped[:end]


def _workflow_from_vcs_tag(
    vcs_tag: str,
    workflow_names: frozenset[str],
) -> str | None:
    """Extract the workflow name from a VCS tag."""
    body = vcs_tag.strip()[1:]
    for workflow in sorted(workflow_names, key=len, reverse=True):
        if body == workflow or body.startswith(workflow):
            return workflow
    return None


def _underscore_ref_from_vcs_tag(vcs_tag: str, workflow: str) -> str | None:
    """Extract legacy underscore-style refs like ``#gh_sase``."""
    body = vcs_tag.strip()[1:]
    suffix = body[len(workflow) :]
    for hitl_suffix in ("!!", "??"):
        if suffix.startswith(hitl_suffix):
            suffix = suffix[len(hitl_suffix) :]
            break
    if suffix.startswith("_") and len(suffix) > 1:
        return suffix[1:]
    return None


def _basename_ref(ref: str) -> str:
    """Return the basename part of a project ref."""
    stripped = ref.rstrip("/")
    return stripped.rsplit("/", 1)[-1] if "/" in stripped else stripped


def _clean_preview_from_protected(
    protected: str,
    fenced_blocks: list[str],
    intervals: list[tuple[int, int]],
) -> str:
    """Remove protected-text spans, restore fences, and collapse the preview."""
    cleaned = protected
    for start, end in reversed(_merge_intervals(intervals)):
        cleaned = cleaned[:start] + cleaned[end:]

    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"(?m)^[ \t]+", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    restored = unprotect_fenced_blocks(cleaned, fenced_blocks).strip()
    if not restored:
        return ""
    first_line = restored.splitlines()[0]
    return " ".join(first_line.split())


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping text spans."""
    normalized = sorted((start, end) for start, end in intervals if start < end)
    if not normalized:
        return []

    merged: list[tuple[int, int]] = [normalized[0]]
    for start, end in normalized[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged
