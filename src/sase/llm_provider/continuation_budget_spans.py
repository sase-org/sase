"""Structural markers for continuation-budget protected/reducible prompt spans.

``continuation_budget_projection.py`` must decide which parts of a fully
expanded prompt are safe to omit under context pressure. Guessing from
Markdown headings is unsound: authored or untrusted content can legitimately
contain a heading string like ``## Selected diagnostics`` without being the
render-generated section of that name, and treating it as reducible would
silently delete whatever protected content follows.

Renderers that emit a genuinely reducible section (``followup_prompt.py``,
``result_projection.py``, continuation replay's ``_render.py``) wrap it with
the markers below at the exact point they build it, so discovery here parses
only explicit, code-attributed spans -- never headings. Any marker-shaped
substring already present in untrusted text is neutralized with
``sanitize_span_text`` before embedding, the same defense-in-depth precedent
``xprompt._disabled_regions`` uses for its own marker syntax.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import count
import re
from urllib.parse import quote

_MARKER_TAG = "sase:budget-span"
_OPEN_RE = re.compile(r"<!--" + re.escape(_MARKER_TAG) + r":open:(?P<fields>[^>]*?)-->")
_CLOSE_RE = re.compile(r"<!--" + re.escape(_MARKER_TAG) + r":close:(?P<id>[0-9]+)-->")
_SPOOF_RE = re.compile(re.escape(_MARKER_TAG))
_id_counter = count(1)


@dataclass(frozen=True, slots=True)
class _ReducibleSpan:
    """A code-attributed, marker-delimited span the render layer marked reducible."""

    kind: str
    start: int
    end: int
    checkpoint_ref: str | None
    covered_node_ids: tuple[str, ...]


def sanitize_span_text(text: str) -> str:
    """Neutralize marker-shaped text so untrusted content cannot forge a span."""

    if _MARKER_TAG not in text:
        return text
    return _SPOOF_RE.sub("sase: budget-span", text)


def open_reducible_span_marker(
    *,
    kind: str,
    checkpoint_ref: str | None = None,
    covered_node_ids: Sequence[str] = (),
) -> tuple[str, str]:
    """Return a paired (open, close) marker bracketing one reducible span.

    Values are percent-encoded so the enclosing HTML comment can never be
    broken out of by a crafted field value.
    """

    span_id = str(next(_id_counter))
    fields = [f"kind={quote(kind, safe='')}", f"id={span_id}"]
    if checkpoint_ref:
        fields.append(f"checkpoint_ref={quote(checkpoint_ref, safe='')}")
    covered = [node for node in covered_node_ids if node]
    if covered:
        fields.append("covered=" + ",".join(quote(node, safe="") for node in covered))
    open_marker = f"<!--{_MARKER_TAG}:open:{';'.join(fields)}-->"
    close_marker = f"<!--{_MARKER_TAG}:close:{span_id}-->"
    return open_marker, close_marker


def extract_reducible_spans(prompt: str) -> list[_ReducibleSpan]:
    """Parse well-formed, non-overlapping marker pairs from *prompt*.

    A malformed, unmatched, or out-of-order marker is ignored rather than
    raising: a missing reducible span only means less compaction headroom,
    never lost protected content.
    """

    closes = {match.group("id"): match for match in _CLOSE_RE.finditer(prompt)}
    spans: list[_ReducibleSpan] = []
    last_end = 0
    for open_match in _OPEN_RE.finditer(prompt):
        start = open_match.start()
        if start < last_end:
            continue
        fields = _parse_fields(open_match.group("fields"))
        span_id = fields.get("id")
        close_match = closes.get(span_id) if span_id else None
        if close_match is None or close_match.start() < open_match.end():
            continue
        end = close_match.end()
        kind = fields.get("kind")
        if not kind:
            continue
        covered_raw = fields.get("covered")
        covered = tuple(covered_raw.split(",")) if covered_raw else ()
        spans.append(
            _ReducibleSpan(
                kind=kind,
                start=start,
                end=end,
                checkpoint_ref=fields.get("checkpoint_ref"),
                covered_node_ids=covered,
            )
        )
        last_end = end
    return spans


def _parse_fields(raw: str) -> dict[str, str]:
    from urllib.parse import unquote

    fields: dict[str, str] = {}
    for part in raw.split(";"):
        key, sep, value = part.partition("=")
        if not sep:
            continue
        fields[key] = unquote(value)
    return fields


__all__ = [
    "extract_reducible_spans",
    "open_reducible_span_marker",
    "sanitize_span_text",
]
