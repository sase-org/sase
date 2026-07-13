"""Compatibility exports for xprompt parsing helpers."""

import re
from collections.abc import Mapping, Sequence

from . import _parsing_args as _args
from . import _parsing_shorthand as _shorthand
from . import _parsing_vcs_refs as _vcs_refs
from . import _parsing_vcs_tags as _vcs_tags
from ._parsing_args import (
    decode_xprompt_arg_value,
    decode_xprompt_args,
    escape_for_xprompt,
    find_matching_brace_for_args,
    find_matching_paren_for_args,
    parse_args,
    parse_workflow_reference,
    strip_hitl_suffix,
)
from ._parsing_references import (
    XPROMPT_REFERENCE_ARGUMENT_FRAGMENT,
    XPROMPT_REFERENCE_HITL_SUFFIX_FRAGMENT,
    XPROMPT_REFERENCE_LEADING_CONTEXT,
    XPROMPT_REFERENCE_MARKER_FRAGMENT,
    XPROMPT_REFERENCE_NAME_FRAGMENT,
    XPROMPT_REFERENCE_PATTERN,
    XPromptReference,
    XPromptReferenceArgKind,
    XPromptReferenceMarker,
    iter_xprompt_references,
    xprompt_reference_from_match,
)
from ._parsing_shorthand import (
    DOUBLE_COLON_SHORTHAND_PATTERN,
    SHORTHAND_PATTERN,
    find_double_colon_text_end,
    find_shorthand_text_end,
    preprocess_shorthand_syntax,
)
from ._parsing_vcs_tags import (
    DEFAULT_VCS_WORKFLOW_PREFIX,
    extract_project_from_vcs_tag,
    replace_ref_in_vcs_tag,
)


def _parse_named_arg(token: str) -> tuple[str | None, str]:
    """Compatibility wrapper for tests that import the old private helper."""
    return _args._parse_named_arg(token)


def _process_text_block(value: str) -> str:
    """Compatibility wrapper for tests that import the old private helper."""
    return _args._process_text_block(value)


def _format_as_text_block(text: str) -> str:
    """Compatibility wrapper for tests that import the old private helper."""
    return _shorthand._format_as_text_block(text)


def _preprocess_paren_shorthand(prompt: str, xprompt_names: set[str]) -> str:
    """Compatibility wrapper for tests that import the old private helper."""
    return _shorthand._preprocess_paren_shorthand(prompt, xprompt_names)


_VCS_UNDERSCORE_NORMALIZER = _vcs_refs._VCS_UNDERSCORE_NORMALIZER
_LAUNCH_XPROMPT_AT_REF_RE = _vcs_refs._LAUNCH_XPROMPT_AT_REF_RE
_VCS_TAG_PATTERN = _vcs_tags._VCS_TAG_PATTERN
_VCS_TAG_EMBEDDED_PATTERN = _vcs_tags._VCS_TAG_EMBEDDED_PATTERN
_VCS_REPLACE_PATTERN = _vcs_tags._VCS_REPLACE_PATTERN
_DIRECTIVE_PREFIX_RE = _vcs_tags._DIRECTIVE_PREFIX_RE
_SEGMENT_SEPARATOR_RE = _vcs_tags._SEGMENT_SEPARATOR_RE


def _sync_vcs_ref_caches_to_impl() -> None:
    _vcs_refs._VCS_UNDERSCORE_NORMALIZER = _VCS_UNDERSCORE_NORMALIZER
    _vcs_refs._LAUNCH_XPROMPT_AT_REF_RE = _LAUNCH_XPROMPT_AT_REF_RE


def _sync_vcs_ref_caches_from_impl() -> None:
    global _LAUNCH_XPROMPT_AT_REF_RE, _VCS_UNDERSCORE_NORMALIZER  # noqa: PLW0603
    _VCS_UNDERSCORE_NORMALIZER = _vcs_refs._VCS_UNDERSCORE_NORMALIZER
    _LAUNCH_XPROMPT_AT_REF_RE = _vcs_refs._LAUNCH_XPROMPT_AT_REF_RE


def _sync_vcs_tag_caches_to_impl() -> None:
    _vcs_tags._VCS_TAG_PATTERN = _VCS_TAG_PATTERN
    _vcs_tags._VCS_TAG_EMBEDDED_PATTERN = _VCS_TAG_EMBEDDED_PATTERN
    _vcs_tags._VCS_REPLACE_PATTERN = _VCS_REPLACE_PATTERN


