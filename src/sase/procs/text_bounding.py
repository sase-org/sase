"""Shared bounding and redaction primitives for proc-shell output text.

Kept dependency-light (no Textual/ACE imports) so both the ACE proc-shell
projection and the history ``#fork`` renderer can bound and redact untrusted
program output identically without importing one another.
"""

from __future__ import annotations

import re

_SENSITIVE_LINE_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|bearer)\b"
)


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


__all__ = ["bound_and_redact_text"]
