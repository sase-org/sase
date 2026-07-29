"""Xprompt swarm expansion at dispatch time.

When a user-prompt segment references an xprompt whose body contains ``---``
segment separators, expand the xprompt body once (substituting the call-site's
arguments) and then split the substituted body on ``---``.

A sole reference becomes one prompt per body segment.  A single embedded
reference uses the first body segment as the embeddable prompt part and appends
the remaining body segments as follow-up agent prompts.  Multiple embedded
references fan out independently in document order.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import count

from sase.agent.names import iter_agent_name_key_markers
from sase.agent.multi_prompt import split_segments_protecting_fences
from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from sase.xprompt._fenced_blocks import (
    protect_fenced_blocks,
    protect_fenced_blocks_only,
    unprotect_fenced_blocks,
)
from sase.xprompt._literal_zones import literal_zone_ranges
from sase.xprompt._parsing import (
    _DIRECTIVE_PREFIX_RE,
    extract_known_project_vcs_ref,
    XPromptReference,
    XPromptReferenceArgKind,
    XPromptReferenceMarker,
    iter_xprompt_references,
    normalize_vcs_underscore_refs,
)
from sase.xprompt._parsing_args import decode_xprompt_args
from sase.xprompt.loader import get_all_xprompts
from sase.xprompt.models import XPrompt
from sase.xprompt.processor import expand_single_xprompt
from sase.xprompt.segment_separators import xprompt_has_segment_separators

_DIRECTIVE_LINE_RE = re.compile(r"^%[a-zA-Z][a-zA-Z0-9_]*(?:[:(].*)?\s*$")


class _XpromptSwarmError(ValueError):
    """Base class for xprompt swarm expansion errors."""


class _XpromptSwarmUsageError(_XpromptSwarmError):
    """Raised when an xprompt swarm reference is ambiguous or invalid."""


class _XpromptSwarmDepthError(_XpromptSwarmError):
    """Raised when recursive xprompt swarm expansion exceeds the depth cap."""


@dataclass
class _XPromptCall:
    """A parsed top-level xprompt reference in a segment."""

    name: str
    marker: XPromptReferenceMarker
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


@dataclass(frozen=True)
class _ExpandedXpromptSwarmSegment:
    """Expanded segment plus optional template-allocation group metadata."""

    prompt: str
    template_group: str | None = None


def _directive_tokens(text: str) -> list[str]:
    """Return parser-style directive tokens from a leading directive prefix."""
    return re.findall(r"%\S+", text)


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
        line_end = segment.find("\n", pos)
        if line_end == -1:
            line = segment[pos:]
        else:
            line = segment[pos : line_end + 1]

        line_indent_match = re.match(r"[ \t]*", line)
        assert line_indent_match is not None
        line_indent = line_indent_match.group(0)
        directive_match = _DIRECTIVE_PREFIX_RE.match(line[line_indent_match.end() :])
        if directive_match is not None:
            directive_prefix = line_indent + directive_match.group(0)
            prefix += directive_prefix
            directives.extend(_directive_tokens(directive_prefix))
            pos += len(directive_prefix)
            if segment[pos:].lstrip(" \t").startswith("%"):
                continue
            break

        stripped = line.strip()
        if stripped and _DIRECTIVE_LINE_RE.match(stripped):
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


def _parse_xprompt_reference_arguments(
    ref: XPromptReference,
) -> tuple[list[str], dict[str, str]]:
    """Parse reference arguments using xprompt-compatible argument semantics."""
    if ref.arg_kind is XPromptReferenceArgKind.NONE:
        return [], {}
    if ref.arg_kind is XPromptReferenceArgKind.PLUS:
        return ["true"], {}
    if ref.arg_kind is XPromptReferenceArgKind.COLON:
        colon_arg = ref.argument_source[1:]
        if colon_arg.startswith("`") and colon_arg.endswith("`"):
            return decode_xprompt_args([colon_arg[1:-1]], {})
        return decode_xprompt_args(colon_arg.split(","), {})
    return ref.parse_arguments()


def _build_xprompt_call(
    ref: XPromptReference,
    leading_directives: list[str],
    *,
    leading_directive_prefix: str = "",
    leading_vcs_ref_text: str | None = None,
) -> _XPromptCall:
    positional_args, named_args = _parse_xprompt_reference_arguments(ref)
    return _XPromptCall(
        name=ref.name,
        marker=ref.marker,
        raw=ref.raw,
        positional_args=positional_args,
        named_args=named_args,
        leading_directives=leading_directives,
        leading_directive_prefix=leading_directive_prefix,
        leading_vcs_ref_text=leading_vcs_ref_text,
    )


def _sole_xprompt_reference(body: str, available: set[str]) -> XPromptReference | None:
    refs = iter_xprompt_references(body)
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


def _prepend_inherited_vcs_ref(
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


def _leading_vcs_ref_text(segment: str) -> str | None:
    """Return the leading VCS ref inherited by embedded generated prompts."""
    _directives, body = _split_leading_directives(segment)
    if not body:
        return None
    stripped = _strip_leading_vcs_ref(body)
    return stripped[0] if stripped is not None else None


def _extract_top_level_xprompt_reference(
    segment: str, available: set[str]
) -> _XPromptCall | None:
    """Return the call info if *segment* is a sole top-level xprompt reference.

    A segment qualifies if, after stripping leading blank/directive lines and
    trailing whitespace, what remains is exactly one ``#name`` or ``#!name``
    (optionally with args) and nothing else, and ``name`` is in *available*.
    """
    directive_split = _split_leading_directive_prefix(segment)
    directives, body = directive_split.directives, directive_split.body.strip()
    if not body:
        return None

    ref = _sole_xprompt_reference(body, available)
    if ref is not None:
        return _build_xprompt_call(
            ref,
            directives,
            leading_directive_prefix=directive_split.prefix,
        )

    vcs_prefixed = _strip_leading_vcs_ref(body)
    if vcs_prefixed is None:
        return None

    leading_vcs_ref_text, remaining_body = vcs_prefixed
    ref = _sole_xprompt_reference(remaining_body, available)
    if ref is None:
        return None

    return _build_xprompt_call(
        ref,
        directives,
        leading_directive_prefix=directive_split.prefix,
        leading_vcs_ref_text=leading_vcs_ref_text,
    )


def _span_overlaps_ranges(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(
        start < range_end and end > range_start for range_start, range_end in ranges
    )


def _real_xprompt_references(segment: str) -> list[XPromptReference]:
    """Return lexical xprompt references in *segment*, excluding disabled examples."""
    ignored_ranges = literal_zone_ranges(segment)
    return [
        ref
        for ref in iter_xprompt_references(segment)
        if not _span_overlaps_ranges(ref.start, ref.end, ignored_ranges)
    ]


def _xprompt_swarm_references(
    segment: str, swarm_names: set[str]
) -> list[XPromptReference]:
    if not swarm_names:
        return []
    return [ref for ref in _real_xprompt_references(segment) if ref.name in swarm_names]


def _first_invalid_standalone_xprompt_reference(
    segment: str,
    catalog: dict[str, XPrompt],
    swarm_names: set[str],
) -> XPromptReference | None:
    """Return the first ``#!`` reference to an ordinary embeddable xprompt."""
    for ref in _real_xprompt_references(segment):
        if (
            ref.is_standalone_marker
            and ref.name in catalog
            and ref.name not in swarm_names
        ):
            return ref
    return None


