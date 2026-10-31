"""Bound-turn wait wire dataclasses for the agent scan facade.

Split out of :mod:`sase.core.agent_scan_wire_markers` to keep each module
under the 500-line cap. The scanner projects ``wait_turn_bindings`` from
``wait_for_artifacts`` and non-``history_only`` ``wait_for_fork_sources``
records with ``target: "turn"``. The per-file marker projections that
carry the field live in :mod:`sase.core.agent_scan_wire_markers`; import
that module for the stable import path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


_WAIT_TURN_BINDINGS_MAX_ENTRIES = 64


@dataclass(frozen=True)
class WaitTurnBindingWire:
    """One bound turn wait, projected for TUI display.

    ``name`` is the authored wait name (``requested``, else ``name``).
    ``turn_name`` is the pinned member captured at bind time.
    """

    name: str = ""
    turn_name: str = ""


def format_wait_turn_binding(name: str, turn_name: str) -> str:
    """Return the compact TUI label for one bound turn wait."""
    return f"{name} → turn {turn_name}"


def format_wait_targets(
    names: Iterable[str],
    bindings: Iterable[WaitTurnBindingWire] | None = None,
) -> str:
    """Join wait names, annotating those with a bound turn."""
    by_name = {binding.name: binding.turn_name for binding in (bindings or ())}
    return ", ".join(
        format_wait_turn_binding(name, by_name[name]) if name in by_name else name
        for name in names
    )


def _trimmed_nonempty(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _binding_from_compact(item: object) -> WaitTurnBindingWire | None:
    if isinstance(item, WaitTurnBindingWire):
        if item.name.strip() and item.turn_name.strip():
            return item
        return None
    if not isinstance(item, Mapping):
        return None
    name = _trimmed_nonempty(item.get("name"))
    turn_name = _trimmed_nonempty(item.get("turn_name"))
    if name is None or turn_name is None:
        return None
    return WaitTurnBindingWire(name=name, turn_name=turn_name)


def _binding_from_record(item: object) -> WaitTurnBindingWire | None:
    if not isinstance(item, Mapping):
        return None
    if _trimmed_nonempty(item.get("target")) != "turn":
        return None
    history_only = item.get("history_only")
    if history_only is True or history_only == 1:
        return None
    turn_name = _trimmed_nonempty(item.get("turn_name"))
    if turn_name is None:
        return None
    name = _trimmed_nonempty(item.get("requested")) or _trimmed_nonempty(
        item.get("name")
    )
    if name is None:
        return None
    return WaitTurnBindingWire(name=name, turn_name=turn_name)


def _first_wins(bindings: Iterable[WaitTurnBindingWire]) -> list[WaitTurnBindingWire]:
    seen: set[str] = set()
    result: list[WaitTurnBindingWire] = []
    for binding in bindings:
        if binding.name in seen:
            continue
        seen.add(binding.name)
        result.append(binding)
        if len(result) >= _WAIT_TURN_BINDINGS_MAX_ENTRIES:
            break
    return result


def wait_turn_bindings_from_value(value: object) -> list[WaitTurnBindingWire]:
    """Coerce an explicit compact ``wait_turn_bindings`` list; never raises."""
    if not isinstance(value, list):
        return []
    return _first_wins(
        binding
        for item in value
        if (binding := _binding_from_compact(item)) is not None
    )


def _wait_turn_bindings_from_records(
    artifacts: object = None,
    fork_sources: object = None,
) -> list[WaitTurnBindingWire]:
    """Derive bindings from identity records; never raises."""
    derived: list[WaitTurnBindingWire] = []
    for source in (artifacts, fork_sources):
        if not isinstance(source, list):
            continue
        for item in source:
            binding = _binding_from_record(item)
            if binding is not None:
                derived.append(binding)
    return _first_wins(derived)


def wait_turn_bindings_from_payload(
    payload: Mapping[str, Any] | None,
) -> list[WaitTurnBindingWire]:
    """Prefer an explicit compact field, else derive from identity records."""
    if payload is None:
        return []
    if "wait_turn_bindings" in payload:
        return wait_turn_bindings_from_value(payload.get("wait_turn_bindings"))
    return _wait_turn_bindings_from_records(
        payload.get("wait_for_artifacts"),
        payload.get("wait_for_fork_sources"),
    )


__all__ = [
    "WaitTurnBindingWire",
    "format_wait_targets",
    "format_wait_turn_binding",
    "wait_turn_bindings_from_payload",
    "wait_turn_bindings_from_value",
]
