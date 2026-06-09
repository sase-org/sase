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
    assert check.data["executable"] == str(exe)
