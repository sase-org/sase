"""Public ``sase flag enable`` / ``disable`` journeys through ``sase.main.entry``."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.config.core import CONFIG_DIR
from sase.feature_flags.cli_set import ACE_RESTART_NOTICE, SET_JSON_SCHEMA_VERSION
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV, parse_feature_flags_env
from sase.feature_flags.snapshot import current_flags
from sase.feature_flags.state import (
    FEATURE_FLAG_STATE_FILENAME,
    feature_flag_state_path,
    load_saved_feature_flags,
    set_saved_feature_flag,
)
from sase.main.entry import main as sase_main
from sase.main.update_types import RestartInfo
from tests._conftest_runtime import reset_process_feature_flags

KEY = "ref_sync_gesture"
ROLLOUT = "admin_center_flags"


@pytest.fixture(autouse=True)
def _clean_flag_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    reset_process_feature_flags()
    yield
    reset_process_feature_flags()


def _fingerprint(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


def _seed_portable_config() -> dict[Path, tuple[bytes, int]]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    user = CONFIG_DIR / "sase.yml"
    overlay = CONFIG_DIR / "sase_extra.yml"
    user.write_text("feature_flags:\n  ref_sync_gesture: true\n", encoding="utf-8")
    overlay.write_text("timezone: UTC\n", encoding="utf-8")
    return {path: _fingerprint(path) for path in (user, overlay)}


def _skip_restart(**_kwargs: object) -> RestartInfo:
    return RestartInfo(
        attempted=False,
        status="skipped_not_running",
        reason="axe is not running",
    )


def _fail_restart(**_kwargs: object) -> RestartInfo:
    return RestartInfo(
        attempted=True,
        status="failed",
        message="daemon refused",
    )


def _run_public(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    *,
    restart: object = _skip_restart,
) -> tuple[int | str | None, str, str]:
    monkeypatch.setattr(sys, "argv", ["sase", *argv])
    monkeypatch.setattr(
        "sase.feature_flags.cli_set.restart_after_update",
        restart,
    )
    with pytest.raises(SystemExit) as exc_info:
        sase_main()
    captured = capsys.readouterr()
    return exc_info.value.code, captured.out, captured.err


def test_public_enable_then_disable_writes_state_and_leaves_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fingerprints = _seed_portable_config()
    sources: list[str] = []

    def capture_restart(*, source: str = "", **_kwargs: object) -> RestartInfo:
        sources.append(source)
        return _skip_restart()

    code, out, err = _run_public(
        monkeypatch,
        capsys,
        ["flag", "enable", KEY, "--json"],
        restart=capture_restart,
    )
    payload = json.loads(out)

    assert code == 0
    assert err == ""
    assert payload["schema_version"] == SET_JSON_SCHEMA_VERSION
    assert payload["command"] == "enable"
    assert payload["ok"] is True
    assert payload["mutation"]["key"] == KEY
    assert payload["mutation"]["enabled"] is True
    assert payload["mutation"]["changed"] is True
    assert payload["mutation"]["after"]["enabled"] is True
    assert FEATURE_FLAG_STATE_FILENAME in payload["mutation"]["state_path"]
    assert payload["restart"]["status"] == "skipped_not_running"
    assert sources == ["sase flag enable"]
    assert parse_feature_flags_env(os.environ[SASE_FEATURE_FLAGS_ENV])[KEY] is True

    loaded = load_saved_feature_flags()
    assert loaded.flags[KEY] is True
    raw = json.loads(Path(feature_flag_state_path()).read_text(encoding="utf-8"))
    assert raw["flags"][KEY] is True
    for path, fingerprint in fingerprints.items():
        assert _fingerprint(path) == fingerprint

    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    reset_process_feature_flags()
    saved_decision = current_flags().decision(KEY)
    assert saved_decision.enabled is True
    assert saved_decision.source == "state"

    code, out, err = _run_public(
        monkeypatch,
        capsys,
        ["flag", "disable", KEY],
        restart=capture_restart,
    )
    assert code == 0
    assert KEY in out
    assert "disabled" in out
    assert ACE_RESTART_NOTICE in out
    assert "AXE is not running; left stopped." in out
    assert load_saved_feature_flags().flags[KEY] is False
    assert sources == ["sase flag enable", "sase flag disable"]
    for path, fingerprint in fingerprints.items():
        assert _fingerprint(path) == fingerprint


def test_public_restart_failure_keeps_saved_preference(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fingerprints = _seed_portable_config()

    code, out, err = _run_public(
        monkeypatch,
        capsys,
        ["flag", "disable", KEY, "--json"],
        restart=_fail_restart,
    )
    payload = json.loads(out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["mutation"]["enabled"] is False
    assert payload["mutation"]["changed"] is True
    assert payload["restart"]["status"] == "failed"
    assert load_saved_feature_flags().flags[KEY] is False
    for path, fingerprint in fingerprints.items():
        assert _fingerprint(path) == fingerprint
    assert "daemon refused" in out or "failed" in out


def test_public_cli_works_when_flags_pane_rollout_is_off(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_saved_feature_flag(ROLLOUT, False)
    reset_process_feature_flags()

    code, out, _err = _run_public(
        monkeypatch,
        capsys,
        ["flag", "enable", KEY, "--json"],
    )
    payload = json.loads(out)

    assert code == 0
    assert payload["mutation"]["enabled"] is True
    loaded = load_saved_feature_flags()
    assert loaded.flags[ROLLOUT] is False
    assert loaded.flags[KEY] is True
