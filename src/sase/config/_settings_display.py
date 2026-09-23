"""Pager, monitor, and Markdown-formatting settings accessors."""

from __future__ import annotations

from typing import Any

from sase.config import _settings as _settings_facade
from sase.markdown_width import DEFAULT_MARKDOWN_PRINT_WIDTH
from sase.markdown_wrap import MIN_PROSE_WRAP_WIDTH


def _merged_config() -> dict[str, Any]:
    """Route through the facade so its patch point stays effective."""
    return _settings_facade.merged_config()


DEFAULT_PAGER_SYNTAX = "auto"
DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES = 8 * 1024
DEFAULT_MONITOR_FALLBACK_TAIL_BYTES = 4 * 1024
DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES = 12 * 1024
DEFAULT_MONITOR_RAW_TAIL_LINES = 200
DEFAULT_MONITOR_TOOL_WRAP = "verify"
MONITOR_TOOL_WRAP_CHOICES = ("off", "verify", "all")


def get_pager_syntax() -> str:
    """Return ``pager.syntax``: ``auto`` or ``never``.

    Unknown or malformed values fall back to ``auto`` so a hand-edited
    ``sase.yml`` cannot crash the pager. Schema validation is the diagnostic
    path for rejected values.
    """
    try:
        pager = _merged_config().get("pager", {})
    except Exception:  # noqa: BLE001 - pager syntax is fail-open.
        return DEFAULT_PAGER_SYNTAX
    value = (
        pager.get("syntax", DEFAULT_PAGER_SYNTAX)
        if isinstance(pager, dict)
        else DEFAULT_PAGER_SYNTAX
    )
    if value in {"auto", "never"}:
        return str(value)
    return DEFAULT_PAGER_SYNTAX


def get_monitor_tool_wrap() -> str:
    """Return the validated ``monitor.tool_wrap`` policy (``off|verify|all``).

    Fails open to ``verify``, matching :func:`get_monitor_evidence_limits`:
    a hand-edited config must never turn ``sase monitor start`` into a
    traceback.
    """
    try:
        monitor = _merged_config().get("monitor", {})
    except Exception:  # noqa: BLE001 - monitor start should fail open.
        return DEFAULT_MONITOR_TOOL_WRAP
    if not isinstance(monitor, dict):
        return DEFAULT_MONITOR_TOOL_WRAP
    value = monitor.get("tool_wrap", DEFAULT_MONITOR_TOOL_WRAP)
    if isinstance(value, str) and value.strip() in MONITOR_TOOL_WRAP_CHOICES:
        return value.strip()
    return DEFAULT_MONITOR_TOOL_WRAP


def get_monitor_evidence_limits() -> dict[str, int]:
    """Return validated monitor evidence projection byte and line limits."""
    try:
        monitor = _merged_config().get("monitor", {})
    except Exception:  # noqa: BLE001 - evidence projection should fail open.
        return _default_monitor_evidence_limits()
    evidence = monitor.get("evidence_limits", {}) if isinstance(monitor, dict) else {}
    config = evidence if isinstance(evidence, dict) else {}
    limits = {
        "selected_diagnostics_bytes": _positive_int_config(
            config,
            "selected_diagnostics_bytes",
            DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES,
        ),
        "fallback_tail_bytes": _positive_int_config(
            config,
            "fallback_tail_bytes",
            DEFAULT_MONITOR_FALLBACK_TAIL_BYTES,
        ),
        "total_raw_excerpt_bytes": _positive_int_config(
            config,
            "total_raw_excerpt_bytes",
            DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES,
        ),
        "raw_tail_lines": _positive_int_config(
            config,
            "raw_tail_lines",
            DEFAULT_MONITOR_RAW_TAIL_LINES,
        ),
    }
    if (
        limits["selected_diagnostics_bytes"] > limits["total_raw_excerpt_bytes"]
        or limits["fallback_tail_bytes"] > limits["total_raw_excerpt_bytes"]
    ):
        return _default_monitor_evidence_limits()
    return limits


def _default_monitor_evidence_limits() -> dict[str, int]:
    return {
        "selected_diagnostics_bytes": DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES,
        "fallback_tail_bytes": DEFAULT_MONITOR_FALLBACK_TAIL_BYTES,
        "total_raw_excerpt_bytes": DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES,
        "raw_tail_lines": DEFAULT_MONITOR_RAW_TAIL_LINES,
    }


def _positive_int_config(
    config: dict[str, Any],
    key: str,
    default: int,
) -> int:
    value = config.get(key, default)
    return value if type(value) is int and value >= 1 else default


def get_markdown_print_width() -> int:
    """Return the validated configured Markdown prose width.

    Formatting must never hard-fail: a malformed ``~/.config/sase/sase.yml``
    turning ``sase plan propose`` into a traceback would be far worse than
    wrapping at the shipped default, so this accessor is fail-open.
    """
    try:
        markdown = _merged_config().get("markdown", {})
    except Exception:  # noqa: BLE001 - prose width is fail-open.
        return DEFAULT_MARKDOWN_PRINT_WIDTH
    value = (
        markdown.get("print_width", DEFAULT_MARKDOWN_PRINT_WIDTH)
        if isinstance(markdown, dict)
        else DEFAULT_MARKDOWN_PRINT_WIDTH
    )
    # Below ``MIN_PROSE_WRAP_WIDTH`` ``wrap_markdown()`` silently returns text
    # unwrapped, so the floor is the schema's ``minimum`` too.
    if type(value) is int and value >= MIN_PROSE_WRAP_WIDTH:
        return value
    return DEFAULT_MARKDOWN_PRINT_WIDTH


__all__ = [
    "DEFAULT_MONITOR_FALLBACK_TAIL_BYTES",
    "DEFAULT_MONITOR_RAW_TAIL_LINES",
    "DEFAULT_MONITOR_SELECTED_DIAGNOSTICS_BYTES",
    "DEFAULT_MONITOR_TOOL_WRAP",
    "DEFAULT_MONITOR_TOTAL_RAW_EXCERPT_BYTES",
    "DEFAULT_PAGER_SYNTAX",
    "MONITOR_TOOL_WRAP_CHOICES",
    "get_markdown_print_width",
    "get_monitor_evidence_limits",
    "get_monitor_tool_wrap",
    "get_pager_syntax",
]
