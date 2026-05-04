"""Multi-agent xprompt expansion at dispatch time.

When a user-prompt segment is a top-level reference to an xprompt whose body
contains ``---`` segment separators, expand the xprompt body once (substituting
the call-site's arguments) and then split the substituted body on ``---``,
replacing the original segment with N sub-segments — one per body segment.

Each spawned agent therefore receives the same input arguments, substituted
into its own segment.  See ``sdd/tales/202604/multi_agent_xprompts.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.agent.multi_prompt import split_segments_protecting_fences
from sase.xprompt._disabled_regions import protect_disabled_regions
from sase.xprompt._fenced_blocks import protect_fenced_blocks
from sase.xprompt._parsing import (
    extract_known_project_vcs_ref,
    XPromptReference,
    XPromptReferenceArgKind,
    XPromptReferenceMarker,
    iter_xprompt_references,
    normalize_vcs_underscore_refs,
)
from sase.xprompt.loader import get_all_xprompts
from sase.xprompt.models import XPrompt
from sase.xprompt.processor import expand_single_xprompt
from sase.xprompt.segment_separators import xprompt_has_segment_separators

_DIRECTIVE_LINE_RE = re.compile(r"^%[a-zA-Z][a-zA-Z0-9_]*(?:[:(].*)?\s*$")


class _MultiAgentXPromptError(ValueError):
    """Base class for multi-agent xprompt expansion errors."""


class MultiAgentXPromptUsageError(_MultiAgentXPromptError):
    """Raised when a multi-agent xprompt is referenced mid-segment.

    A multi-agent xprompt (one whose body contains ``---`` separators) must
    be the *only* content in its segment.  Mixing the reference with other
    prose is ambiguous — the user can split their prompt manually if they
    want surrounding text.
    """


class MultiAgentXPromptDepthError(_MultiAgentXPromptError):
    """Raised when recursive multi-agent xprompt expansion exceeds the depth cap."""


@dataclass
class _XPromptCall:
    """A parsed top-level xprompt reference in a segment."""

    name: str
    marker: XPromptReferenceMarker
    raw: str
    positional_args: list[str] = field(default_factory=list)
    named_args: dict[str, str] = field(default_factory=dict)
    leading_directives: list[str] = field(default_factory=list)
    leading_vcs_ref_text: str | None = None


def _split_leading_directives(segment: str) -> tuple[list[str], str]:
    """Split *segment* into (leading directive lines, remaining body).

    Directive lines are consecutive lines at the top of the segment matching
    ``_DIRECTIVE_LINE_RE``.  Leading blank lines are skipped.  The returned
    body keeps its original trailing whitespace stripped.
    """
    directives: list[str] = []
    lines = segment.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        if _DIRECTIVE_LINE_RE.match(stripped):
            directives.append(stripped)
            i += 1
            continue
        break
    remaining = "\n".join(lines[i:]).strip()
    return directives, remaining


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
            return [colon_arg[1:-1]], {}
        return colon_arg.split(","), {}
    return ref.parse_arguments()


def _build_xprompt_call(
    ref: XPromptReference,
    leading_directives: list[str],
    *,
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
    directives, body = _split_leading_directives(segment)
    if not directives:
        return f"{vcs_ref_text} {segment}"

    directive_block = "\n".join(directives)
    return f"{directive_block}\n{vcs_ref_text} {body}"


def extract_top_level_xprompt_reference(
    segment: str, available: set[str]
) -> _XPromptCall | None:
    """Return the call info if *segment* is a sole top-level xprompt reference.

    A segment qualifies if, after stripping leading blank/directive lines and
    trailing whitespace, what remains is exactly one ``#name`` or ``#!name``
    (optionally with args) and nothing else, and ``name`` is in *available*.
    """
    directives, body = _split_leading_directives(segment)
    if not body:
        return None

    ref = _sole_xprompt_reference(body, available)
    if ref is not None:
        return _build_xprompt_call(ref, directives)

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
        leading_vcs_ref_text=leading_vcs_ref_text,
    )


def _real_xprompt_references(segment: str) -> list[XPromptReference]:
    """Return lexical xprompt references in *segment*, excluding fenced examples."""
    protected = _protected_prompt_for_ref_detection(segment)
    return iter_xprompt_references(protected)


def _first_multi_agent_reference(
    segment: str, multi_agent_names: set[str]
) -> XPromptReference | None:
    """Return the first real reference to a multi-agent xprompt in *segment*."""
    if not multi_agent_names:
        return None
    for ref in _real_xprompt_references(segment):
        if ref.name in multi_agent_names:
            return ref
    return None


def _first_invalid_standalone_xprompt_reference(
    segment: str,
    catalog: dict[str, XPrompt],
    multi_agent_names: set[str],
) -> XPromptReference | None:
    """Return the first ``#!`` reference to an ordinary embeddable xprompt."""
    for ref in _real_xprompt_references(segment):
        if (
            ref.is_standalone_marker
            and ref.name in catalog
            and ref.name not in multi_agent_names
        ):
            return ref
    return None


