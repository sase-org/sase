"""Unit coverage for the ``fs`` trigger's host-side state-token computation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.axe.chop_policy import (
    _compute_fs_trigger_token,
    check_chop_trigger_runtime,
)
from sase.axe.config import ChopConfig


def test_missing_path_is_a_stable_token_not_an_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    token, error = _compute_fs_trigger_token([str(missing)])

    assert error is None
    assert token is not None
    first_token = token

    # A second call against the same still-missing path is stable.
    token_again, error_again = _compute_fs_trigger_token([str(missing)])
    assert error_again is None
    assert token_again == first_token


def test_file_token_changes_with_content_and_is_stable_otherwise(
    tmp_path: Path,
) -> None:
    watched = tmp_path / "watched.json"
    watched.write_text("{}", encoding="utf-8")

    token, error = _compute_fs_trigger_token([str(watched)])
    assert error is None

    same_token, same_error = _compute_fs_trigger_token([str(watched)])
    assert same_error is None
    assert same_token == token

    watched.write_text('{"changed": true}', encoding="utf-8")
    changed_token, changed_error = _compute_fs_trigger_token([str(watched)])
    assert changed_error is None
    assert changed_token != token


def test_directory_token_reflects_child_count(tmp_path: Path) -> None:
    watched_dir = tmp_path / "state"
    watched_dir.mkdir()

    empty_token, error = _compute_fs_trigger_token([str(watched_dir)])
    assert error is None

    (watched_dir / "one.json").write_text("{}", encoding="utf-8")
    one_child_token, error = _compute_fs_trigger_token([str(watched_dir)])
    assert error is None
    assert one_child_token != empty_token


def test_glob_watch_spec_matches_shallow_entries_only(tmp_path: Path) -> None:
    watched_dir = tmp_path / "state"
    watched_dir.mkdir()
    (watched_dir / "nested").mkdir()
    (watched_dir / "nested" / "deep.json").write_text("{}", encoding="utf-8")

    spec = {"path": str(watched_dir), "glob": "*.json"}
    baseline, error = _compute_fs_trigger_token([spec])
    assert error is None

    # A deeply nested match is invisible to a shallow (non-recursive) glob.
    unchanged, error = _compute_fs_trigger_token([spec])
    assert error is None
    assert unchanged == baseline

    (watched_dir / "top.json").write_text("{}", encoding="utf-8")
    with_match, error = _compute_fs_trigger_token([spec])
    assert error is None
    assert with_match != baseline


def test_relative_watch_path_resolves_against_sase_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    (home / "axe" / "lumberjacks").mkdir(parents=True)
    (home / "axe" / "lumberjacks" / "hooks.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("sase.axe.chop_policy.sase_home", lambda: home)

    token, error = _compute_fs_trigger_token(["axe/lumberjacks/hooks.json"])

    assert error is None
    assert token is not None


def test_unreadable_path_fails_open_with_an_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = tmp_path / "watched.json"
    watched.write_text("{}", encoding="utf-8")

    def _raise_permission_error(self: Path) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "exists", _raise_permission_error, raising=True)

    token, error = _compute_fs_trigger_token([str(watched)])

    assert token is None
    assert error is not None
    assert "permission denied" in error


def test_doctor_runtime_check_accepts_a_normal_or_missing_fs_watch_path(
    tmp_path: Path,
) -> None:
    chop = ChopConfig(
        name="hook_checks",
        description="",
        trigger={
            "provider": "fs",
            "paths": [str(tmp_path / "does-not-exist-yet")],
            "max_quiet": "60s",
        },
    )

    assert check_chop_trigger_runtime(chop) is None


def test_doctor_runtime_check_reports_an_unreadable_fs_watch_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watched = tmp_path / "watched.json"
    watched.write_text("{}", encoding="utf-8")
    chop = ChopConfig(
        name="hook_checks",
        description="",
        trigger={
            "provider": "fs",
            "paths": [str(watched)],
            "max_quiet": "60s",
        },
    )

    def _raise_permission_error(self: Path) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "exists", _raise_permission_error, raising=True)

    error = check_chop_trigger_runtime(chop)

    assert error is not None
    assert "permission denied" in error


def test_bare_string_and_object_watch_specs_combine_independently(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second_dir = tmp_path / "second"
    first.write_text("{}", encoding="utf-8")
    second_dir.mkdir()

    combined, error = _compute_fs_trigger_token([str(first), {"path": str(second_dir)}])
    assert error is None

    first_only, error = _compute_fs_trigger_token([str(first)])
    assert error is None
    assert combined != first_only