def _sync_vcs_tag_caches_from_impl() -> None:
    global _VCS_REPLACE_PATTERN, _VCS_TAG_EMBEDDED_PATTERN, _VCS_TAG_PATTERN  # noqa: PLW0603
    _VCS_TAG_PATTERN = _vcs_tags._VCS_TAG_PATTERN
    _VCS_TAG_EMBEDDED_PATTERN = _vcs_tags._VCS_TAG_EMBEDDED_PATTERN
    _VCS_REPLACE_PATTERN = _vcs_tags._VCS_REPLACE_PATTERN


def normalize_vcs_underscore_refs(prompt: str) -> str:
    """Normalize ``#gh_sase`` to ``#gh:sase`` for known VCS workflow names."""
    _sync_vcs_ref_caches_to_impl()
    result = _vcs_refs.normalize_vcs_underscore_refs(prompt)
    _sync_vcs_ref_caches_from_impl()
    return result


def _get_launch_xprompt_at_ref_pattern() -> re.Pattern[str]:
    """Return the scoped ``#workflow@ref`` launch-shorthand normalizer."""
    _sync_vcs_ref_caches_to_impl()
    pattern = _vcs_refs._get_launch_xprompt_at_ref_pattern()
    _sync_vcs_ref_caches_from_impl()
    return pattern


def normalize_launch_xprompt_at_refs(prompt: str) -> str:
    """Normalize mobile/Telegram ``#workflow@ref`` launch shorthand."""
    _sync_vcs_ref_caches_to_impl()
    result = _vcs_refs.normalize_launch_xprompt_at_refs(prompt)
    _sync_vcs_ref_caches_from_impl()
    return result


def resolve_known_project_ref(
    ref: str, known_projects: Mapping[str, object]
) -> str | None:
    """Return the registered project name for *ref* or ``None``."""
    return _vcs_refs.resolve_known_project_ref(ref, known_projects)


def extract_known_project_vcs_ref(
    prompt: str,
    include_states: Sequence[str] | str = ("enabled",),
) -> tuple[str, str] | None:
    """Return ``(workflow_type, ref)`` for a generic known-project VCS ref."""
    _sync_vcs_ref_caches_to_impl()
    result = _vcs_refs.extract_known_project_vcs_ref(prompt, include_states)
    _sync_vcs_ref_caches_from_impl()
    return result


def iter_known_project_vcs_refs(
    prompt: str,
    known_projects: Mapping[str, object],
) -> list[tuple[str, str]]:
    """Return all generic VCS refs that resolve to known projects."""
    _sync_vcs_ref_caches_to_impl()
    result = _vcs_refs.iter_known_project_vcs_refs(prompt, known_projects)
    _sync_vcs_ref_caches_from_impl()
    return result


def strip_known_project_vcs_refs(prompt: str) -> str:
    """Remove generic VCS refs that point at known projects."""
    return _vcs_refs.strip_known_project_vcs_refs(prompt)


def _get_vcs_tag_pattern() -> re.Pattern[str]:
    """Lazily initialize and return the VCS tag pattern."""
    _sync_vcs_tag_caches_to_impl()
    pattern = _vcs_tags._get_vcs_tag_pattern()
    _sync_vcs_tag_caches_from_impl()
    return pattern


def _get_embedded_vcs_tag_pattern() -> re.Pattern[str]:
    """Lazily initialize and return the embedded VCS tag pattern."""
    _sync_vcs_tag_caches_to_impl()
    pattern = _vcs_tags._get_embedded_vcs_tag_pattern()
    _sync_vcs_tag_caches_from_impl()
    return pattern


def extract_vcs_workflow_tag(prompt: str) -> str | None:
    """Extract a leading VCS workflow tag from a prompt string."""
    m = _DIRECTIVE_PREFIX_RE.match(prompt)
    stripped = prompt[m.end() :] if m else prompt

    match = _get_vcs_tag_pattern().match(stripped)
    if match:
        return match.group(0)
    return None


def find_vcs_workflow_tag(prompt: str) -> str | None:
    """Find the first VCS workflow tag anywhere in *prompt*."""
    match = _get_embedded_vcs_tag_pattern().search(prompt)
    if match:
        return match.group(0)
    return None


def find_vcs_workflow_tag_span(prompt: str) -> tuple[int, int] | None:
    """Return the span of the first VCS workflow tag in *prompt*.

    Tags inside fenced code blocks are quoted content, not workflow refs,
    and are skipped.
    """
    from sase.xprompt._fenced_blocks import fenced_block_ranges

    fenced = fenced_block_ranges(prompt)
    for match in _get_embedded_vcs_tag_pattern().finditer(f"{prompt} "):
        start = match.start()
        if any(fence_start <= start < fence_end for fence_start, fence_end in fenced):
            continue
        return start, match.end() - 1
    return None


