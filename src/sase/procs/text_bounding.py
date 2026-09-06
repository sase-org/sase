"""Shared bounding and redaction primitives for proc-shell output text.

Kept dependency-light (no Textual/ACE imports) so both the ACE proc-shell
projection and the history ``#fork`` renderer can bound and redact untrusted
program output identically without importing one another.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from sase.core.rust import require_rust_binding

_SENSITIVE_LINE_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|bearer)\b"
)


@dataclass(frozen=True, slots=True)
class TextTail:
    """Tail text plus counts omitted before the selected tail."""

    text: str
    omitted_lines: int
    omitted_chars: int


def bound_and_redact_text(raw: str | None, max_chars: int) -> str | None:
    """Redact sensitive lines and bound *raw* to its last *max_chars* characters."""
    if not raw:
        return None
    lines = [
        "<redacted sensitive line>" if _SENSITIVE_LINE_RE.search(line) else line
        for line in raw.splitlines()
    ]
    value = "\n".join(lines)
    if len(value) <= max_chars:
        return value
    return f"{value[-max_chars:]}\n... truncated to last {max_chars} chars ..."


def tail_text_by_lines_and_chars(
    text: str,
    max_lines: int,
    max_chars: int,
) -> TextTail:
    """Return the end of *text* under both a line and character budget."""
    binding = require_rust_binding("tail_text_by_lines_and_chars")
    payload = binding(text, max(0, max_lines), max(0, max_chars))
    if not isinstance(payload, Mapping):
        raise RuntimeError("tail_text_by_lines_and_chars returned a non-dict payload")
    return TextTail(
        text=str(payload.get("text", "")),
        omitted_lines=_int_field(payload, "omitted_lines"),
        omitted_chars=_int_field(payload, "omitted_chars"),
    )


def _int_field(payload: Mapping[str, Any], field: str) -> int:
    value = payload.get(field, 0)
    return value if isinstance(value, int) else int(value)


__all__ = ["TextTail", "bound_and_redact_text", "tail_text_by_lines_and_chars"]
