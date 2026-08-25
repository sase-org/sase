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


def test_resolve_audit_identity_prefers_agent_env() -> None:
    env = {"SASE_AGENT_NAME": "worker.agent", "SASE_ARTIFACTS_DIR": "/artifacts"}

    result = identity.resolve_audit_identity(env)

    assert result == identity.discover_agent_identity(env)
    assert result.source == "SASE_AGENT_NAME"


def test_resolve_audit_identity_falls_back_to_interactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity.getpass, "getuser", lambda: "bryan")

    result = identity.resolve_audit_identity({})

    assert result.source == "interactive"
    assert result.name == "bryan"
    assert result.artifacts_dir is None


def test_resolve_audit_identity_interactive_falls_back_to_user_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> str:
        raise OSError("no such user")

    monkeypatch.setattr(identity.getpass, "getuser", _raise)

    result = identity.resolve_audit_identity({"USER": "bugyi"})

    assert result.source == "interactive"
    assert result.name == "bugyi"


def test_resolve_audit_identity_interactive_defaults_to_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> str:
        raise OSError("no such user")

    monkeypatch.setattr(identity.getpass, "getuser", _raise)

    result = identity.resolve_audit_identity({})

    assert result.source == "interactive"
    assert result.name == "unknown"


def test_resolve_audit_identity_does_not_widen_agent_only_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(identity.getpass, "getuser", lambda: "bryan")
    env: dict[str, str] = {}

    assert identity.discover_agent_identity(env) is None
    with pytest.raises(identity.AgentIdentityError):
        identity.require_agent_identity(env)
