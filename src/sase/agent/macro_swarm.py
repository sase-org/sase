"""Macro swarm expansion at dispatch time.

When a user-prompt segment references a macro whose body contains ``---``
segment separators, expand the macro body once (substituting the call-site's
arguments) and then split the substituted body on ``---``.

A sole reference becomes one prompt per body segment.  A single embedded
reference uses the first body segment as the embeddable prompt part and appends
the remaining body segments as follow-up agent prompts.  Multiple embedded
references fan out independently in document order.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import count

from sase.agent._macro_swarm_parsing import (
    build_macro_call,
    extract_top_level_macro_reference as _extract_top_level_macro_reference,
    first_invalid_standalone_macro_reference,
    invalid_explicit_macro_message,
    leading_vcs_ref_text,
    prepend_inherited_vcs_ref,
    macro_swarm_references,
)
from sase.agent._macro_swarm_rendering import render_macro_swarm
from sase.macro._parsing import MacroReference, MacroReferenceMarker
from sase.macro.loader import get_all_macros
from sase.macro.models import Macro
from sase.macro.segment_separators import macro_has_segment_separators


class _MacroSwarmError(ValueError):
    """Base class for macro swarm expansion errors."""


class _MacroSwarmUsageError(_MacroSwarmError):
    """Raised when a macro swarm reference is ambiguous or invalid."""


class _MacroSwarmDepthError(_MacroSwarmError):
    """Raised when recursive macro swarm expansion exceeds the depth cap."""


@dataclass(frozen=True)
class _ExpandedMacroSwarmSegment:
    """Expanded segment plus dispatch metadata."""

    prompt: str
    template_group: str | None = None
    swarm_macros: tuple[str, ...] = ()


def _expand_embedded_macro_swarm_reference(
    segment: str,
    ref: MacroReference,
    catalog: dict[str, Macro],
    local_macros: dict[str, Macro] | None,
    max_depth: int,
    template_group: str | None,
    swarm_macros: tuple[str, ...],
    group_counter: Iterator[int],
    qualification_counter: Iterator[int],
) -> list[_ExpandedMacroSwarmSegment]:
    if max_depth <= 0:
        raise _MacroSwarmDepthError(
            f"xprompt swarm expansion exceeded max depth at "
            f"#{ref.name} (possible self-reference)"
        )

    call = build_macro_call(ref, [])
    group = template_group or _next_template_group(call.name, group_counter)
    current_swarm_macros = _append_swarm_macro(swarm_macros, call.name)
    sub_segments = render_macro_swarm(
        catalog[call.name],
        call.positional_args,
        call.named_args,
        qualification_counter,
    )
    if not sub_segments:
        reconstructed = segment[: ref.start] + segment[ref.end :]
        return (
            [_ExpandedMacroSwarmSegment(reconstructed, group, current_swarm_macros)]
            if reconstructed.strip()
            else []
        )

    first = segment[: ref.start] + sub_segments[0] + segment[ref.end :]
    follow_ups = prepend_inherited_vcs_ref(
        sub_segments[1:], leading_vcs_ref_text(segment)
    )
    return _expand_macro_swarms_with_metadata(
        [first, *follow_ups],
        local_macros=local_macros,
        max_depth=max_depth - 1,
        template_group=group,
        swarm_macros=current_swarm_macros,
        group_counter=group_counter,
        qualification_counter=qualification_counter,
    )


def _expand_multiple_embedded_macro_swarm_references(
    segment: str,
    refs: list[MacroReference],
    catalog: dict[str, Macro],
    local_macros: dict[str, Macro] | None,
    max_depth: int,
    strict_segment_check: bool,
    swarm_macros: tuple[str, ...],
    group_counter: Iterator[int],
    qualification_counter: Iterator[int],
) -> list[_ExpandedMacroSwarmSegment]:
    """Expand multiple embedded macro swarm refs in document order.

    The leading prose before the first reference attaches to the first generated
    segment only.  Text between references and after the last reference is
    intentionally discarded.
    """
    if max_depth <= 0:
        raise _MacroSwarmDepthError(
            f"xprompt swarm expansion exceeded max depth at "
            f"#{refs[0].name} (possible self-reference)"
        )

    leading_prose = segment[: refs[0].start]
    inherited_vcs_ref = leading_vcs_ref_text(segment)
    expanded: list[_ExpandedMacroSwarmSegment] = []
    for index, ref in enumerate(refs):
        call = build_macro_call(ref, [])
        group = _next_template_group(call.name, group_counter)
        current_swarm_macros = _append_swarm_macro(swarm_macros, call.name)
        sub_segments = render_macro_swarm(
            catalog[call.name],
            call.positional_args,
            call.named_args,
            qualification_counter,
        )
        if not sub_segments:
            continue
        if index == 0:
            sub_segments[0] = f"{leading_prose}{sub_segments[0]}"
            inherited_tail = prepend_inherited_vcs_ref(
                sub_segments[1:], inherited_vcs_ref
            )
            sub_segments = [sub_segments[0], *inherited_tail]
        else:
            sub_segments = prepend_inherited_vcs_ref(sub_segments, inherited_vcs_ref)
        expanded.extend(
            _expand_macro_swarms_with_metadata(
                sub_segments,
                local_macros=local_macros,
                max_depth=max_depth - 1,
                strict_segment_check=strict_segment_check,
                template_group=group,
                swarm_macros=current_swarm_macros,
                group_counter=group_counter,
                qualification_counter=qualification_counter,
            )
        )
    return expanded


def expand_macro_swarms_with_metadata(
    segments: list[str],
    local_macros: dict[str, Macro] | None = None,
    *,
    max_depth: int = 8,
    _strict_segment_check: bool = True,
    group_counter: Iterator[int] | None = None,
    qualification_counter: Iterator[int] | None = None,
) -> list[_ExpandedMacroSwarmSegment]:
    """Expand any macro swarm references in *segments* into sub-segments.

    For each segment:
        * If the segment is a sole top-level reference (per
          :func:`extract_top_level_macro_reference`) to a macro whose body
          contains ``---`` separators, substitute the call's args into the
          macro body and split the result on ``---``.  The call site's
          leading directives (e.g. ``%id:custom``) attach to the *first*
          sub-segment only.
        * If the segment contains multiple macro swarm references, each
          reference fans out in document order.  Leading prose attaches to the
          first generated segment; inter-reference and trailing prose is
          discarded.
        * Otherwise, the segment is passed through unchanged.

    Recursion: each sub-segment is fed back through this function with
    ``max_depth - 1`` so a macro swarm can compose another macro swarm.
    When *max_depth* is exhausted on a still-qualifying reference,
    :class:`ValueError` is raised.

    Raises:
        _MacroSwarmUsageError: A segment uses the standalone marker for
            an ordinary embeddable macro.
        ValueError: Recursive expansion exceeded *max_depth*.

    ``group_counter`` and ``qualification_counter`` let callers that expand
    segments one call at a time (e.g. per-segment ``segment_extra_env``
    launches) share independent invocation counters. Distinct invocations of
    the same macro then collide on neither template groups nor keyed-marker
    namespaces.
    """
    return _expand_macro_swarms_with_metadata(
        segments,
        local_macros=local_macros,
        max_depth=max_depth,
        strict_segment_check=_strict_segment_check,
        swarm_macros=(),
        group_counter=group_counter if group_counter is not None else count(),
        qualification_counter=(
            qualification_counter if qualification_counter is not None else count()
        ),
    )


def _expand_macro_swarms_with_metadata(
    segments: list[str],
    *,
    local_macros: dict[str, Macro] | None,
    max_depth: int,
    strict_segment_check: bool = True,
    template_group: str | None = None,
    swarm_macros: tuple[str, ...],
    group_counter: Iterator[int],
    qualification_counter: Iterator[int],
) -> list[_ExpandedMacroSwarmSegment]:
    # Fast path: if no segment contains '#', no macro reference is possible.
    if not any("#" in seg for seg in segments):
        return [
            _ExpandedMacroSwarmSegment(seg, template_group, swarm_macros)
            for seg in segments
        ]

    catalog: dict[str, Macro] = dict(get_all_macros())
    if local_macros:
        catalog.update(local_macros)
    available = set(catalog.keys())

    swarm_names = {
        name for name, xp in catalog.items() if macro_has_segment_separators(xp)
    }

    expanded: list[_ExpandedMacroSwarmSegment] = []
    for segment in segments:
        call = _extract_top_level_macro_reference(segment, available)
        if call is not None and call.name in swarm_names:
            if max_depth <= 0:
                raise _MacroSwarmDepthError(
                    f"xprompt swarm expansion exceeded max depth at "
                    f"#{call.name} (possible self-reference)"
                )
            group = template_group or _next_template_group(call.name, group_counter)
            current_swarm_macros = _append_swarm_macro(swarm_macros, call.name)
            xp = catalog[call.name]
            sub_segments = render_macro_swarm(
                xp,
                call.positional_args,
                call.named_args,
                qualification_counter,
            )
            if not sub_segments:
                # A macro body that had separators but produces no content
                # after substitution (e.g. all-empty segments): drop entirely.
                continue
            sub_segments = prepend_inherited_vcs_ref(
                sub_segments, call.leading_vcs_ref_text
            )
            if call.leading_directive_prefix:
                sub_segments[0] = f"{call.leading_directive_prefix}{sub_segments[0]}"
            recursively_expanded = _expand_macro_swarms_with_metadata(
                sub_segments,
                local_macros=local_macros,
                max_depth=max_depth - 1,
                strict_segment_check=strict_segment_check,
                template_group=group,
                swarm_macros=current_swarm_macros,
                group_counter=group_counter,
                qualification_counter=qualification_counter,
            )
            expanded.extend(recursively_expanded)
        elif call is not None and call.marker is MacroReferenceMarker.STANDALONE:
            raise _MacroSwarmUsageError(
                invalid_explicit_macro_message(
                    MacroReference(
                        marker=call.marker,
                        name=call.name,
                        start=0,
                        end=0,
                        raw=call.raw,
                    )
                )
            )
        else:
            invalid_standalone = first_invalid_standalone_macro_reference(
                segment, catalog, swarm_names
            )
            if invalid_standalone is not None:
                raise _MacroSwarmUsageError(
                    invalid_explicit_macro_message(invalid_standalone)
                )

            if strict_segment_check:
                macro_swarm_refs = macro_swarm_references(segment, swarm_names)
                if len(macro_swarm_refs) == 1:
                    expanded.extend(
                        _expand_embedded_macro_swarm_reference(
                            segment,
                            macro_swarm_refs[0],
                            catalog,
                            local_macros,
                            max_depth,
                            template_group,
                            swarm_macros,
                            group_counter,
                            qualification_counter,
                        )
                    )
                    continue
                if len(macro_swarm_refs) > 1:
                    expanded.extend(
                        _expand_multiple_embedded_macro_swarm_references(
                            segment,
                            macro_swarm_refs,
                            catalog,
                            local_macros,
                            max_depth,
                            strict_segment_check,
                            swarm_macros,
                            group_counter,
                            qualification_counter,
                        )
                    )
                    continue
            expanded.append(
                _ExpandedMacroSwarmSegment(segment, template_group, swarm_macros)
            )

    return expanded


def _next_template_group(name: str, group_counter: Iterator[int]) -> str:
    return f"xprompt:{name}:{next(group_counter)}"


def _append_swarm_macro(swarm_macros: tuple[str, ...], name: str) -> tuple[str, ...]:
    if name in swarm_macros:
        return swarm_macros
    return (*swarm_macros, name)


__all__ = [
    "expand_macro_swarms_with_metadata",
    "_extract_top_level_macro_reference",
    "macro_has_segment_separators",
]
