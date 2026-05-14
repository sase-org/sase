"""User-facing rollout diagnostics for daemon adoption."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.daemon import rollout_diagnostics as diagnostics
from sase.integrations import daemon_lifecycle as lifecycle
from tests._daemon_lifecycle_helpers import _args, _metadata, _write_metadata


def test_rollout_payload_reports_no_daemon_as_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "load_config_without_plugin_defaults",
        _minimal_rollout_config,
    )
    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(tmp_path / "run"))
    )

    payload = diagnostics.rollout_diagnostics_payload(
        inspection,
        args=_args(no_daemon=True),
    )

    assert payload["top_level"]["disabled"] is True
    assert payload["top_level"]["source"]["key"] == "--no-daemon"
    read_global = _surface(payload, "read.global")
    assert read_global["effective_mode"] == "disabled"
    assert read_global["blocked_reasons"] == ["top-level daemon escape hatch is active"]


def test_rollout_payload_reports_independent_m0_and_m1_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def config() -> dict[str, Any]:
        data = _minimal_rollout_config()
        data["daemon"]["rollout"]["milestones"]["m0_shadow_indexing"] = False
        data["daemon"]["rollout"]["milestones"]["m1_read_through"] = True
        return data

    monkeypatch.setattr(diagnostics, "load_config_without_plugin_defaults", config)
    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(tmp_path / "run"))
    )

    payload = diagnostics.rollout_diagnostics_payload(inspection, args=_args())

    assert (
        _surface(payload, "milestone.m0_shadow_indexing")["effective_mode"]
        == "disabled"
    )
    assert (
        _surface(payload, "milestone.m1_read_through")["effective_mode"]
        == "read_through"
    )
    assert _surface(payload, "read.global")["effective_mode"] == "read_through"

    def config_m1_disabled() -> dict[str, Any]:
        data = _minimal_rollout_config()
        data["daemon"]["rollout"]["milestones"]["m0_shadow_indexing"] = True
        data["daemon"]["rollout"]["milestones"]["m1_read_through"] = False
        return data

    monkeypatch.setattr(
        diagnostics,
        "load_config_without_plugin_defaults",
        config_m1_disabled,
    )

    payload = diagnostics.rollout_diagnostics_payload(inspection, args=_args())

    assert (
        _surface(payload, "milestone.m0_shadow_indexing")["effective_mode"] == "shadow"
    )
    read_global = _surface(payload, "read.global")
    assert read_global["effective_mode"] == "direct"
    assert "M1 read-through milestone is disabled" in read_global["blocked_reasons"]


def test_rollout_payload_includes_capabilities_compatibility_and_perf_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOSTNAME", "workstation.local")
    monkeypatch.setattr(
        diagnostics,
        "load_config_without_plugin_defaults",
        _minimal_rollout_config,
    )
    run_root = tmp_path / "run"
    _write_metadata(run_root, _metadata(os.getpid(), "workstation.local"))
    monkeypatch.setattr(
        lifecycle,
        "_try_health_rpc",
        lambda _socket: {
            "available": True,
            "health": {
                "status": "ok",
                "capabilities": ["changespecs.read", "notifications.read"],
                "compatibility": {
                    "supported_client_schema_range": {"min": 1, "max": 1},
                    "projection_read_schema_version": 1,
                    "projection_write_schema_version": 1,
                },
                "details": {
                    "indexing": {
                        "state": "ok",
                        "message": "shadow projections match source stores",
                    }
                },
            },
        },
    )
    report_path = tmp_path / "perf.json"
    report_path.write_text(
        json.dumps(
            {
                "perf_gates": {
                    "daemon_read.perf.changespecs": {"status": "ok", "p95_ms": 12}
                },
                "parity_gates": ["daemon_read.parity.changespecs"],
                "recovery_checks": ["sase.daemon.rebuild.surface.changespecs"],
                "docs_links": ["docs/perf_runbook.md#daemon-read-rollout"],
            }
        ),
        encoding="utf-8",
    )

    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(run_root))
    )
    payload = diagnostics.rollout_diagnostics_payload(
        inspection,
        args=_args(),
        benchmark_report_path=report_path,
    )

    assert payload["capabilities"]["observed"] == [
        "changespecs.read",
        "notifications.read",
    ]
    assert payload["compatibility"]["status"] == "ok"
    changespecs = _surface(payload, "read.changespecs")
    assert changespecs["effective_mode"] == "read_through"
    assert changespecs["parity_status"]["status"] == "ok"
    assert changespecs["perf_status"]["status"] == "ok"
    assert changespecs["fallback"]["command"] == "SASE_NO_DAEMON=1"


def test_rollout_payload_includes_m5_release_checklist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "load_config_without_plugin_defaults",
        _minimal_rollout_config,
    )
    inspection = lifecycle._inspect_daemon(
        _args(sase_home=str(tmp_path / "home"), run_root=str(tmp_path / "run"))
    )

    payload = diagnostics.rollout_diagnostics_payload(inspection, args=_args())

    provider_host = payload["provider_host"]
    assert provider_host["manifest_discovery"]["records"]
    assert provider_host["resource_policy"]["timeout"]["state"] == "active"

    checklist = payload["release_checklist"]
    assert (
        checklist["current_defaults"]["provider_host"]["modes"]["llm_metadata"]
        == "host-preferred"
    )
    assert "sase daemon rebuild --surface all" in checklist["migration_rebuild_steps"]
    assert "SASE_PROVIDER_HOST_MODE=direct" in checklist["rollback_commands"]
    assert "read.ace_agents" not in checklist["known_opt_in_surfaces"]
    assert checklist["supported_schema_ranges"]["sase_core_rs"]["dependency"] == (
        "sase-core-rs>=0.1.1,<0.2.0"
    )
    assert [
        item["milestone"] for item in checklist["required_ci_perf_soak_evidence"]
    ] == [
        "M0",
        "M1",
        "M2",
        "M3",
        "M4",
        "M5",
    ]


def test_rollout_handler_prints_json_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "load_config_without_plugin_defaults",
        _minimal_rollout_config,
    )

    code = lifecycle.handle_daemon_rollout(
        _args(
            sase_home=str(tmp_path / "home"),
            run_root=str(tmp_path / "run"),
            no_daemon=True,
            json_output=True,
        )
    )

    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["schema_version"] == 1
    assert out["top_level"]["disabled"] is True


def _surface(payload: dict[str, Any], surface_id: str) -> dict[str, Any]:
    for surface in payload["surfaces"]:
        if surface["surface_id"] == surface_id:
            return surface
    raise AssertionError(f"missing surface {surface_id}")


def _minimal_rollout_config() -> dict[str, Any]:
    return {
        "daemon": {
            "rollout": {
                "milestones": {
                    "m0_shadow_indexing": True,
                    "m1_read_through": True,
                }
            },
            "reads": {
                "enabled": True,
                "force_direct": False,
                "fallback_diagnostics": False,
                "surfaces": {
                    "changespecs": True,
                    "notifications": True,
                    "agents": True,
                    "beads": True,
                    "catalogs": True,
                    "ace_agents": False,
                    "ace_changespecs": False,
                    "ace_notifications": False,
                    "ace_artifacts": False,
                    "ace_archive_search": False,
                },
            },
            "scheduler": {
                "launch_mode": "direct",
                "lifecycle_mode": "direct",
                "axe_mode": "direct",
            },
            "provider_host": {
                "default_mode": "direct",
                "modes": {
                    "llm_metadata": "host-preferred",
                    "xprompt_catalog": "host-preferred",
                    "vcs_query": "host-preferred",
                    "workspace_metadata": "host-preferred",
                    "workspace_resolve_ref": "host-preferred",
                    "llm_invoke": "direct",
                    "workflow_step": "direct",
                    "vcs_mutation": "direct",
                },
            },
        }
    }
