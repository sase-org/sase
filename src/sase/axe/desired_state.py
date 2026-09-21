"""Persistent desired-state marker for the axe daemon."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import sase.axe.state as _state


AxeDesiredStateValue = Literal["running", "stopped"]


@dataclass(frozen=True)
class _AxeDesiredState:
    """The operator's last requested axe lifecycle state."""

    state: AxeDesiredStateValue
    source: str
    timestamp: str


def _desired_state_path() -> Path:
    """Return the desired-state marker path."""
    return _state.axe_state_dir() / "desired_state.json"


def write_desired_state(
    state: AxeDesiredStateValue,
    *,
    source: str,
    timestamp: str | None = None,
) -> _AxeDesiredState:
    """Atomically persist the requested axe lifecycle state."""
    marker = _AxeDesiredState(
        state=state,
        source=source,
        timestamp=timestamp or _state.get_timestamp(),
    )
    _state.atomic_write_json(_desired_state_path(), asdict(marker))
    return marker


def read_desired_state() -> _AxeDesiredState | None:
    """Read and validate the desired-state marker, if one exists."""
    data = _state.read_json(_desired_state_path())
    if not isinstance(data, dict):
        return None
    state = data.get("state")
    source = data.get("source")
    timestamp = data.get("timestamp")
    if state not in {"running", "stopped"}:
        return None
    if not isinstance(source, str) or not source:
        return None
    if not isinstance(timestamp, str) or not timestamp:
        return None
    return _AxeDesiredState(state=state, source=source, timestamp=timestamp)


__all__ = [
    "AxeDesiredStateValue",
    "read_desired_state",
    "write_desired_state",
]
