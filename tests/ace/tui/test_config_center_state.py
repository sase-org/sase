"""Persistence coverage for the Admin Center tab history pair."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.modals import config_center_state
from sase.ace.tui.modals.config_center_history import AdminCenterTabHistory
from sase.ace.tui.modals.config_center_state import (
    load_admin_center_tab_history,
    save_admin_center_tab_history,
)


def _use_sase_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


@pytest.mark.parametrize(
    "tab",
    ["config", "logs", "procs", "projects", "statistics", "updates", "xprompts"],
)
def test_valid_single_tab_round_trips_with_exact_wire_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tab: Any,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)

    save_admin_center_tab_history(AdminCenterTabHistory(current=tab))

    path = home / "ace_admin_center_last_tab.txt"
    assert config_center_state._admin_center_last_tab_path() == path
    assert path.read_bytes() == f"{tab}\n".encode()
    assert load_admin_center_tab_history() == AdminCenterTabHistory(current=tab)


def test_valid_pair_round_trips_with_exact_two_line_wire_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)

    save_admin_center_tab_history(
        AdminCenterTabHistory(current="procs", alternate="logs")
    )

    path = home / "ace_admin_center_last_tab.txt"
    assert path.read_bytes() == b"procs\nlogs\n"
    assert load_admin_center_tab_history() == AdminCenterTabHistory(
        current="procs", alternate="logs"
    )


def test_legacy_tasks_current_migrates_to_procs_on_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)
    home.mkdir(parents=True)
    (home / "ace_admin_center_last_tab.txt").write_bytes(b"tasks\n")

    assert load_admin_center_tab_history() == AdminCenterTabHistory(current="procs")


def test_legacy_tasks_alternate_migrates_to_procs_on_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)
    home.mkdir(parents=True)
    (home / "ace_admin_center_last_tab.txt").write_bytes(b"logs\ntasks\n")

    assert load_admin_center_tab_history() == AdminCenterTabHistory(
        current="logs", alternate="procs"
    )


def test_missing_and_unreadable_state_return_empty_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_sase_home(monkeypatch, tmp_path)
    assert load_admin_center_tab_history() == AdminCenterTabHistory()

    class _UnreadablePath:
        def open(self, _mode: str) -> Any:
            raise OSError("synthetic unreadable state")

    monkeypatch.setattr(
        config_center_state,
        "_admin_center_last_tab_path",
        lambda: _UnreadablePath(),
    )
    assert load_admin_center_tab_history() == AdminCenterTabHistory()


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"missing\n",
        b"tasks",
        b"tasks\nlogs\nconfig\n",
        b"tasks\nmissing\n",
        b"\xff\n",
        b"x" * 65,
    ],
)
def test_malformed_or_oversized_state_returns_empty_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: bytes,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)
    home.mkdir(parents=True)
    (home / "ace_admin_center_last_tab.txt").write_bytes(content)

    assert load_admin_center_tab_history() == AdminCenterTabHistory()


def test_degenerate_duplicate_pair_keeps_current_and_drops_alternate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)
    home.mkdir(parents=True)
    (home / "ace_admin_center_last_tab.txt").write_bytes(b"tasks\ntasks\n")

    assert load_admin_center_tab_history() == AdminCenterTabHistory(current="procs")


def test_save_atomically_replaces_existing_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)
    home.mkdir(parents=True)
    path = home / "ace_admin_center_last_tab.txt"
    path.write_text("logs\n")
    replacements: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def _replace(
        source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        source_path = Path(source)
        target_path = Path(target)
        replacements.append((source_path, target_path))
        assert source_path.parent == target_path.parent == home
        assert target_path.read_text() == "logs\n"
        real_replace(source_path, target_path)

    monkeypatch.setattr(config_center_state.os, "replace", _replace)

    save_admin_center_tab_history(AdminCenterTabHistory(current="procs"))

    assert len(replacements) == 1
    assert replacements[0][1] == path
    assert path.read_text() == "procs\n"
    assert not list(home.glob(f".{path.name}.*.tmp"))


def test_failed_replace_preserves_destination_and_cleans_temporary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)
    home.mkdir(parents=True)
    path = home / "ace_admin_center_last_tab.txt"
    path.write_text("logs\n")

    def _fail_replace(_source: object, _target: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(config_center_state.os, "replace", _fail_replace)

    with pytest.raises(OSError, match="synthetic replace failure"):
        save_admin_center_tab_history(AdminCenterTabHistory(current="procs"))

    assert path.read_text() == "logs\n"
    assert not list(home.glob(f".{path.name}.*.tmp"))


def test_save_rejects_non_catalog_current_tab(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_sase_home(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="invalid Admin Center tab"):
        save_admin_center_tab_history(
            AdminCenterTabHistory(current="missing")  # type: ignore[arg-type]
        )


def test_save_drops_alternate_matching_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)

    save_admin_center_tab_history(
        AdminCenterTabHistory(current="procs", alternate="procs")
    )

    path = home / "ace_admin_center_last_tab.txt"
    assert path.read_bytes() == b"procs\n"
    assert load_admin_center_tab_history() == AdminCenterTabHistory(current="procs")
