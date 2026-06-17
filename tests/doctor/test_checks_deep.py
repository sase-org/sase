"""Tests for Phase 4 doctor deep checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.doctor.checks_deep import (
    _check_agent_index_verify,
    _check_axe_state,
    _check_provider_cli_versions,
)
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
        env={},
    )


def test_agent_index_verify_warns_on_drift(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep.default_agent_artifact_index_path",
        lambda: tmp_path / "index.sqlite",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep.sase_projects_dir",
        lambda: tmp_path / "projects",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep.verify_agent_artifact_index",
        lambda *_args: SimpleNamespace(
            ok=False,
            schema_version=3,
            index_path="/tmp/index.sqlite",
            projects_root="/tmp/projects",
            indexed_rows=1,
            source_rows=2,
            stale_rows=0,
            missing_rows=1,
            extra_rows=0,
            corrupt_rows=0,
        ),
    )

    check = _check_agent_index_verify()

    assert check.status == "WARN"
    assert "missing_rows=1" in check.summary
    assert check.next_steps == ("Run `sase agent index gc`.",)


def test_provider_cli_versions_reports_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep.llm_registry.get_llm_metadata_payload",
        lambda: {
            "providers": {
                "codex": {
                    "autodetect_cli_name": "codex",
                    "known_model_names": [],
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep._resolve_executable",
        lambda _command: "/usr/bin/codex",
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep._run_version_probe",
        lambda _executable: {
            "probe_status": "ok",
            "detail": "codex 1.2.3",
            "version": "codex 1.2.3",
            "returncode": 0,
        },
    )

    check = _check_provider_cli_versions(_context(tmp_path))

    assert check.status == "OK"
    assert "1/1" in check.summary
    assert check.data["providers"][0]["version"] == "codex 1.2.3"


def test_axe_state_ok_when_no_lumberjack_status_files(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_deep.load_axe_config",
        lambda: SimpleNamespace(
            lumberjacks={"hooks": object()},
            max_hook_runners=3,
            max_agent_runners=3,
            zombie_timeout_seconds=7200,
        ),
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep.read_lumberjack_status",
        lambda _name: None,
    )
    monkeypatch.setattr(
        "sase.doctor.checks_deep.read_maintenance",
        lambda: None,
    )

    check = _check_axe_state()

    assert check.status == "OK"
    assert "1 configured" in check.summary
