"""Rendered-segment preparation for xprompt swarm expansion."""

from __future__ import annotations

import re
from collections.abc import Iterator

from sase.agent.multi_prompt import split_segments_protecting_fences
from sase.agent.names import iter_agent_name_key_markers
from sase.xprompt._disabled_regions import (
    protect_disabled_regions,
    unprotect_disabled_regions,
)
from sase.xprompt._fenced_blocks import (
    protect_fenced_blocks_only,
    unprotect_fenced_blocks,
)
from sase.xprompt.models import XPrompt
from sase.xprompt.processor import expand_single_xprompt


def render_xprompt_swarm(
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
