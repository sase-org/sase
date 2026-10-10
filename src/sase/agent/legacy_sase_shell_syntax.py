"""Compatibility normalizers for retired sase-shell user syntax.

Keep every temporary alias for the sase-turn terminology migration in this
module. Both durable readers and authored input always accept the retired
spellings as aliases of their sase-turn replacements.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _retired_sase_shell_syntax_message(legacy: str, replacement: str) -> str:
    """Return the consistent replacement hint for one retired spelling."""
    return f"{legacy} is retired; use {replacement}"


_LEGACY_FORK = "shell"
_CANONICAL_FORK = "turn"
_LEGACY_CONTINUATION = "gate_shell"
_CANONICAL_CONTINUATION = "gate_turn"
_LEGACY_SPEC_BLOCK = "shell"
_CANONICAL_SPEC_BLOCK = "turn"


def normalize_gate_fork(value: object, *, persisted: bool = False) -> object:
    """Normalize a gate fork value to its turn spelling."""
    if value != _LEGACY_FORK:
        return value
    # Retired switch kept for compatibility and ignored.
    _ = persisted
    return _CANONICAL_FORK


def normalize_gate_spec_block(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Return *spec* with a legacy ``shell`` block moved to ``turn``.

    A spec containing both blocks raises.
    """
    data = dict(spec)
    has_legacy = _LEGACY_SPEC_BLOCK in data
    has_canonical = _CANONICAL_SPEC_BLOCK in data
    if has_legacy and has_canonical:
        raise ValueError("shell and turn blocks cannot be combined; use only turn.")
    if not has_legacy:
        return data
    data[_CANONICAL_SPEC_BLOCK] = data.pop(_LEGACY_SPEC_BLOCK)
    return data


def normalize_continuation_mode(value: object, *, persisted: bool = False) -> object:
    """Normalize a gate continuation mode to its turn spelling."""
    if value != _LEGACY_CONTINUATION:
        return value
    # Retired switch kept for compatibility and ignored.
    _ = persisted
    return _CANONICAL_CONTINUATION


def normalize_persisted_continuation_mode(value: object) -> object:
    """Normalize a pre-rename durable continuation mode to its turn spelling."""
    return normalize_continuation_mode(value, persisted=True)


def normalize_proc_name_args(
    args: Mapping[str, Any], *, persisted: bool = False
) -> dict[str, Any]:
    """Map a legacy ``shell`` proc-name value to ``name``."""
    # Retired switch kept for compatibility and ignored.
    _ = persisted
    data = dict(args)
    has_legacy = "shell" in data and data["shell"] is not None
    has_canonical = "name" in data and data["name"] is not None
    if has_legacy and has_canonical:
        raise ValueError("--shell and --name cannot be combined; use only --name.")
    if not has_legacy:
        return data
    data["name"] = data.pop("shell")
    return data


def normalize_gate_shell_bool_args(args: Mapping[str, Any]) -> dict[str, Any]:
    """Map legacy gate-create shell bools to their turn replacements.

    Handles ``shell``/``shell_status``/``shell_stop_status`` -> ``turn``/
    ``turn_status``/``turn_stop_status``. Both spellings together raise.
    """
    pairs = (
        ("shell", "turn"),
        ("shell_status", "turn_status"),
        ("shell_stop_status", "turn_stop_status"),
    )
    data = dict(args)
    for legacy, canonical in pairs:
        has_legacy = legacy in data and data[legacy] not in (None, False)
        has_canonical = canonical in data and data[canonical] not in (None, False)
        if has_legacy and has_canonical:
            raise ValueError(
                _retired_sase_shell_syntax_message(f"--{legacy}", f"--{canonical}")
                + "; use only the turn spelling"
            )
        if has_legacy:
            data[canonical] = data.pop(legacy)
    return data


def normalize_reclaim_config(data: Mapping[str, Any]) -> dict[str, Any]:
    """Map legacy ``gate.shell.reclaim_grace_seconds`` to the turn key."""
    result = dict(data)
    gate = result.get("gate")
    if not isinstance(gate, dict):
        return result
    gate = dict(gate)
    shell_branch = gate.get("shell")
    turn_branch = gate.get("turn")
    if isinstance(shell_branch, dict) and "reclaim_grace_seconds" in shell_branch:
        if isinstance(turn_branch, dict) and "reclaim_grace_seconds" in turn_branch:
            raise ValueError(
                "gate.shell and gate.turn cannot both set reclaim_grace_seconds; "
                "use only gate.turn"
            )
        turn_branch = dict(turn_branch) if isinstance(turn_branch, dict) else {}
        turn_branch["reclaim_grace_seconds"] = shell_branch["reclaim_grace_seconds"]
        gate["turn"] = turn_branch
    result["gate"] = gate
    return result


__all__ = [
    "normalize_continuation_mode",
    "normalize_gate_fork",
    "normalize_gate_shell_bool_args",
    "normalize_gate_spec_block",
    "normalize_persisted_continuation_mode",
    "normalize_proc_name_args",
    "normalize_reclaim_config",
]
