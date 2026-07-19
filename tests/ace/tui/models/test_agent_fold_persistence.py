"""Tests for the bounded, versioned Agents-fold persistence format."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_fold_persistence as persistence
from sase.ace.tui.models.agent_fold_persistence import (
    AgentGroupingFoldSnapshot,
    AgentsFoldStateSnapshot,
    EMPTY_AGENTS_FOLD_STATE,
    load_agents_fold_state,
    save_agents_fold_state,
    _serialize_agents_fold_state,
)
from sase.ace.tui.models.agent_group_fold import (
    AgentPanelFoldScope,
    AgentPanelFoldSnapshot,
)
from sase.ace.tui.models.agent_groups import GroupingMode


def _scope(
    panel_key: str | None,
    *keys: tuple[str, ...],
    merged: bool = False,
) -> AgentPanelFoldSnapshot:
    return AgentPanelFoldSnapshot(
        AgentPanelFoldScope(panel_key, merged=merged),
        frozenset(keys),
    )


def _full_snapshot() -> AgentsFoldStateSnapshot:
    return AgentsFoldStateSnapshot(
        collapsed_panels=frozenset({None, "chop"}),
        group_folds=(
            AgentGroupingFoldSnapshot(
                GroupingMode.STANDARD,
                (
                    _scope(None, ("sase",), ("sase", "")),
                    _scope("chop", ("sase", "agent")),
                    _scope(None, ("merged",), merged=True),
                ),
            ),
            AgentGroupingFoldSnapshot(
                GroupingMode.BY_DATE,
                (_scope(None, ("Today",), ("Earlier", "2026-W28")),),
            ),
            AgentGroupingFoldSnapshot(
                GroupingMode.BY_STATUS,
                (_scope(None, ("Done",)),),
            ),
        ),
    )


def test_deterministic_round_trip_covers_modes_panels_and_layouts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "folds.json"
    snapshot = _full_snapshot()

    save_agents_fold_state(snapshot, path)

    assert load_agents_fold_state(path) == snapshot
    first = path.read_text()
    save_agents_fold_state(snapshot, path)
    assert path.read_text() == first
    assert '"kind":"no_tribe"' in first
    assert '"kind":"tribe","tribe":"chop"' in first
    assert '"tag"' not in first
    assert '"merged":true' in first


def test_empty_state_omits_empty_collections() -> None:
    assert _serialize_agents_fold_state(EMPTY_AGENTS_FOLD_STATE) == (
        '{"schema_version":2}\n'
    )


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"schema_version": 999}),
        json.dumps(
            {
                "schema_version": 2,
                "group_folds": [
                    {
                        "mode": "by_status",
                        "scopes": [
                            {
                                "panel": {"kind": "no_tribe"},
                                "merged": False,
                                "collapsed": [],
                            }
                        ],
                    }
                ],
            }
        ),
        json.dumps(
            {
                "schema_version": 2,
                "collapsed_panels": [{"kind": "tribe", "tribe": 7}],
            }
        ),
    ],
)
def test_invalid_or_future_state_fails_open(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "folds.json"
    path.write_text(payload)

    assert load_agents_fold_state(path) == EMPTY_AGENTS_FOLD_STATE


def test_missing_and_oversized_state_fail_open(tmp_path: Path) -> None:
    path = tmp_path / "folds.json"
    assert load_agents_fold_state(path) == EMPTY_AGENTS_FOLD_STATE

    path.write_bytes(b" " * (persistence.MAX_FILE_BYTES + 1))
    assert load_agents_fold_state(path) == EMPTY_AGENTS_FOLD_STATE


def test_legacy_v1_tag_panel_discriminators_load_and_rewrite_as_tribes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "folds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "collapsed_panels": [
                    {"kind": "untagged"},
                    {"kind": "tag", "tag": "chop"},
                ],
                "group_folds": [
                    {
                        "mode": "by_status",
                        "scopes": [
                            {
                                "panel": {"kind": "tag", "tag": "chop"},
                                "merged": False,
                                "collapsed": [["Done"]],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_agents_fold_state(path)
    assert loaded.collapsed_panels == frozenset({None, "chop"})
    assert loaded.group_folds[0].scopes[0].scope.panel_key == "chop"

    save_agents_fold_state(loaded, path)

    rewritten = path.read_text(encoding="utf-8")
    assert '"schema_version":2' in rewritten
    assert '"kind":"no_tribe"' in rewritten
    assert '"kind":"tribe","tribe":"chop"' in rewritten
    assert '"tag"' not in rewritten


def test_atomic_save_failure_removes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "folds.json"

    def _fail_replace(_source: str, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(persistence.os, "replace", _fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        save_agents_fold_state(_full_snapshot(), path)

    assert not path.exists()
    assert list(tmp_path.iterdir()) == []