def normalize_default_vcs_workflow_segment(
    segment: str,
    *,
    default_vcs_prefix: str = DEFAULT_VCS_WORKFLOW_PREFIX,
) -> str:
    """Prefix *segment* with the default workspace workflow when none is present."""
    _sync_vcs_ref_caches_to_impl()
    result = _vcs_tags.normalize_default_vcs_workflow_segment(
        segment,
        default_vcs_prefix=default_vcs_prefix,
    )
    _sync_vcs_ref_caches_from_impl()
    return result


def find_vcs_workflow_tag_prepend_offset(prompt: str) -> int:
    """Return where a leading VCS workflow tag should be inserted."""
    return _vcs_tags.find_vcs_workflow_tag_prepend_offset(prompt)


def inherit_vcs_workflow_tag(prompt: str, inherited_vcs_tag: str | None) -> str:
    """Apply an inherited workspace workflow tag to each untagged prompt segment."""
    _sync_vcs_ref_caches_to_impl()
    result = _vcs_tags.inherit_vcs_workflow_tag(prompt, inherited_vcs_tag)
    _sync_vcs_ref_caches_from_impl()
    return result


def normalize_default_vcs_workflow(prompt: str) -> str:
    """Normalize bare prompt segments to the default workspace workflow."""
    _sync_vcs_ref_caches_to_impl()
    result = _vcs_tags.normalize_default_vcs_workflow(prompt)
    _sync_vcs_ref_caches_from_impl()
    return result


def strip_vcs_workflow_tag(prompt: str) -> str:
    """Strip a leading VCS workflow tag from a prompt string."""
    return _get_vcs_tag_pattern().sub("", prompt)


def _get_vcs_replace_pattern() -> re.Pattern[str]:
    """Build a regex matching VCS workflow tags at the start of any line."""
    _sync_vcs_tag_caches_to_impl()
    pattern = _vcs_tags._get_vcs_replace_pattern()
    _sync_vcs_tag_caches_from_impl()
    return pattern


def replace_vcs_workflow_tags(prompt: str, new_vcs_prefix: str) -> str:
    """Replace all VCS workflow tags in *prompt* with *new_vcs_prefix*."""
    pattern = _get_vcs_replace_pattern()
    result, count = pattern.subn(lambda m: f"{m.group(1)}{new_vcs_prefix} ", prompt)
    if count == 0:
        return f"{new_vcs_prefix} {prompt}"
    return result


__all__ = [
    "DEFAULT_VCS_WORKFLOW_PREFIX",
    "DOUBLE_COLON_SHORTHAND_PATTERN",
    "SHORTHAND_PATTERN",
    "XPROMPT_REFERENCE_ARGUMENT_FRAGMENT",
    "XPROMPT_REFERENCE_HITL_SUFFIX_FRAGMENT",
    "XPROMPT_REFERENCE_LEADING_CONTEXT",
    "XPROMPT_REFERENCE_MARKER_FRAGMENT",
    "XPROMPT_REFERENCE_NAME_FRAGMENT",
    "XPROMPT_REFERENCE_PATTERN",
    "XPromptReference",
    "XPromptReferenceArgKind",
    "XPromptReferenceMarker",
    "_format_as_text_block",
    "_parse_named_arg",
    "_preprocess_paren_shorthand",
    "_process_text_block",
    "decode_xprompt_arg_value",
    "decode_xprompt_args",
    "escape_for_xprompt",
    "extract_project_from_vcs_tag",
    "extract_known_project_vcs_ref",
    "extract_vcs_workflow_tag",
    "find_double_colon_text_end",
    "find_matching_brace_for_args",
    "find_matching_paren_for_args",
    "find_shorthand_text_end",
    "find_vcs_workflow_tag",
    "find_vcs_workflow_tag_prepend_offset",
    "find_vcs_workflow_tag_span",
    "inherit_vcs_workflow_tag",
    "iter_known_project_vcs_refs",
    "iter_xprompt_references",
    "normalize_launch_xprompt_at_refs",
    "normalize_vcs_underscore_refs",
    "normalize_default_vcs_workflow",
    "normalize_default_vcs_workflow_segment",
    "parse_args",
    "parse_workflow_reference",
    "preprocess_shorthand_syntax",
    "replace_ref_in_vcs_tag",
    "replace_vcs_workflow_tags",
    "resolve_known_project_ref",
    "strip_known_project_vcs_refs",
    "strip_hitl_suffix",
    "strip_vcs_workflow_tag",
    "xprompt_reference_from_match",
]
