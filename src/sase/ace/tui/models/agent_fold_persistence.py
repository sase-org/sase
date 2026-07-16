"""Versioned persistence for Agents-tab group and whole-panel folds.

The TUI owns lifecycle scheduling; this module is deliberately synchronous and
side-effect free except for its explicit load/save functions so callers can run
all file and JSON work through ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from .agent_group_fold import AgentPanelFoldScope, AgentPanelFoldSnapshot
from .agent_groups import GroupingMode
from .agent_panels import PanelKey
from .group_fold import GroupKey

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FILENAME = "ace_agents_fold_state.json"
MAX_FILE_BYTES = 256 * 1024
MAX_COLLAPSED_PANELS = 256
MAX_GROUPING_ENTRIES = len(GroupingMode)
MAX_SCOPES = 512
MAX_COLLAPSED_GROUP_KEYS = 4096
MAX_GROUP_KEY_DEPTH = 32
MAX_STRING_LENGTH = 1024


@dataclass(frozen=True)
class AgentGroupingFoldSnapshot:
    """Immutable group-fold state for one grouping mode."""

    mode: GroupingMode
    scopes: tuple[AgentPanelFoldSnapshot, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scopes",
            tuple(
                sorted(
                    self.scopes,
                    key=lambda item: (
                        item.scope.merged,
                        item.scope.panel_key is not None,
                        item.scope.panel_key or "",
                    ),
                )
            ),
        )


@dataclass(frozen=True)
class AgentsFoldStateSnapshot:
    """Complete persisted Agents-tab collapse intent."""

    collapsed_panels: frozenset[PanelKey] = frozenset()
    group_folds: tuple[AgentGroupingFoldSnapshot, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "group_folds",
            tuple(sorted(self.group_folds, key=lambda item: item.mode.value)),
        )


EMPTY_AGENTS_FOLD_STATE = AgentsFoldStateSnapshot()


class _AgentsFoldStateDecodeError(ValueError):
    """Raised internally when a persisted snapshot fails validation."""


def _agents_fold_state_path() -> Path:
    """Return the global ACE Agents-fold state path."""
    return sase_home() / FILENAME


def _decode_panel_key(raw: Any) -> PanelKey:
    if not isinstance(raw, dict):
        raise _AgentsFoldStateDecodeError("panel key must be an object")
    kind = raw.get("kind")
    if kind == "untagged" and set(raw) == {"kind"}:
        return None
    if kind == "tag" and set(raw) == {"kind", "tag"}:
        tag = raw.get("tag")
        if isinstance(tag, str) and bool(tag) and len(tag) <= MAX_STRING_LENGTH:
            return tag
    raise _AgentsFoldStateDecodeError("invalid panel key")


def _encode_panel_key(panel_key: PanelKey) -> dict[str, str]:
    if panel_key is None:
        return {"kind": "untagged"}
    return {"kind": "tag", "tag": panel_key}


def _decode_group_key(raw: Any) -> GroupKey:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_GROUP_KEY_DEPTH:
        raise _AgentsFoldStateDecodeError("invalid group-key depth")
    components: list[str] = []
    for component in raw:
        if not isinstance(component, str) or len(component) > MAX_STRING_LENGTH:
            raise _AgentsFoldStateDecodeError("invalid group-key component")
        components.append(component)
    return tuple(components)


def _decode_agents_fold_state(raw: Any) -> AgentsFoldStateSnapshot:
    """Validate a decoded JSON value and return a fully immutable snapshot."""
    if not isinstance(raw, dict):
        raise _AgentsFoldStateDecodeError("root must be an object")
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise _AgentsFoldStateDecodeError("unknown schema version")
    if not set(raw).issubset({"schema_version", "collapsed_panels", "group_folds"}):
        raise _AgentsFoldStateDecodeError("unknown root field")

    raw_panels = raw.get("collapsed_panels", [])
    if not isinstance(raw_panels, list) or len(raw_panels) > MAX_COLLAPSED_PANELS:
        raise _AgentsFoldStateDecodeError("invalid collapsed-panels collection")
    collapsed_panels: set[PanelKey] = set()
    for raw_panel in raw_panels:
        panel_key = _decode_panel_key(raw_panel)
        if panel_key in collapsed_panels:
            raise _AgentsFoldStateDecodeError("duplicate collapsed panel")
        collapsed_panels.add(panel_key)

    raw_group_folds = raw.get("group_folds", [])
    if (
        not isinstance(raw_group_folds, list)
        or len(raw_group_folds) > MAX_GROUPING_ENTRIES
    ):
        raise _AgentsFoldStateDecodeError("invalid group-fold collection")

    group_folds: list[AgentGroupingFoldSnapshot] = []
    seen_modes: set[GroupingMode] = set()
    total_scopes = 0
    total_keys = 0
    for raw_mode_entry in raw_group_folds:
        if not isinstance(raw_mode_entry, dict) or set(raw_mode_entry) != {
            "mode",
            "scopes",
        }:
            raise _AgentsFoldStateDecodeError("invalid grouping entry")
        raw_mode = raw_mode_entry.get("mode")
        if not isinstance(raw_mode, str):
            raise _AgentsFoldStateDecodeError("grouping mode must be a string")
        try:
            mode = GroupingMode(raw_mode)
        except ValueError as exc:
            raise _AgentsFoldStateDecodeError("unknown grouping mode") from exc
        if mode in seen_modes:
            raise _AgentsFoldStateDecodeError("duplicate grouping mode")
        seen_modes.add(mode)

        raw_scopes = raw_mode_entry.get("scopes")
        if not isinstance(raw_scopes, list) or not raw_scopes:
            raise _AgentsFoldStateDecodeError("scopes must be a non-empty list")
        total_scopes += len(raw_scopes)
        if total_scopes > MAX_SCOPES:
            raise _AgentsFoldStateDecodeError("too many scopes")
        scopes: list[AgentPanelFoldSnapshot] = []
        seen_scopes: set[AgentPanelFoldScope] = set()
        for raw_scope in raw_scopes:
            if not isinstance(raw_scope, dict) or set(raw_scope) != {
                "collapsed",
                "merged",
                "panel",
            }:
                raise _AgentsFoldStateDecodeError("invalid scope entry")
            merged = raw_scope.get("merged")
            if not isinstance(merged, bool):
                raise _AgentsFoldStateDecodeError("merged must be boolean")
            scope = AgentPanelFoldScope(
                panel_key=_decode_panel_key(raw_scope.get("panel")),
                merged=merged,
            )
            if scope in seen_scopes:
                raise _AgentsFoldStateDecodeError("duplicate panel scope")
            seen_scopes.add(scope)
            raw_keys = raw_scope.get("collapsed")
            if not isinstance(raw_keys, list) or not raw_keys:
                raise _AgentsFoldStateDecodeError("collapsed keys must be non-empty")
            total_keys += len(raw_keys)
            if total_keys > MAX_COLLAPSED_GROUP_KEYS:
                raise _AgentsFoldStateDecodeError("too many collapsed group keys")
            collapsed = frozenset(_decode_group_key(key) for key in raw_keys)
            if len(collapsed) != len(raw_keys):
                raise _AgentsFoldStateDecodeError("duplicate collapsed group key")
            scopes.append(AgentPanelFoldSnapshot(scope, collapsed))
        if scopes:
            group_folds.append(AgentGroupingFoldSnapshot(mode, tuple(scopes)))

    return AgentsFoldStateSnapshot(
        collapsed_panels=frozenset(collapsed_panels),
        group_folds=tuple(group_folds),
    )


def _panel_sort_key(panel_key: PanelKey) -> tuple[int, str]:
    return (0, "") if panel_key is None else (1, panel_key)


def _encode_agents_fold_state(snapshot: AgentsFoldStateSnapshot) -> dict[str, Any]:
    """Return the deterministic JSON object for *snapshot*."""
    payload: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    if snapshot.collapsed_panels:
        payload["collapsed_panels"] = [
            _encode_panel_key(key)
            for key in sorted(snapshot.collapsed_panels, key=_panel_sort_key)
        ]

    group_folds: list[dict[str, Any]] = []
    for mode_snapshot in sorted(snapshot.group_folds, key=lambda item: item.mode.value):
        scopes: list[dict[str, Any]] = []
        for panel_snapshot in sorted(
            mode_snapshot.scopes,
            key=lambda item: (
                item.scope.merged,
                *_panel_sort_key(item.scope.panel_key),
            ),
        ):
            if not panel_snapshot.collapsed:
                continue
            scopes.append(
                {
                    "collapsed": [
                        list(key) for key in sorted(panel_snapshot.collapsed)
                    ],
                    "merged": panel_snapshot.scope.merged,
                    "panel": _encode_panel_key(panel_snapshot.scope.panel_key),
                }
            )
        if scopes:
            group_folds.append({"mode": mode_snapshot.mode.value, "scopes": scopes})
    if group_folds:
        payload["group_folds"] = group_folds
    return payload


def _serialize_agents_fold_state(snapshot: AgentsFoldStateSnapshot) -> str:
    """Serialize *snapshot* with stable ordering and compact separators."""
    payload = _encode_agents_fold_state(snapshot)
    # Keep writer and reader bounds identical so an oversized in-memory state
    # can never replace a previously valid file with one the next session must
    # reject. This validation runs only in the off-thread writer.
    _decode_agents_fold_state(payload)
    serialized = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    if len(serialized.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError("Agents fold state exceeds maximum file size")
    return serialized


def load_agents_fold_state(path: Path | None = None) -> AgentsFoldStateSnapshot:
    """Load and defensively decode the fold snapshot, failing open to empty."""
    state_path = path or _agents_fold_state_path()
    try:
        with state_path.open("rb") as stream:
            raw_bytes = stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        log.debug("Agents fold state is missing: %s", state_path)
        return EMPTY_AGENTS_FOLD_STATE
    except OSError:
        log.warning("Unable to read Agents fold state: %s", state_path, exc_info=True)
        return EMPTY_AGENTS_FOLD_STATE
    if len(raw_bytes) > MAX_FILE_BYTES:
        log.warning("Ignoring oversized Agents fold state: %s", state_path)
        return EMPTY_AGENTS_FOLD_STATE
    try:
        decoded = json.loads(raw_bytes.decode("utf-8"))
        return _decode_agents_fold_state(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, _AgentsFoldStateDecodeError):
        log.warning(
            "Ignoring malformed Agents fold state: %s", state_path, exc_info=True
        )
        return EMPTY_AGENTS_FOLD_STATE


def save_agents_fold_state(
    snapshot: AgentsFoldStateSnapshot,
    path: Path | None = None,
) -> None:
    """Atomically save *snapshot* using a same-directory temporary file."""
    state_path = path or _agents_fold_state_path()
    payload = _serialize_agents_fold_state(snapshot)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=state_path.parent,
        prefix=f".{state_path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        os.replace(temporary, state_path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


__all__ = [
    "AgentGroupingFoldSnapshot",
    "AgentsFoldStateSnapshot",
    "EMPTY_AGENTS_FOLD_STATE",
    "MAX_FILE_BYTES",
    "SCHEMA_VERSION",
    "load_agents_fold_state",
    "save_agents_fold_state",
]
