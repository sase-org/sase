"""Public ``sase flag enable`` / ``disable`` journeys through ``sase.main.entry``."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.config import core as config_core
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
_PYTEST_SANDBOX_DIR_ENV_VAR = "SASE_PYTEST_SANDBOX_DIR"


@pytest.fixture(autouse=True)
def _clean_flag_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    reset_process_feature_flags()
    yield
    reset_process_feature_flags()


def _fingerprint(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


def _resolve_config_dir_inside_pytest_sandbox(config_dir: Path) -> Path:
    sandbox_value = os.environ.get(_PYTEST_SANDBOX_DIR_ENV_VAR)
    assert sandbox_value, (
        f"{_PYTEST_SANDBOX_DIR_ENV_VAR} is required before seeding config files"
    )

    sandbox_path = Path(sandbox_value)
    assert sandbox_path.is_absolute(), (
        f"{_PYTEST_SANDBOX_DIR_ENV_VAR} must be an absolute path: {sandbox_value!r}"
    )

    try:
        sandbox = sandbox_path.resolve(strict=True)
        resolved = config_dir.resolve(strict=False)
        resolved.relative_to(sandbox)
    except (OSError, RuntimeError, ValueError) as exc:
        raise AssertionError(
            f"refusing to seed config outside pytest sandbox {sandbox_path}: "
            f"{config_dir}"
        ) from exc

    assert sandbox.is_dir(), (
        f"{_PYTEST_SANDBOX_DIR_ENV_VAR} must name an existing directory: {sandbox}"
    )
    return resolved


def _seed_portable_config(config_dir: Path) -> dict[Path, tuple[bytes, int]]:
    config_dir = _resolve_config_dir_inside_pytest_sandbox(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    user = config_dir / "sase.yml"
    overlay = config_dir / "sase_extra.yml"
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


def test_seed_portable_config_requires_pytest_sandbox_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.delenv(_PYTEST_SANDBOX_DIR_ENV_VAR, raising=False)

    with pytest.raises(AssertionError, match=_PYTEST_SANDBOX_DIR_ENV_VAR):
        _seed_portable_config(config_dir)

    assert not config_dir.exists()


def test_seed_portable_config_rejects_config_dir_outside_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    config_dir = tmp_path / "outside" / ".config" / "sase"
    monkeypatch.setenv(_PYTEST_SANDBOX_DIR_ENV_VAR, str(sandbox))

    with pytest.raises(AssertionError, match="outside pytest sandbox"):
        _seed_portable_config(config_dir)

    assert not config_dir.exists()


def test_public_enable_then_disable_writes_state_and_leaves_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fingerprints = _seed_portable_config(config_core.CONFIG_DIR)
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
    fingerprints = _seed_portable_config(config_core.CONFIG_DIR)

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
