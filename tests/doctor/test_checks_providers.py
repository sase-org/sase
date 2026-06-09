"""Tests for Phase 3 doctor provider checks."""

from __future__ import annotations

import stat
from pathlib import Path

from sase.doctor.checks_providers import _check_llm_default, _check_llm_registry
from sase.doctor.runner import DoctorContext


def _payload() -> dict[str, object]:
    return {
        "providers": {
            "codex": {
                "known_model_names": ["gpt-5.5"],
                "autodetect_cli_name": "codex",
                "model_resolutions": {"large": "gpt-5.5"},
            }
        },
        "autodetect_candidates": [
            {"priority": 10, "provider": "codex", "cli_name": "codex"}
        ],
    }


def _autodetect_payload() -> dict[str, object]:
    return {
        "providers": {
            "codex": {
                "known_model_names": ["gpt-5.5"],
                "autodetect_cli_name": "codex",
                "model_resolutions": {"large": "gpt-5.5"},
            },
            "gemini": {
                "known_model_names": ["gemini-3-flash-preview"],
                "autodetect_cli_name": "gemini",
                "model_resolutions": {"large": "gemini-3-flash-preview"},
            },
        },
        "autodetect_candidates": [
            {"priority": 10, "provider": "codex", "cli_name": "codex"},
            {"priority": 30, "provider": "gemini", "cli_name": "gemini"},
        ],
    }


def _context(tmp_path: Path, env: dict[str, str] | None = None) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env=env or {},
    )


def test_llm_registry_reports_metadata_load_failure(monkeypatch) -> None:
    def fail() -> dict[str, object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        fail,
    )

    check = _check_llm_registry()

    assert check.status == "ERROR"
    assert "metadata could not be loaded" in check.summary
    assert "boom" in check.details[0]


def test_llm_default_errors_when_selected_cli_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        lambda: "codex",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {"provider": "codex"},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )
    monkeypatch.setattr("sase.doctor.checks_providers.shutil.which", lambda _: None)

    check = _check_llm_default(_context(tmp_path))

    assert check.status == "ERROR"
    assert "codex" in check.summary
    assert "executable" in check.summary
    assert "SASE_CODEX_PATH" in check.next_steps[0]
    assert check.data["selection_source"] == "config"
    assert check.data["auth_status"] == "not_verified"
    assert check.data["auth_verified"] is False
    assert check.data["setup_hint"]["tool"] == "Codex CLI"


def test_llm_default_errors_when_autodetect_finds_no_cli(monkeypatch, tmp_path) -> None:
    def fail_default() -> str:
        raise RuntimeError("No LLM provider is available")

    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _autodetect_payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        fail_default,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )
    monkeypatch.setattr("sase.doctor.checks_providers.shutil.which", lambda _: None)

    check = _check_llm_default(_context(tmp_path))

    readiness = {row["provider"]: row for row in check.data["provider_readiness"]}
    assert check.status == "ERROR"
    assert "no usable default" in check.summary
    assert check.data["provider"] is None
    assert check.data["selection_source"] == "autodetect"
    assert readiness["codex"]["ready"] is False
    assert readiness["gemini"]["cli_name"] == "gemini"
    assert readiness["gemini"]["ready"] is False
    assert "Codex CLI setup" in check.next_steps[0]
    assert "auth: not verified" in check.details[-1]


def test_llm_default_accepts_configured_executable_path(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "codex"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_llm_metadata_payload",
        _payload,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.llm_registry.get_default_provider_name",
        lambda: "codex",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_llm_provider_config",
        lambda: {"provider": "codex"},
    )
    monkeypatch.setattr(
        "sase.doctor.checks_providers.get_active_temporary_override",
        lambda: None,
    )

    check = _check_llm_default(_context(tmp_path, {"SASE_CODEX_PATH": str(exe)}))

    assert check.status == "OK"
    assert check.data["configured_command"] == str(exe)
    assert check.data["command"] == str(exe)
    assert check.data["executable"] == str(exe)
    assert check.data["ready"] is True
    assert check.data["auth_status"] == "not_verified"
