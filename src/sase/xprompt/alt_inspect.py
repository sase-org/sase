"""Frontend-agnostic inspection helpers for alt fan-out prompts.

These helpers compute span information used to highlight ``%{A | B}``,
``%alt(A, B)``, and ``%(A, B)`` fan-out forms in prompt editors. They are
presentation-layer only: the canonical fan-out grammar lives in the Rust core
(``sase_core::agent_launch``) and is exposed to Python through the
``alternation_scan`` binding. This module is a thin memoized adapter over that
scan, so the visual treatment always matches launch behavior:

- the brace form opens anywhere outside literal/definition zones (including
  mid-word: ``foo%{bar | baz}qux``), while the paren forms still need a
  directive-valid position (start of line, or after whitespace / an opening
  bracket / a quote / a directive-value colon);
- top-level ``|`` (brace form) or ``,`` (paren forms) separators split
  branches, where "top-level" means outside nested alternations, quoting, and
  text blocks — single quotes do not hide structure;
- an optional ``name=`` prefix on a branch names that branch;
- an unclosed opener is an error span over the opener.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

AltSpanKind = Literal["delimiter", "separator", "branch_name", "error"]


@dataclass(frozen=True, slots=True)
class AltSpan:
    """A single highlightable span of alt fan-out syntax.

    Offsets are character offsets into the original (unmasked) text.
    """

    start: int
    end: int
    kind: AltSpanKind


@dataclass(frozen=True, slots=True)
class _AltGroup:
    """A top-level closed ``%{...}`` group with its branch texts.

    ``start``/``end`` are character offsets covering the whole group
    (``end`` is exclusive, just past the closing brace). ``branches`` holds
    the raw branch texts split at the core-reported top-level separators.
    """

    start: int
    end: int
    branches: tuple[str, ...]


def _get_alternation_scan_binding() -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding("alternation_scan")


def _has_alt_marker(text: str) -> bool:
    return "%{" in text or "%(" in text or "%alt(" in text


@lru_cache(maxsize=128)
def _cached_records(text: str) -> tuple[dict[str, Any], ...]:
    """Scan records for *text*, shared by every caller of one rebuild.

    The TUI prompt input rebuilds its highlight map synchronously on every
    keystroke, with up to three alt callers per rebuild (the alt overlay,
    ``highlight_spans``, and the semantic overlay). Keying on the text means
    those callers share a single FFI scan per distinct text.
    """
    scan = _get_alternation_scan_binding()
    return tuple(dict(record) for record in scan(text))


def tokenize(text: str) -> list[AltSpan]:
    """Return alt fan-out spans, sorted by start offset.

    Spans inside fenced blocks, inline code, or disabled regions are ignored
    (the core scan already excludes those zones). An unclosed opener yields a
    single ``error`` span over the opener. Alternation-free text returns ``[]``
    without crossing FFI.
    """
    if not _has_alt_marker(text):
        return []
    spans = [span for record in _cached_records(text) for span in _record_spans(record)]
    spans.sort(key=lambda span: span.start)
    return spans


def groups(text: str) -> tuple[_AltGroup, ...]:
    """Return top-level closed ``%{...}`` groups with their branch texts.

    Shares the same cached scan records as :func:`tokenize`, so grouping never
    costs an extra FFI scan. Alternation-free text returns ``()`` without
    crossing FFI.
    """
    if not _has_alt_marker(text):
        return ()
    found: list[_AltGroup] = []
    for record in _cached_records(text):
        if record["form"] != "brace" or record["depth"] != 0:
            continue
        close = record["close"]
        if close is None:
            continue
        opener_end = int(record["opener_end"])
        previous = opener_end
        branches: list[str] = []
        for separator in record["separators"]:
            branches.append(text[previous : int(separator)])
            previous = int(separator) + 1
        branches.append(text[previous : int(close)])
        found.append(
            _AltGroup(int(record["marker_start"]), int(close) + 1, tuple(branches))
        )
    return tuple(found)


def _record_spans(record: dict[str, Any]) -> list[AltSpan]:
    """Derive highlight spans from one core scan record."""
    marker_start = int(record["marker_start"])
    opener_end = int(record["opener_end"])
    close = record["close"]
    if close is None:
        return [AltSpan(marker_start, opener_end, "error")]
    spans = [
        AltSpan(marker_start, opener_end, "delimiter"),
        AltSpan(int(close), int(close) + 1, "delimiter"),
    ]
    spans.extend(
        AltSpan(int(separator), int(separator) + 1, "separator")
        for separator in record["separators"]
    )
    for branch_name in record["branch_names"]:
        start, end = int(branch_name[0]), int(branch_name[1])
        spans.append(AltSpan(start, end, "branch_name"))
    return spans