def _invalid_explicit_xprompt_message(ref: XPromptReference) -> str:
    return (
        "Only standalone workflows use `#!`; "
        f"`{ref.raw}` resolves to an embeddable xprompt. "
        f"Use `#{ref.name}` for inline expansion."
    )


def _render_xprompt_swarm(
    xprompt: XPrompt,
    positional_args: list[str],
    named_args: dict[str, str],
    qualification_counter: Iterator[int],
) -> list[str]:
    substituted = expand_single_xprompt(
        xprompt,
        positional_args,
        named_args,
        preserve_segment_separators=True,
    )
    qualification_prefix = _next_key_qualification_prefix(
        xprompt.name, qualification_counter
    )
    return [
        _qualify_agent_name_key_markers(segment, qualification_prefix)
        for segment in split_segments_protecting_fences(substituted)
    ]


def _next_key_qualification_prefix(
    xprompt_name: str, qualification_counter: Iterator[int]
) -> str:
    from sase.core.time import generate_timestamp

    name = re.sub(r"[^A-Za-z0-9]+", ".", xprompt_name).strip(".") or "xprompt"
    timestamp = generate_timestamp().replace("_", ".")
    return f"{name}.{timestamp}.{next(qualification_counter)}"


def _qualify_agent_name_key_markers(text: str, prefix: str) -> str:
    """Namespace unqualified keyed markers for one xprompt invocation."""
    if "{@" not in text:
        return text

    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks_only(text, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    markers = [
        marker
        for marker in iter_agent_name_key_markers(protected)
        if marker.braced and marker.id is not None and not marker.qualified
    ]
    for marker in reversed(markers):
        start = _character_index(protected, marker.start)
        end = _character_index(protected, marker.end)
        protected = protected[:start] + f"{{@{prefix}.{marker.id}!}}" + protected[end:]

    protected = unprotect_disabled_regions(protected, disabled_regions)
    return unprotect_fenced_blocks(protected, fenced_blocks)


def _character_index(text: str, byte_offset: int) -> int:
    """Translate a Rust scanner byte offset into a Python string index."""
    return len(text.encode("utf-8")[:byte_offset].decode("utf-8"))


def _expand_embedded_xprompt_swarm_reference(
    segment: str,
    ref: XPromptReference,
    catalog: dict[str, XPrompt],
    local_xprompts: dict[str, XPrompt] | None,
    max_depth: int,
    template_group: str | None,
    group_counter: Iterator[int],
    qualification_counter: Iterator[int],
) -> list[_ExpandedXpromptSwarmSegment]:
    if max_depth <= 0:
        raise _XpromptSwarmDepthError(
            f"xprompt swarm expansion exceeded max depth at "
            f"#{ref.name} (possible self-reference)"
        )

    call = _build_xprompt_call(ref, [])
    group = template_group or _next_template_group(call.name, group_counter)
    sub_segments = _render_xprompt_swarm(
        catalog[call.name],
        call.positional_args,
        call.named_args,
        qualification_counter,
    )
    if not sub_segments:
        reconstructed = segment[: ref.start] + segment[ref.end :]
        return (
            [_ExpandedXpromptSwarmSegment(reconstructed, group)]
            if reconstructed.strip()
            else []
        )

    first = segment[: ref.start] + sub_segments[0] + segment[ref.end :]
    follow_ups = _prepend_inherited_vcs_ref(
        sub_segments[1:], _leading_vcs_ref_text(segment)
    )
    return _expand_xprompt_swarms_with_metadata(
        [first, *follow_ups],
        local_xprompts=local_xprompts,
        max_depth=max_depth - 1,
        template_group=group,
        group_counter=group_counter,
        qualification_counter=qualification_counter,
    )


def _expand_multiple_embedded_xprompt_swarm_references(
    segment: str,
    refs: list[XPromptReference],
    catalog: dict[str, XPrompt],
    local_xprompts: dict[str, XPrompt] | None,
    max_depth: int,
    strict_segment_check: bool,
    group_counter: Iterator[int],
    qualification_counter: Iterator[int],
) -> list[_ExpandedXpromptSwarmSegment]:
    """Expand multiple embedded xprompt swarm refs in document order.

    The leading prose before the first reference attaches to the first generated
    segment only.  Text between references and after the last reference is
    intentionally discarded.
    """
    if max_depth <= 0:
        raise _XpromptSwarmDepthError(
            f"xprompt swarm expansion exceeded max depth at "
            f"#{refs[0].name} (possible self-reference)"
        )

    leading_prose = segment[: refs[0].start]
    inherited_vcs_ref = _leading_vcs_ref_text(segment)
    expanded: list[_ExpandedXpromptSwarmSegment] = []
    for index, ref in enumerate(refs):
        call = _build_xprompt_call(ref, [])
        group = _next_template_group(call.name, group_counter)
        sub_segments = _render_xprompt_swarm(
            catalog[call.name],
            call.positional_args,
            call.named_args,
            qualification_counter,
        )
        if not sub_segments:
            continue
        if index == 0:
            sub_segments[0] = f"{leading_prose}{sub_segments[0]}"
            inherited_tail = _prepend_inherited_vcs_ref(
                sub_segments[1:], inherited_vcs_ref
            )
            sub_segments = [sub_segments[0], *inherited_tail]
        else:
            sub_segments = _prepend_inherited_vcs_ref(sub_segments, inherited_vcs_ref)
        expanded.extend(
            _expand_xprompt_swarms_with_metadata(
                sub_segments,
                local_xprompts=local_xprompts,
                max_depth=max_depth - 1,
                strict_segment_check=strict_segment_check,
                template_group=group,
                group_counter=group_counter,
                qualification_counter=qualification_counter,
            )
        )
    return expanded


def expand_xprompt_swarms_with_metadata(
    segments: list[str],
    local_xprompts: dict[str, XPrompt] | None = None,
    *,
    max_depth: int = 8,
    _strict_segment_check: bool = True,
    group_counter: Iterator[int] | None = None,
    qualification_counter: Iterator[int] | None = None,
) -> list[_ExpandedXpromptSwarmSegment]:
    """Expand any xprompt swarm references in *segments* into sub-segments.

    For each segment:
        * If the segment is a sole top-level reference (per
          :func:`extract_top_level_xprompt_reference`) to an xprompt whose body
          contains ``---`` separators, substitute the call's args into the
          xprompt body and split the result on ``---``.  The call site's
          leading directives (e.g. ``%id:custom``) attach to the *first*
          sub-segment only.
        * If the segment contains multiple xprompt swarm references, each
          reference fans out in document order.  Leading prose attaches to the
          first generated segment; inter-reference and trailing prose is
          discarded.
        * Otherwise, the segment is passed through unchanged.

    Recursion: each sub-segment is fed back through this function with
    ``max_depth - 1`` so an xprompt swarm can compose another xprompt swarm.
    When *max_depth* is exhausted on a still-qualifying reference,
    :class:`ValueError` is raised.

    Raises:
        _XpromptSwarmUsageError: A segment uses the standalone marker for
            an ordinary embeddable xprompt.
        ValueError: Recursive expansion exceeded *max_depth*.

    ``group_counter`` and ``qualification_counter`` let callers that expand
    segments one call at a time (e.g. per-segment ``segment_extra_env``
    launches) share independent invocation counters. Distinct invocations of
    the same xprompt then collide on neither template groups nor keyed-marker
    namespaces.
    """
    return _expand_xprompt_swarms_with_metadata(
        segments,
        local_xprompts=local_xprompts,
        max_depth=max_depth,
        strict_segment_check=_strict_segment_check,
        group_counter=group_counter if group_counter is not None else count(),
        qualification_counter=(
            qualification_counter if qualification_counter is not None else count()
        ),
    )


def _expand_xprompt_swarms_with_metadata(
    segments: list[str],
    *,
    local_xprompts: dict[str, XPrompt] | None,
    max_depth: int,
    strict_segment_check: bool = True,
    template_group: str | None = None,
    group_counter: Iterator[int],
    qualification_counter: Iterator[int],
) -> list[_ExpandedXpromptSwarmSegment]:
    # Fast path: if no segment contains '#', no xprompt reference is possible.
    if not any("#" in seg for seg in segments):
        return [_ExpandedXpromptSwarmSegment(seg, template_group) for seg in segments]

    catalog: dict[str, XPrompt] = dict(get_all_xprompts())
    if local_xprompts:
        catalog.update(local_xprompts)
    available = set(catalog.keys())

    swarm_names = {
        name for name, xp in catalog.items() if xprompt_has_segment_separators(xp)
    }

    expanded: list[_ExpandedXpromptSwarmSegment] = []
    for segment in segments:
        call = _extract_top_level_xprompt_reference(segment, available)
        if call is not None and call.name in swarm_names:
            if max_depth <= 0:
                raise _XpromptSwarmDepthError(
                    f"xprompt swarm expansion exceeded max depth at "
                    f"#{call.name} (possible self-reference)"
                )
            group = template_group or _next_template_group(call.name, group_counter)
            xp = catalog[call.name]
            sub_segments = _render_xprompt_swarm(
                xp,
                call.positional_args,
                call.named_args,
                qualification_counter,
            )
            if not sub_segments:
                # An xprompt body that had separators but produces no content
                # after substitution (e.g. all-empty segments): drop entirely.
                continue
            sub_segments = _prepend_inherited_vcs_ref(
                sub_segments, call.leading_vcs_ref_text
            )
            if call.leading_directive_prefix:
                sub_segments[0] = f"{call.leading_directive_prefix}{sub_segments[0]}"
            recursively_expanded = _expand_xprompt_swarms_with_metadata(
                sub_segments,
                local_xprompts=local_xprompts,
                max_depth=max_depth - 1,
                strict_segment_check=strict_segment_check,
                template_group=group,
                group_counter=group_counter,
                qualification_counter=qualification_counter,
            )
            expanded.extend(recursively_expanded)
        elif call is not None and call.marker is XPromptReferenceMarker.STANDALONE:
            raise _XpromptSwarmUsageError(
                _invalid_explicit_xprompt_message(
                    XPromptReference(
                        marker=call.marker,
                        name=call.name,
                        start=0,
                        end=0,
                        raw=call.raw,
                    )
                )
            )
        else:
            invalid_standalone = _first_invalid_standalone_xprompt_reference(
                segment, catalog, swarm_names
            )
            if invalid_standalone is not None:
                raise _XpromptSwarmUsageError(
                    _invalid_explicit_xprompt_message(invalid_standalone)
                )

            if strict_segment_check:
                xprompt_swarm_refs = _xprompt_swarm_references(segment, swarm_names)
                if len(xprompt_swarm_refs) == 1:
                    expanded.extend(
                        _expand_embedded_xprompt_swarm_reference(
                            segment,
                            xprompt_swarm_refs[0],
                            catalog,
                            local_xprompts,
                            max_depth,
                            template_group,
                            group_counter,
                            qualification_counter,
                        )
                    )
                    continue
                if len(xprompt_swarm_refs) > 1:
                    expanded.extend(
                        _expand_multiple_embedded_xprompt_swarm_references(
                            segment,
                            xprompt_swarm_refs,
                            catalog,
                            local_xprompts,
                            max_depth,
                            strict_segment_check,
                            group_counter,
                            qualification_counter,
                        )
                    )
                    continue
            expanded.append(_ExpandedXpromptSwarmSegment(segment, template_group))

    return expanded


def _next_template_group(name: str, group_counter: Iterator[int]) -> str:
    return f"xprompt:{name}:{next(group_counter)}"


__all__ = [
    "expand_xprompt_swarms_with_metadata",
    "_extract_top_level_xprompt_reference",
    "xprompt_has_segment_separators",
]
