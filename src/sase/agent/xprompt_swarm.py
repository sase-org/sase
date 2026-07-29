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

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import count

from sase.agent._xprompt_swarm_parsing import (
    build_xprompt_call,
    extract_top_level_xprompt_reference as _extract_top_level_xprompt_reference,
    first_invalid_standalone_xprompt_reference,
    invalid_explicit_xprompt_message,
    leading_vcs_ref_text,
    prepend_inherited_vcs_ref,
    xprompt_swarm_references,
)
from sase.agent._xprompt_swarm_rendering import render_xprompt_swarm
from sase.xprompt._parsing import XPromptReference, XPromptReferenceMarker
from sase.xprompt.loader import get_all_xprompts
from sase.xprompt.models import XPrompt
from sase.xprompt.segment_separators import xprompt_has_segment_separators


class _XpromptSwarmError(ValueError):
    """Base class for xprompt swarm expansion errors."""


class _XpromptSwarmUsageError(_XpromptSwarmError):
    """Raised when an xprompt swarm reference is ambiguous or invalid."""


class _XpromptSwarmDepthError(_XpromptSwarmError):
    """Raised when recursive xprompt swarm expansion exceeds the depth cap."""


@dataclass(frozen=True)
class _ExpandedXpromptSwarmSegment:
    """Expanded segment plus optional template-allocation group metadata."""

    prompt: str
    template_group: str | None = None


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

    call = build_xprompt_call(ref, [])
    group = template_group or _next_template_group(call.name, group_counter)
    sub_segments = render_xprompt_swarm(
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
    follow_ups = prepend_inherited_vcs_ref(
        sub_segments[1:], leading_vcs_ref_text(segment)
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
    inherited_vcs_ref = leading_vcs_ref_text(segment)
    expanded: list[_ExpandedXpromptSwarmSegment] = []
    for index, ref in enumerate(refs):
        call = build_xprompt_call(ref, [])
        group = _next_template_group(call.name, group_counter)
        sub_segments = render_xprompt_swarm(
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
            sub_segments = render_xprompt_swarm(
                xp,
                call.positional_args,
                call.named_args,
                qualification_counter,
            )
            if not sub_segments:
                # An xprompt body that had separators but produces no content
                # after substitution (e.g. all-empty segments): drop entirely.
                continue
            sub_segments = prepend_inherited_vcs_ref(
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
                invalid_explicit_xprompt_message(
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
            invalid_standalone = first_invalid_standalone_xprompt_reference(
                segment, catalog, swarm_names
            )
            if invalid_standalone is not None:
                raise _XpromptSwarmUsageError(
                    invalid_explicit_xprompt_message(invalid_standalone)
                )

            if strict_segment_check:
                xprompt_swarm_refs = xprompt_swarm_references(segment, swarm_names)
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
