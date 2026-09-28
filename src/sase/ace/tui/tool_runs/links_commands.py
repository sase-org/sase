"""Command detection and run-id scraping for run-links."""

from __future__ import annotations

import re

__all__ = [
    "extract_run_ids",
    "is_tool_run_command",
]

_HEX_RUN_ID_RE = re.compile(r"\b[0-9a-f]{32}\b")
_TOOL_RUN_COMMAND_RE = re.compile(r"\bsase\b.*\btool\b.*\brun\b")
_MONITOR_START_RE = re.compile(r"\bsase\b.*\bmonitor\b.*\bstart\b")


def is_tool_run_command(command: str | None) -> bool:
    """Return True when *command* runs (or wraps) ``sase tool run``."""

    if not command:
        return False
    text = str(command)
    return bool(_TOOL_RUN_COMMAND_RE.search(text) or _MONITOR_START_RE.search(text))


def extract_run_ids(text: str | None) -> tuple[str, ...]:
    """Return 32-hex run ids found in *text*, in order, deduped."""

    if not text:
        return ()
    seen: set[str] = set()
    found: list[str] = []
    for match in _HEX_RUN_ID_RE.findall(str(text)):
        if match not in seen:
            seen.add(match)
            found.append(match)
    return tuple(found)
