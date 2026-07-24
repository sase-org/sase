"""Persistence coverage for the Admin Center resume tab."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.modals import config_center_state
from sase.ace.tui.modals.config_center_state import (
    load_admin_center_last_tab,
    save_admin_center_last_tab,
)


def _use_sase_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


@pytest.mark.parametrize(
    "tab",
    ["config", "logs", "projects", "statistics", "tasks", "updates", "xprompts"],
)
def test_valid_tabs_round_trip_with_exact_wire_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tab: Any,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)

    save_admin_center_last_tab(tab)

    path = home / "ace_admin_center_last_tab.txt"
    assert config_center_state._admin_center_last_tab_path() == path
    assert path.read_bytes() == f"{tab}\n".encode()
    assert load_admin_center_last_tab() == tab


def test_missing_and_unreadable_state_return_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_sase_home(monkeypatch, tmp_path)
    assert load_admin_center_last_tab() is None

    class _UnreadablePath:
        def open(self, _mode: str) -> Any:
            raise OSError("synthetic unreadable state")

    monkeypatch.setattr(
        config_center_state,
        "_admin_center_last_tab_path",
        lambda: _UnreadablePath(),
    )
    assert load_admin_center_last_tab() is None


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"missing\n",
        b"tasks",
        b"tasks\nlogs\n",
        b"\xff\n",
        b"x" * 65,
    ],
)
def test_malformed_or_oversized_state_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    content: bytes,
) -> None:
    home = _use_sase_home(monkeypatch, tmp_path)
    home.mkdir(parents=True)
    (home / "ace_admin_center_last_tab.txt").write_bytes(content)

    assert load_admin_center_last_tab() is None


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

    save_admin_center_last_tab("tasks")

    assert len(replacements) == 1
    assert replacements[0][1] == path
    assert path.read_text() == "tasks\n"
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
        save_admin_center_last_tab("tasks")

    assert path.read_text() == "logs\n"
    assert not list(home.glob(f".{path.name}.*.tmp"))


def test_save_rejects_non_catalog_tab(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_sase_home(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="invalid Admin Center tab"):
        save_admin_center_last_tab("missing")  # type: ignore[arg-type]
