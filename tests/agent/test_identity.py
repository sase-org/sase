"""Direct coverage for observation-window resolution and its fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent import identity


def _env(artifacts_dir: Path) -> dict[str, str]:
    return {"SASE_AGENT_NAME": "worker.agent", "SASE_ARTIFACTS_DIR": str(artifacts_dir)}


def _write_meta(artifacts_dir: Path, run_started_at: object) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"run_started_at": run_started_at}), encoding="utf-8"
    )


def test_valid_zulu_instant_passes_through_unchanged(tmp_path: Path) -> None:
    _write_meta(tmp_path, "2026-08-10T09:00:00.123456Z")

    assert (
        identity.resolve_observation_window_start(_env(tmp_path))
        == "2026-08-10T09:00:00.123456Z"
    )


def test_valid_non_utc_offset_instant_passes_through_unchanged(tmp_path: Path) -> None:
    _write_meta(tmp_path, "2026-08-10T09:00:00-04:00")

    assert (
        identity.resolve_observation_window_start(_env(tmp_path))
        == "2026-08-10T09:00:00-04:00"
    )


def test_malformed_text_falls_back_to_current_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_meta(tmp_path, "not-an-instant")
    monkeypatch.setattr(
        identity, "current_instant", lambda: "2026-08-10T00:00:00.000000Z"
    )

    assert (
        identity.resolve_observation_window_start(_env(tmp_path))
        == "2026-08-10T00:00:00.000000Z"
    )


def test_offset_less_timestamp_falls_back_to_current_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_meta(tmp_path, "2026-08-10T09:00:00")
    monkeypatch.setattr(
        identity, "current_instant", lambda: "2026-08-10T00:00:00.000000Z"
    )

    assert (
        identity.resolve_observation_window_start(_env(tmp_path))
        == "2026-08-10T00:00:00.000000Z"
    )


def test_missing_run_started_at_falls_back_to_current_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "agent_meta.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(
        identity, "current_instant", lambda: "2026-08-10T00:00:00.000000Z"
    )

    assert (
        identity.resolve_observation_window_start(_env(tmp_path))
        == "2026-08-10T00:00:00.000000Z"
    )


def test_missing_agent_meta_file_falls_back_to_current_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unreadable_dir = tmp_path / "artifacts"
    monkeypatch.setattr(
        identity, "current_instant", lambda: "2026-08-10T00:00:00.000000Z"
    )

    assert (
        identity.resolve_observation_window_start(_env(unreadable_dir))
        == "2026-08-10T00:00:00.000000Z"
    )


def test_invalid_json_falls_back_to_current_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "agent_meta.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        identity, "current_instant", lambda: "2026-08-10T00:00:00.000000Z"
    )

    assert (
        identity.resolve_observation_window_start(_env(tmp_path))
        == "2026-08-10T00:00:00.000000Z"
    )


def test_human_environment_without_agent_identity_uses_current_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        identity, "current_instant", lambda: "2026-08-10T00:00:00.000000Z"
    )

    assert (
        identity.resolve_observation_window_start({}) == "2026-08-10T00:00:00.000000Z"
    )
