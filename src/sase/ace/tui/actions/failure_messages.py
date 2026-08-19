"""Register a session error and toast the leader chord that jumps to it."""

from __future__ import annotations

from typing import Any

from sase.logs import RegisteredError, register_error

_DEFAULT_CHORD = ",L"


def notify_registered_error(
    app: Any,
    prefix: str,
    *,
    error_id: str,
    source_id: str = "launch_failures",
    severity: str = "error",
) -> RegisteredError:
    """Register this session's latest error and toast the chord that reaches it."""
    registered = register_error(
        error_id=error_id,
        source_id=source_id,
        summary=prefix,
    )
    chord = _last_error_chord(app)
    app.notify(f"{prefix} - press {chord} for the log entry", severity=severity)
    return registered


def _last_error_chord(app: Any) -> str:
    """Return the configured jump-to-last-error chord, or ``,L`` if unknown."""
    registry = getattr(app, "_keymap_registry", None)
    if registry is None:
        return _DEFAULT_CHORD
    try:
        from ..keymaps import leader_key_display

        chord = leader_key_display(registry, "jump_to_last_error")
    except Exception:
        return _DEFAULT_CHORD
    return chord or _DEFAULT_CHORD


__all__ = ["notify_registered_error"]
