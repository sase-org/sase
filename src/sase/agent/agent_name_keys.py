"""Dispatch-scoped resolution for keyed agent-name markers."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sase.agent.names import (
    AgentNameNamespaceReservationIndex,
    iter_agent_name_key_markers,
)
from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from sase.xprompt._fenced_blocks import (
    protect_fenced_blocks_only,
    unprotect_fenced_blocks,
)

_NAME_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)


@dataclass(frozen=True)
class _MarkerOccurrence:
    key: str
    start: int
    end: int


@dataclass
class _ProtectedSegment:
    text: str
    fenced_blocks: list[str]
    disabled_regions: list[str]
    occurrences: list[_MarkerOccurrence]

    def restore(self, text: str) -> str:
        text = unprotect_disabled_regions(text, self.disabled_regions)
        return unprotect_fenced_blocks(text, self.fenced_blocks)


def agent_name_allocation_lock() -> AbstractContextManager[None]:
    from sase.agent.names import agent_name_allocation_lock as impl

    return impl()


def get_reserved_agent_names() -> set[str]:
    from sase.agent.names import get_reserved_agent_names as impl

    return impl()


def get_reserved_clan_names() -> set[str]:
    from sase.agent.names import get_reserved_clan_names as impl

    return impl()


def iter_agent_name_template_tokens() -> Iterator[str]:
    from sase.agent.names import iter_agent_name_template_tokens as impl

    return impl()


def render_agent_name_template(template: str, token: str) -> str:
    from sase.agent.names import render_agent_name_template as impl

    return impl(template, token)


def render_agent_name_template_namespace(template: str, token: str) -> str:
    from sase.agent.names import render_agent_name_template_namespace as impl

    return impl(template, token)


def resolve_agent_name_key_markers(segments: Sequence[str]) -> list[str]:
    """Resolve every keyed marker in *segments* from one registry snapshot.

    Keys are shared across the complete dispatch. Fenced code blocks and
    disabled xprompt regions remain literal, while inline-code prose is
    rewritten just like ordinary prose.
    """
    if not any("{@" in segment for segment in segments):
        return list(segments)

    protected_segments: list[_ProtectedSegment] = []
    shapes_by_key: OrderedDict[str, list[str]] = OrderedDict()
    seen_shapes: dict[str, set[str]] = {}

    for segment in segments:
        protected = _protect_segment(segment)
        occurrences: list[_MarkerOccurrence] = []
        for marker in iter_agent_name_key_markers(protected.text):
            if not marker.braced or marker.id is None:
                continue
            start = _character_index(protected.text, marker.start)
            end = _character_index(protected.text, marker.end)
            occurrence = _MarkerOccurrence(marker.id, start, end)
            occurrences.append(occurrence)

            left = start
            while left > 0 and protected.text[left - 1] in _NAME_CHARACTERS:
                left -= 1
            right = end
            while (
                right < len(protected.text)
                and protected.text[right] in _NAME_CHARACTERS
            ):
                right += 1
            shape = protected.text[left:right]
            key_shapes = shapes_by_key.setdefault(marker.id, [])
            key_seen = seen_shapes.setdefault(marker.id, set())
            if shape not in key_seen:
                key_shapes.append(shape)
                key_seen.add(shape)
        protected.occurrences = occurrences
        protected_segments.append(protected)

    if not shapes_by_key:
        return list(segments)

    tokens = _allocate_key_tokens(shapes_by_key)
    resolved: list[str] = []
    for protected_segment in protected_segments:
        text = protected_segment.text
        for occurrence in reversed(protected_segment.occurrences):
            token = tokens[occurrence.key]
            replacement = _replacement_for_occurrence(
                text,
                occurrence.start,
                token,
            )
            text = text[: occurrence.start] + replacement + text[occurrence.end :]
        resolved.append(protected_segment.restore(text))
    return resolved


def has_unresolved_agent_name_key_marker(text: str) -> bool:
    """Return whether executable prompt text still contains a keyed marker."""
    if "{@" not in text:
        return False
    protected = _protect_segment(text)
    return any(
        marker.braced and marker.id is not None
        for marker in iter_agent_name_key_markers(protected.text)
    )


def _protect_segment(text: str) -> _ProtectedSegment:
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks_only(text, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)
    return _ProtectedSegment(
        text=protected,
        fenced_blocks=fenced_blocks,
        disabled_regions=disabled_regions,
        occurrences=[],
    )


def _character_index(text: str, byte_offset: int) -> int:
    """Translate a Rust scanner byte offset into a Python string index."""
    return len(text.encode("utf-8")[:byte_offset].decode("utf-8"))


def _allocate_key_tokens(
    shapes_by_key: OrderedDict[str, list[str]],
) -> dict[str, str]:
    tokens: dict[str, str] = {}
    with agent_name_allocation_lock():
        index = AgentNameNamespaceReservationIndex.from_registry_names(
            get_reserved_agent_names(),
            namespace_containers=get_reserved_clan_names(),
        )
        for key, shapes in shapes_by_key.items():
            for token in iter_agent_name_template_tokens():
                candidates = {
                    (
                        render_agent_name_template(shape, token),
                        render_agent_name_template_namespace(shape, token),
                    )
                    for shape in shapes
                }
                if not all(
                    index.candidate_available(name, namespace)
                    for name, namespace in candidates
                ):
                    continue
                tokens[key] = token
                index.update_names({name for name, _ in candidates})
                break
            else:
                raise AssertionError("agent-name token iterator is infinite")
    return tokens


def _replacement_for_occurrence(text: str, start: int, token: str) -> str:
    left = start
    while left > 0 and text[left - 1] in _NAME_CHARACTERS:
        left -= 1
    preceding_run = text[left:start]
    if preceding_run and preceding_run[-1] not in {"-", "."} and token[:1].islower():
        return f"-{token}"
    return token


__all__ = [
    "has_unresolved_agent_name_key_marker",
    "resolve_agent_name_key_markers",
]
