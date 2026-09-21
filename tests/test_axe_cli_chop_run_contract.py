"""Tests for the axe_routine_job_contract upgrade path across the CLI surface."""

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from sase.axe.cli import (
    handle_axe_chop_doctor,
    handle_axe_chop_list,
    handle_axe_chop_run,
)
from sase.config.core import ConfigLayer
from sase.feature_flags import FeatureFlag, override_flags

pytest_plugins = ("tests._axe_cli_fixtures",)


def _make_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def test_routine_job_upgrade_contract_exercises_public_and_legacy_paths(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import UTC, datetime

    import sase.axe.status_collector as status_collector
    from sase.axe._process_types import AxeOrchestratorProbe
    from sase.axe.chop_agents import (
        build_chop_launch_env,
        get_chop_agent_records,
        record_chop_agent_launch_from_env,
    )
    from sase.axe.state import (
        chop_run_context_path,
        read_chop_run,
        read_chop_run_index,
    )

    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_executable(
        scripts_dir / "fixture_success",
        "#!/bin/sh\n"
        "printf 'routine=%s\\n' \"${SASE_JOB_ROUTINE:-missing}\"\n"
        "printf 'job=%s\\n' \"${SASE_JOB_NAME:-missing}\"\n"
        "printf 'legacy=%s/%s\\n' "
        '"${SASE_CHOP_LUMBERJACK:-missing}" "${SASE_CHOP_NAME:-missing}"\n'
        "printf 'target=%s\\n' \"${SASE_JOB_TARGET_NAME:-none}\"\n"
        "printf 'agent=%s\\n' \"${SASE_AGENT_NAME:-unset}\"\n",
    )
    _make_executable(scripts_dir / "sase_chop_legacy_only", "#!/bin/sh\ntrue\n")

    user_config = tmp_path / "sase.yml"
    user_config.write_text(
        "# keep bytes\n"
        "axe:\n"
        "  job_script_dirs:\n"
        f"    - {scripts_dir}\n"
        "  routines:\n"
        "    chop-watch:\n"
        "      description: Watch exact dotted jobs\n"
        "      interval: 5\n"
        "      job_timeout: 3s\n"
        "      jobs:\n"
        "        chop-test:\n"
        "          description: Shared public job name\n"
        "          script: fixture_success\n"
        "        exact.dotted:\n"
        "          description: Target-expanded dotted job\n"
        "          script: fixture_success\n"
        "          timeout: 2s\n"
        "          for_each:\n"
        "            - name: sase\n"
        "              workspace: gh:sase-org/sase\n"
        "        legacy.entry:\n"
        "          description: Old-only plugin entry point\n"
        "          script: sase_chop_legacy_only\n"
        "    other.routine:\n"
        "      description: Holds duplicate job name\n"
        "      interval: 7\n"
        "      jobs:\n"
        "        chop-test:\n"
        "          description: Duplicate public job name\n"
        "          script: fixture_success\n",
        encoding="utf-8",
    )
    original_config_bytes = user_config.read_bytes()
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "axe": {
                    "lumberjacks": {
                        "legacy-list": {
                            "description": "Legacy list-form routine",
                            "interval": 11,
                            "chops": [
                                {
                                    "name": "list.job",
                                    "description": "Legacy list-form job",
                                    "script": "fixture_success",
                                }
                            ],
                        }
                    }
                }
            },
        ),
        ConfigLayer(
            name="user",
            path=str(user_config),
            exists=True,
            list_strategy="replace",
            data=yaml.safe_load(user_config.read_text(encoding="utf-8")),
        ),
    ]

    monkeypatch.setattr("sase.axe.config.load_merged_config", lambda: {})
    monkeypatch.setattr("sase.axe.config.load_config_layers", lambda: layers)
    monkeypatch.setenv("SASE_AGENT_NAME", "ambient-parent")

    def capture_job_list_payload(
        *,
        axe_subcommand: str = "job",
        enabled: bool,
    ) -> dict[str, object]:
        with override_flags(axe_routine_job_contract=enabled) as flags:
            decision = flags.decision(FeatureFlag.axe_routine_job_contract)
            assert decision.enabled is enabled
            assert decision.source == "override"
            with pytest.raises(SystemExit) as exc_info:
                handle_axe_chop_list(
                    argparse.Namespace(
                        axe_subcommand=axe_subcommand,
                        json=True,
                        available=False,
                        verbose=False,
                    )
                )
            assert exc_info.value.code == 0
            return json.loads(capsys.readouterr().out)

    list_payload = capture_job_list_payload(enabled=True)
    disabled_job_payload = capture_job_list_payload(enabled=False)
    hidden_chop_payload = capture_job_list_payload(
        axe_subcommand="chop",
        enabled=True,
    )

    assert list_payload["schema_version"] == 2
    assert "jobs" in list_payload
    assert "chops" not in list_payload
    assert disabled_job_payload["schema_version"] == 1
    assert "chops" in disabled_job_payload
    assert "jobs" not in disabled_job_payload
    assert hidden_chop_payload["schema_version"] == 1
    assert "chops" in hidden_chop_payload
    assert "jobs" not in hidden_chop_payload
    configured = {
        (item["routine"], item["name"]): item
        for item in list_payload["jobs"]["configured"]
    }
    disabled_configured = {
        (item["lumberjack"], item["name"]): item
        for item in disabled_job_payload["chops"]["configured"]
    }
    expanded = configured[("chop-watch", "exact.dotted[sase]")]
    assert expanded["parent_name"] == "exact.dotted"
    assert expanded["target"]["workspace"] == "gh:sase-org/sase"
    assert configured[("chop-watch", "legacy.entry")]["script"] == (
        "sase_chop_legacy_only"
    )
    assert configured[("legacy-list", "list.job")]["script"] == "fixture_success"
    assert (
        disabled_configured[("chop-watch", "exact.dotted[sase]")]["parent_name"]
        == "exact.dotted"
    )
    assert disabled_configured[("chop-watch", "legacy.entry")]["script"] == (
        "sase_chop_legacy_only"
    )

    with override_flags(axe_routine_job_contract=True) as flags:
        decision = flags.decision(FeatureFlag.axe_routine_job_contract)
        assert decision.enabled is True
        assert decision.source == "override"
        with pytest.raises(SystemExit) as exc_info:
            handle_axe_chop_doctor(
                argparse.Namespace(
                    axe_subcommand="job",
                    json=True,
                    verbose=False,
                )
            )
        assert exc_info.value.code == 0
        doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["schema_version"] == 2
    assert "jobs" in doctor_payload
    assert "chops" not in doctor_payload

    with override_flags(axe_routine_job_contract=False) as flags:
        decision = flags.decision(FeatureFlag.axe_routine_job_contract)
        assert decision.enabled is False
        assert decision.source == "override"
        with pytest.raises(SystemExit) as exc_info:
            handle_axe_chop_doctor(
                argparse.Namespace(
                    axe_subcommand="job",
                    json=True,
                    verbose=False,
                )
            )
        assert exc_info.value.code == 0
        disabled_doctor_payload = json.loads(capsys.readouterr().out)
    assert disabled_doctor_payload["schema_version"] == 1
    assert "chops" in disabled_doctor_payload
    assert "jobs" not in disabled_doctor_payload
    assert any(
        check["id"] == "configured_job_scripts" and check["status"] == "OK"
        for check in doctor_payload["checks"]
    )
    assert any(
        check["id"] == "configured_chop_scripts" and check["status"] == "OK"
        for check in disabled_doctor_payload["checks"]
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_axe_chop_run(
            argparse.Namespace(
                chop_name="chop-test",
                routine=None,
                lumberjack=None,
                dry_run=False,
                chop_verbose=False,
                force=False,
            )
        )
    assert exc_info.value.code == 2
    ambiguous_error = capsys.readouterr().err
    assert "multiple routines" in ambiguous_error
    assert "--routine" in ambiguous_error

    with (
        override_flags(axe_routine_job_contract=True),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(
            argparse.Namespace(
                chop_name="exact.dotted[sase]",
                routine="chop-watch",
                lumberjack=None,
                dry_run=False,
                chop_verbose=False,
                force=False,
            )
        )
    assert exc_info.value.code == 0
    run_output = capsys.readouterr().out
    assert "routine=chop-watch" in run_output
    assert "job=exact.dotted[sase]" in run_output
    assert "legacy=chop-watch/exact.dotted[sase]" in run_output
    assert "target=sase" in run_output
    assert "agent=unset" in run_output
    assert user_config.read_bytes() == original_config_bytes

    run_ids = read_chop_run_index("chop-watch", "exact.dotted[sase]")
    assert len(run_ids) == 1
    entry = read_chop_run("chop-watch", "exact.dotted[sase]", run_ids[0])
    assert entry is not None
    assert entry.status == "success"
    assert entry.source == "oneshot"
    assert entry.started_by == "cli"
    assert entry.chop_name == "exact.dotted[sase]"
    context = json.loads(
        chop_run_context_path("chop-watch", "exact.dotted[sase]", run_ids[0]).read_text(
            encoding="utf-8"
        )
    )
    assert context["routine_name"] == "chop-watch"
    assert context["target"] == {"name": "sase", "workspace": "gh:sase-org/sase"}

    record_chop_agent_launch_from_env(
        pid=4321,
        project_file="/tmp/projects/sase/sase.sase",
        project_name="sase",
        workspace_num=15,
        workflow_name="ace(run)-260916_120000",
        cl_name="sase",
        timestamp="260916_120000",
        prompt="inspect",
        env=build_chop_launch_env(
            lumberjack_name="chop-watch",
            chop_name="exact.dotted[sase]",
            run_id=run_ids[0],
            prompt="inspect",
        ),
    )
    records = get_chop_agent_records(
        "chop-watch",
        chop_name="exact.dotted[sase]",
        run_id=run_ids[0],
    )
    assert [record.pid for record in records] == [4321]
    assert records[0].project_name == "sase"

    monkeypatch.setattr(
        status_collector,
        "probe_orchestrator",
        lambda *, cleanup: AxeOrchestratorProbe(
            lock_held=False,
            lock_holder_pid=None,
            orchestrator_pid_file_pid=None,
            legacy_pid=None,
            running_pid=None,
        ),
    )
    monkeypatch.setattr(
        status_collector, "count_hook_and_agent_runners_global", lambda: (0, 0)
    )
    monkeypatch.setattr(status_collector, "scheduler_desired_state", lambda: None)
    monkeypatch.setattr(status_collector, "read_maintenance", lambda: None)
    monkeypatch.setattr(
        status_collector,
        "read_recent_lifecycle_events",
        lambda *, limit: [],
    )

    snapshot = status_collector.collect_axe_status_snapshot(
        clock=lambda: datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    )
    from sase.core.rust import require_rust_binding

    with override_flags(axe_routine_job_contract=True):
        status_payload = require_rust_binding("project_axe_status_public")(
            snapshot.to_wire()
        )
    routines = {item["routine_name"]: item for item in status_payload["routines"]}
    assert routines["chop-watch"]["configured_jobs"] == [
        "chop-test",
        "exact.dotted[sase]",
        "legacy.entry",
    ]
    assert routines["legacy-list"]["configured_jobs"] == ["list.job"]
    assert "lumberjacks" not in status_payload
