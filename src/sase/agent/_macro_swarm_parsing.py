"""Reference and directive parsing helpers for macro swarm expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.macro._disabled_regions import protect_disabled_regions
from sase.macro._fenced_blocks import protect_fenced_blocks
from sase.macro._literal_zones import literal_zone_ranges
from sase.macro._parsing import (
    MacroReference,
    MacroReferenceArgKind,
    MacroReferenceMarker,
    extract_known_project_vcs_ref,
    find_matching_paren_for_args,
    iter_macro_references,
    normalize_vcs_underscore_refs,
)
from sase.macro._parsing_args import decode_macro_args
from sase.macro.models import Macro

_DIRECTIVE_LINE_RE = re.compile(r"^%[a-zA-Z][a-zA-Z0-9_]*(?:[:(].*)?\s*$")


@dataclass
class _MacroCall:
    """A parsed top-level macro reference in a segment."""

    name: str
    marker: MacroReferenceMarker
    raw: str
    positional_args: list[str] = field(default_factory=list)
    named_args: dict[str, str] = field(default_factory=dict)
    leading_directives: list[str] = field(default_factory=list)
    leading_directive_prefix: str = ""
    leading_vcs_ref_text: str | None = None


@dataclass(frozen=True)
class _LeadingDirectiveSplit:
    """Leading launch directives plus the remaining prompt body."""

    directives: list[str]
    prefix: str
    body: str


def _directive_tokens(text: str) -> list[str]:
    """Return parser-style directive tokens from a leading directive prefix."""
    return re.findall(r"%\S+", text)


def _directive_run_end(segment: str, pos: int) -> int | None:
    """Return the offset just past the ``%directive`` run starting at *pos*.

    Deliberately byte-identical to ``_DIRECTIVE_PREFIX_RE`` except for how
    parenthesized argument lists are delimited: they are resolved with
    :func:`find_matching_paren_for_args` instead of a paren-naive regex, so a
    directive whose argument list spans multiple physical lines (e.g. a
    wrapped ``%clan(...)``) is still consumed as a single run instead of
    being split mid-argument-list.
    """
    token_match = re.match(r"%[^\s(]+", segment[pos:])
    if token_match is None:
        return None
    end = pos + token_match.end()

    if end < len(segment) and segment[end] == "(":
        paren_end = find_matching_paren_for_args(segment, end)
        if paren_end is None:
            return None
        end = paren_end + 1

    ws_match = re.match(r"[^\S\n]*\n|[^\S\n]+", segment[end:])
    if ws_match is None:
        return None
    end += ws_match.end()

    indent_match = re.match(r"[ \t]*", segment[end:])
    assert indent_match is not None
    return end + indent_match.end()


def _split_leading_directive_prefix(segment: str) -> _LeadingDirectiveSplit:
    """Split leading whitespace/directives from the prompt body.

    This mirrors the parser's same-line directive prefix handling while also
    keeping support for directive-only lines.  The returned prefix preserves
    original spacing so generated segments can insert VCS refs after launch
    directives without moving those directives behind the workspace tag.
    """
    leading_ws_match = re.match(r"\s*", segment)
    assert leading_ws_match is not None
    prefix = leading_ws_match.group(0)
    pos = leading_ws_match.end()
    directives: list[str] = []

    while pos < len(segment):
        directive_end = _directive_run_end(segment, pos)
        if directive_end is not None:
            directive_prefix = segment[pos:directive_end]
            prefix += directive_prefix
            directives.extend(_directive_tokens(directive_prefix))
            pos = directive_end
            if segment[pos:].lstrip(" \t").startswith("%"):
                continue
            break

        line_end = segment.find("\n", pos)
        line = segment[pos:] if line_end == -1 else segment[pos : line_end + 1]
        stripped = line.strip()
        if stripped and _DIRECTIVE_LINE_RE.match(stripped):
            open_paren = stripped.find("(")
            if (
                open_paren == -1
                or find_matching_paren_for_args(stripped, open_paren) is not None
            ):
                prefix += line
                directives.append(stripped)
                pos += len(line)
                continue

        break

    return _LeadingDirectiveSplit(
        directives=directives, prefix=prefix, body=segment[pos:]
    )


def _split_leading_directives(segment: str) -> tuple[list[str], str]:
    """Split *segment* into (leading directive lines, remaining body).

    Supports both directive-only lines and parser-style same-line directive
    prefixes.  The returned body keeps legacy stripped semantics for callers
    that use it for reference detection.
    """
    split = _split_leading_directive_prefix(segment)
    return split.directives, split.body.strip()


def _parse_macro_reference_arguments(
    ref: MacroReference,
) -> tuple[list[str], dict[str, str]]:
    """Parse reference arguments using macro-compatible argument semantics."""
    if ref.arg_kind is MacroReferenceArgKind.NONE:
        return [], {}
    if ref.arg_kind is MacroReferenceArgKind.PLUS:
        return ["true"], {}
    if ref.arg_kind is MacroReferenceArgKind.COLON:
        colon_arg = ref.argument_source[1:]
        if colon_arg.startswith("`") and colon_arg.endswith("`"):
            return [colon_arg[1:-1]], {}
        return decode_macro_args(colon_arg.split(","), {})
    return ref.parse_arguments()


def build_macro_call(
    ref: MacroReference,
    leading_directives: list[str],
    *,
    leading_directive_prefix: str = "",
    leading_vcs_ref_text: str | None = None,
) -> _MacroCall:
    positional_args, named_args = _parse_macro_reference_arguments(ref)
    return _MacroCall(
        name=ref.name,
        marker=ref.marker,
        raw=ref.raw,
        positional_args=positional_args,
        named_args=named_args,
        leading_directives=leading_directives,
        leading_directive_prefix=leading_directive_prefix,
        leading_vcs_ref_text=leading_vcs_ref_text,
    )


def _sole_macro_reference(body: str, available: set[str]) -> MacroReference | None:
    refs = iter_macro_references(body)
    if len(refs) != 1:
        return None

    ref = refs[0]
    if ref.start != 0 or ref.end != len(body):
        return None

    return ref if ref.name in available else None


def _strip_leading_known_project_vcs_ref(body: str) -> tuple[str, str] | None:
    """Strip one leading generic known-project VCS ref from *body*."""
    known_ref = extract_known_project_vcs_ref(body)
    if known_ref is None:
        return None

    workflow_type, ref = known_ref
    normalized = normalize_vcs_underscore_refs(body)
    forms = (
        rf"#{re.escape(workflow_type)}(?:!!|\?\?)?[_:]{re.escape(ref)}(?=\s|$)",
        rf"#{re.escape(workflow_type)}(?:!!|\?\?)?\({re.escape(ref)}\)(?=\s|$)",
    )
    for form in forms:
        match = re.match(form, normalized)
        if match is None:
            continue
        prefix_text = body[match.start() : match.end()].strip()
        remaining = body[match.end() :].strip()
        if remaining:
            return prefix_text, remaining
    return None


def _strip_leading_vcs_ref(body: str) -> tuple[str, str] | None:
    """Return ``(vcs_ref_text, remaining_body)`` for one leading VCS ref."""
    if not body.startswith("#"):
        return None

    from sase.workspace_provider import get_ref_patterns

    normalized = normalize_vcs_underscore_refs(body)
    for pattern in get_ref_patterns().values():
        match = pattern.match(normalized)
        if match is None:
            continue
        prefix_text = body[match.start() : match.end()].strip()
        remaining = body[match.end() :].strip()
        if remaining:
            return prefix_text, remaining

    return _strip_leading_known_project_vcs_ref(body)


def _protected_prompt_for_ref_detection(prompt: str) -> str:
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)
    disabled_regions: list[str] = []
    return protect_disabled_regions(protected, disabled_regions)


def _segment_has_vcs_ref(segment: str) -> bool:
    """Return whether *segment* contains a real VCS workflow ref."""
    if "#" not in segment:
        return False

    from sase.workspace_provider import get_ref_patterns

    protected = _protected_prompt_for_ref_detection(segment)
    normalized = normalize_vcs_underscore_refs(protected)
    for pattern in get_ref_patterns().values():
        if pattern.search(normalized) is not None:
            return True

    return extract_known_project_vcs_ref(protected) is not None


def prepend_inherited_vcs_ref(
    sub_segments: list[str], vcs_ref_text: str | None
) -> list[str]:
    if vcs_ref_text is None:
        return sub_segments
    return [
        segment
        if _segment_has_vcs_ref(segment)
        else _prefix_segment_vcs_ref(segment, vcs_ref_text)
        for segment in sub_segments
    ]


def _prefix_segment_vcs_ref(segment: str, vcs_ref_text: str) -> str:
    """Prefix *segment* with *vcs_ref_text* after any generated directives."""
    split = _split_leading_directive_prefix(segment)
    if not split.body:
        return f"{split.prefix}{vcs_ref_text}"
    return f"{split.prefix}{vcs_ref_text} {split.body}"


def leading_vcs_ref_text(segment: str) -> str | None:
    """Return the leading VCS ref inherited by embedded generated prompts."""
    _directives, body = _split_leading_directives(segment)
    if not body:
        return None
    stripped = _strip_leading_vcs_ref(body)
    return stripped[0] if stripped is not None else None


def extract_top_level_macro_reference(
    segment: str, available: set[str]
) -> _MacroCall | None:
    """Return the call info if *segment* is a sole top-level macro reference.

    A segment qualifies if, after stripping leading blank/directive lines and
    trailing whitespace, what remains is exactly one ``#name`` or ``#!name``
    (optionally with args) and nothing else, and ``name`` is in *available*.
    """
    directive_split = _split_leading_directive_prefix(segment)
    directives, body = directive_split.directives, directive_split.body.strip()
    if not body:
        return None

    ref = _sole_macro_reference(body, available)
    if ref is not None:
        return build_macro_call(
            ref,
            directives,
            leading_directive_prefix=directive_split.prefix,
        )

    vcs_prefixed = _strip_leading_vcs_ref(body)
    if vcs_prefixed is None:
        return None

    leading_vcs_ref_text, remaining_body = vcs_prefixed
    ref = _sole_macro_reference(remaining_body, available)
    if ref is None:
        return None

    return build_macro_call(
        ref,
        directives,
        leading_directive_prefix=directive_split.prefix,
        leading_vcs_ref_text=leading_vcs_ref_text,
    )


def _span_overlaps_ranges(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(
        start < range_end and end > range_start for range_start, range_end in ranges
    )


def _real_macro_references(segment: str) -> list[MacroReference]:
    """Return lexical macro references in *segment*, excluding disabled examples."""
    ignored_ranges = literal_zone_ranges(segment)
    return [
        ref
        for ref in iter_macro_references(segment)
        if not _span_overlaps_ranges(ref.start, ref.end, ignored_ranges)
    ]


def macro_swarm_references(segment: str, swarm_names: set[str]) -> list[MacroReference]:
    if not swarm_names:
        return []
    return [ref for ref in _real_macro_references(segment) if ref.name in swarm_names]


def first_invalid_standalone_macro_reference(
    segment: str,
    catalog: dict[str, Macro],
    swarm_names: set[str],
) -> MacroReference | None:
    """Return the first ``#!`` reference to an ordinary embeddable macro."""
    for ref in _real_macro_references(segment):
        if (
            ref.is_standalone_marker
            and ref.name in catalog
            and ref.name not in swarm_names
        ):
            return ref
    return None


def invalid_explicit_macro_message(ref: MacroReference) -> str:
    return (
        "Only standalone workflows use `#!`; "
        f"`{ref.raw}` resolves to an embeddable xprompt. "
        f"Use `#{ref.name}` for inline expansion."
    )