def _multi_agent_requires_bang_message(name: str) -> str:
    return (
        f"Multi-agent xprompt '#{name}' must be invoked as '#!{name}' "
        "because it expands to multiple agent prompts."
    )


def _invalid_explicit_xprompt_message(ref: XPromptReference) -> str:
    return (
        "Only standalone workflows and multi-agent xprompts use '#!'; "
        f"'{ref.raw}' resolves to an embeddable xprompt. "
        f"Use '#{ref.name}' for inline expansion."
    )


def _mixed_multi_agent_reference_message(segment: str) -> str:
    return (
        "Multi-agent xprompt reference must be invoked as a sole '#!' "
        "reference in its segment (no surrounding prose). Segment:\n"
        f"{segment}"
    )


def expand_multi_agent_xprompts(
    segments: list[str],
    local_xprompts: dict[str, XPrompt] | None = None,
    *,
    max_depth: int = 8,
    _strict_segment_check: bool = True,
) -> list[str]:
    """Expand any multi-agent xprompt references in *segments* into sub-segments.

    For each segment:
        * If the segment is a sole top-level reference (per
          :func:`extract_top_level_xprompt_reference`) to an xprompt whose body
          contains ``---`` separators, substitute the call's args into the
          xprompt body and split the result on ``---``.  The call site's
          leading directives (e.g. ``%name:custom``) attach to the *first*
          sub-segment only.
        * Otherwise, the segment is passed through unchanged.

    Recursion: each sub-segment is fed back through this function with
    ``max_depth - 1`` so a multi-agent xprompt can compose another multi-agent
    xprompt.  When *max_depth* is exhausted on a still-qualifying reference,
    :class:`MultiAgentXPromptDepthError` is raised.

    Raises:
        MultiAgentXPromptUsageError: A segment contains a multi-agent xprompt
            reference but isn't a sole top-level reference to it.
        MultiAgentXPromptDepthError: Recursive expansion exceeded *max_depth*.
    """
    # Fast path: if no segment contains '#', no xprompt reference is possible.
    if not any("#" in seg for seg in segments):
        return list(segments)

    catalog: dict[str, XPrompt] = dict(get_all_xprompts())
    if local_xprompts:
        catalog.update(local_xprompts)
    available = set(catalog.keys())

    multi_agent_names = {
        name for name, xp in catalog.items() if xprompt_has_segment_separators(xp)
    }

    expanded: list[str] = []
    for segment in segments:
        call = extract_top_level_xprompt_reference(segment, available)
        if call is not None and call.name in multi_agent_names:
            if call.marker is XPromptReferenceMarker.INLINE:
                raise MultiAgentXPromptUsageError(
                    _multi_agent_requires_bang_message(call.name)
                )
            if max_depth <= 0:
                raise MultiAgentXPromptDepthError(
                    f"multi-agent xprompt expansion exceeded max depth at "
                    f"#!{call.name} (possible self-reference)"
                )
            xp = catalog[call.name]
            substituted = expand_single_xprompt(
                xp, call.positional_args, call.named_args
            )
            sub_segments = split_segments_protecting_fences(substituted)
            if not sub_segments:
                # An xprompt body that had separators but produces no content
                # after substitution (e.g. all-empty segments): drop entirely.
                continue
            sub_segments = _prepend_inherited_vcs_ref(
                sub_segments, call.leading_vcs_ref_text
            )
            if call.leading_directives:
                directive_block = "\n".join(call.leading_directives)
                sub_segments[0] = f"{directive_block}\n{sub_segments[0]}"
            recursively_expanded = expand_multi_agent_xprompts(
                sub_segments,
                local_xprompts=local_xprompts,
                max_depth=max_depth - 1,
            )
            expanded.extend(recursively_expanded)
        elif call is not None and call.marker is XPromptReferenceMarker.STANDALONE:
            raise MultiAgentXPromptUsageError(
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
                segment, catalog, multi_agent_names
            )
            if invalid_standalone is not None:
                raise MultiAgentXPromptUsageError(
                    _invalid_explicit_xprompt_message(invalid_standalone)
                )

            if _strict_segment_check:
                multi_agent_ref = _first_multi_agent_reference(
                    segment, multi_agent_names
                )
                if multi_agent_ref is not None:
                    if multi_agent_ref.is_standalone_marker:
                        raise MultiAgentXPromptUsageError(
                            _mixed_multi_agent_reference_message(segment)
                        )
                    raise MultiAgentXPromptUsageError(
                        _multi_agent_requires_bang_message(multi_agent_ref.name)
                    )
            expanded.append(segment)

    return expanded


__all__ = [
    "MultiAgentXPromptDepthError",
    "MultiAgentXPromptUsageError",
    "expand_multi_agent_xprompts",
    "extract_top_level_xprompt_reference",
    "xprompt_has_segment_separators",
]
