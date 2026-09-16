"""Tests for the axe CLI command handlers."""

import argparse
from collections.abc import Iterator
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from sase.axe.cli import (
    handle_axe_chop_doctor,
    handle_axe_chop_list,
    handle_axe_chop_run,
    handle_axe_lumberjack_list,
    handle_axe_lumberjack_status,
)
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.axe.chop_runner import ChopRunOutcome
from sase.config.core import ConfigLayer
from sase.feature_flags import FeatureFlag, override_flags

ALL_12_CHOP_NAMES = sorted(
    [
        "hook_checks",
        "mentor_checks",
        "workflow_checks",
        "pending_checks_poll",
        "comment_zombie_checks",
        "suffix_transforms",
        "orphan_cleanup",
        "stale_running_cleanup",
        "pr_submitted_checks",
        "comment_checks",
        "error_digest",
        "wait_checks",
    ]
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch state directories for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
        patch("sase.axe.state.shared_state_dir", return_value=shared_dir),
    ):
        yield state_dir


@pytest.fixture
def default_axe_config() -> AxeConfig:
    """Return a default AxeConfig with 4 lumberjacks."""
    from sase.axe.config import _parse_lumberjacks

    return AxeConfig(
        lumberjacks=_parse_lumberjacks(
            {
                "hooks": {
                    "interval": 1,
                    "description": "Fast lane that advances hook lifecycle state",
                    "chops": [
                        {"name": "hook_checks", "description": "Check hooks"},
                    ],
                },
                "checks": {
                    "interval": 300,
                    "description": "Poll slower PR-submission checks",
                    "chops": [
                        {
                            "name": "pr_submitted_checks",
                            "description": "Check Patches",
                        },
                    ],
                },
                "comments": {
                    "interval": 60,
                    "description": "Start critique-comment checks for mailed PRs",
                    "chops": [
                        {"name": "comment_checks", "description": "Check comments"},
                    ],
                },
                "housekeeping": {
                    "description": "Run hourly housekeeping checks",
                    "interval": 3600,
                    "chops": [
                        {"name": "error_digest", "description": "Digest errors"},
                    ],
                },
            }
        )
    )


# --- handle_axe_chop_list Tests ---


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_chop_list_renders_configured_chops(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The list view renders one configured-chop row per lumberjack."""
    from sase.axe.config import _parse_lumberjacks

    config = AxeConfig(
        lumberjacks=_parse_lumberjacks(
            {
                "lumberjack1": {
                    "description": "Run first shared-chop checks",
                    "interval": 1,
                    "chops": [
                        {"name": "shared_chop", "description": "From lumberjack1"},
                    ],
                },
                "lumberjack2": {
                    "description": "Run second shared-chop checks",
                    "interval": 60,
                    "chops": [
                        {"name": "shared_chop", "description": "From lumberjack2"},
                    ],
                },
            }
        )
    )
    mock_load.return_value = config
    args = argparse.Namespace(json=False, available=False, verbose=False)
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_chop_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "shared_chop" in output
    assert "Configured Jobs" in output


# --- handle_axe_chop_run --lumberjack Tests ---


def _config_with(**chops_per_jack: list[ChopConfig]) -> AxeConfig:
    return AxeConfig(
        lumberjacks={
            name: LumberjackConfig(
                name=name,
                description=f"Run {name} CLI test chops",
                interval=10,
                chops=chops,
            )
            for name, chops in chops_per_jack.items()
        }
    )


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
    from io import StringIO

    import sase.axe.status_collector as status_collector
    import sase.axe.status_render as status_render
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
    monkeypatch.setattr(status_collector, "read_desired_state", lambda: None)
    monkeypatch.setattr(status_collector, "read_maintenance", lambda: None)
    monkeypatch.setattr(
        status_collector,
        "read_recent_lifecycle_events",
        lambda *, limit: [],
    )
    monkeypatch.setattr(status_collector, "unsafe_axe_systemd_scope", lambda _pid: None)

    snapshot = status_collector.collect_axe_status_snapshot(
        clock=lambda: datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    )
    status_output = StringIO()
    with override_flags(axe_routine_job_contract=True):
        status_render.render_axe_status_json(snapshot, stream=status_output)
    status_payload = json.loads(status_output.getvalue())
    routines = {item["routine_name"]: item for item in status_payload["routines"]}
    assert routines["chop-watch"]["configured_jobs"] == [
        "chop-test",
        "exact.dotted[sase]",
        "legacy.entry",
    ]
    assert routines["legacy-list"]["configured_jobs"] == ["list.job"]
    assert "lumberjacks" not in status_payload


def test_handle_axe_chop_run_ambiguous_requires_lumberjack(
    temp_state_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A duplicate chop name without --lumberjack exits with a clear error."""
    config = AxeConfig(
        lumberjacks={
            "lumberjack_hooks": LumberjackConfig(
                name="lumberjack_hooks",
                description="Run hook CLI test chops",
                interval=10,
                chops=[ChopConfig(name="chop-test", description="")],
            ),
            "comments": LumberjackConfig(
                name="comments",
                description="Run comment CLI test chops",
                interval=10,
                chops=[ChopConfig(name="chop-test", description="")],
            ),
        }
    )
    args = argparse.Namespace(chop_name="chop-test", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "multiple routines" in err
    assert "--routine" in err
    assert "job 'chop-test'" in err
    assert "lumberjack_hooks" in err
    assert "job-test" not in err
    assert "routine_hooks" not in err


def test_handle_axe_chop_run_with_lumberjack_disambiguates(
    temp_state_dir: Path,
) -> None:
    """Passing --lumberjack selects the configured chop under that lumberjack."""
    chop = ChopConfig(
        name="dup",
        description="script under comments",
        script="comments_dup",
    )
    config = _config_with(
        hooks=[ChopConfig(name="dup", description="")],
        comments=[chop],
    )
    args = argparse.Namespace(chop_name="dup", lumberjack="comments")

    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch(
            "sase.axe.cli.run_configured_chop_once",
            return_value=ChopRunOutcome(
                lumberjack_name="comments",
                chop_name="dup",
                status="success",
            ),
        ) as mock_run,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 0
    assert mock_run.call_args.kwargs["lumberjack_name"] == "comments"
    assert mock_run.call_args.kwargs["chop"] is chop


def test_handle_axe_chop_run_passes_debug_flags(
    temp_state_dir: Path,
) -> None:
    chop = ChopConfig(name="probe", description="")
    config = _config_with(checks=[chop])
    args = argparse.Namespace(
        chop_name="probe",
        lumberjack="checks",
        dry_run=True,
        chop_verbose=True,
        force=True,
    )

    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch(
            "sase.axe.cli.run_configured_chop_once",
            return_value=ChopRunOutcome(
                lumberjack_name="checks",
                chop_name="probe",
                status="success",
                dry_run=True,
            ),
        ) as mock_run,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 0
    assert mock_run.call_args.kwargs["dry_run"] is True
    assert mock_run.call_args.kwargs["chop_verbose"] is True
    assert mock_run.call_args.kwargs["force"] is True


def test_handle_axe_chop_run_with_lumberjack_not_configured(
    temp_state_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--lumberjack pointing at a chop that doesn't exist there errors out."""
    config = _config_with(
        hooks=[ChopConfig(name="hook_checks", description="")],
    )
    args = argparse.Namespace(chop_name="hook_checks", lumberjack="comments")
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 1
    assert "not configured under routine" in capsys.readouterr().err


def test_handle_axe_chop_run_unknown_chop(
    temp_state_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config_with(hooks=[])
    args = argparse.Namespace(chop_name="absent", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.cli.discover_chop_script", return_value=None),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 1
    assert "unknown job" in capsys.readouterr().err


def test_handle_axe_chop_run_records_run_history_under_lumberjack(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    """A successful CLI run writes the run-history entry under the configured lumberjack."""
    from sase.axe.state import read_chop_run_index

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "hook_checks"
    script.write_text("#!/bin/sh\necho hello\n")
    import stat as _stat

    script.chmod(script.stat().st_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)

    chop = ChopConfig(name="hook_checks", description="")
    config = AxeConfig(
        chop_script_dirs=[str(scripts_dir)],
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hook CLI test chops",
                interval=10,
                chops=[chop],
            ),
        },
    )
    args = argparse.Namespace(chop_name="hook_checks", lumberjack="hooks")
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 0
    index = read_chop_run_index("hooks", "hook_checks")
    assert len(index) == 1


def test_handle_axe_chop_run_unconfigured_script_uses_oneshot(
    temp_state_dir: Path,
    tmp_path: Path,
) -> None:
    """A discoverable but unconfigured script still runs under ``_oneshot``."""
    from sase.axe.state import read_chop_run_index

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "freestanding"
    script.write_text("#!/bin/sh\ntrue\n")
    import stat as _stat

    script.chmod(script.stat().st_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)

    config = AxeConfig(chop_script_dirs=[str(scripts_dir)])
    args = argparse.Namespace(chop_name="freestanding", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.chop_runner.find_all_patches", return_value=[]),
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 0
    assert read_chop_run_index("_oneshot", "freestanding")


def test_handle_axe_chop_run_already_running_skips(
    temp_state_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When a chop is already running, the CLI notifies and exits nonzero."""
    from datetime import datetime

    from sase.axe.state import ChopRunEntry, start_chop_run

    chop = ChopConfig(name="hook_checks", description="")
    config = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hook CLI test chops",
                interval=10,
                chops=[chop],
            ),
        }
    )

    live_entry = ChopRunEntry(
        run_id="20260101T120000_000000",
        lumberjack_name="hooks",
        chop_name="hook_checks",
        started_at=datetime.now().isoformat(),
        finished_at=None,
        duration_ms=0,
        status="running",
    )
    start_chop_run(live_entry)

    args = argparse.Namespace(chop_name="hook_checks", lumberjack=None)
    with (
        patch("sase.axe.cli.load_axe_config", return_value=config),
        patch("sase.axe.chop_runner.stream_chop_script") as mock_stream,
        pytest.raises(SystemExit) as exc_info,
    ):
        handle_axe_chop_run(args)

    assert exc_info.value.code == 1
    assert "already running" in capsys.readouterr().err
    mock_stream.assert_not_called()


# --- handle_axe_lumberjack_list Tests ---


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_lumberjack_list_prints_lumberjacks(
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that lumberjack list prints 4 default lumberjacks."""
    mock_load.return_value = default_axe_config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_list(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    # 4 routines × (name + description + interval + "jobs:" + 1 job).
    assert len(lines) == 20
    assert "hooks" in output
    assert "checks" in output
    assert "comments" in output
    assert "housekeeping" in output
    assert "interval:" in output
    assert "jobs:" in output


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_lumberjack_list_prints_descriptions(
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Each described lumberjack prints its description before its interval."""
    mock_load.return_value = default_axe_config
    with pytest.raises(SystemExit):
        handle_axe_lumberjack_list(argparse.Namespace())

    lines = [
        line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()
    ]
    hooks_index = lines.index("hooks")
    assert lines[hooks_index + 1] == (
        "description: Fast lane that advances hook lifecycle state"
    )
    assert lines[hooks_index + 2].startswith("interval:")
    housekeeping_index = lines.index("housekeeping")
    assert lines[housekeeping_index + 1] == (
        "description: Run hourly housekeeping checks"
    )
    assert lines[housekeeping_index + 2].startswith("interval:")


@patch("sase.axe.cli.load_axe_config")
def test_handle_axe_lumberjack_list_prints_only_configured_wait_runners(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_load.return_value = AxeConfig(
        lumberjacks={
            "audits": LumberjackConfig(
                name="audits",
                description="Run audits",
                interval=60,
                wait_runners=0,
            ),
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hooks",
                interval=1,
            ),
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_list(argparse.Namespace())

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert output.count("wait_runners:") == 1
    assert "wait_runners: 0" in output


@patch("sase.axe.cli.load_axe_config")
@pytest.mark.parametrize("verbose", [False, True])
def test_handle_axe_lumberjack_list_verbose_controls_description_body(
    mock_load: MagicMock,
    capsys: pytest.CaptureFixture[str],
    verbose: bool,
) -> None:
    body = "Explains the hook lifecycle and stale-work startup path."
    mock_load.return_value = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Advance hook lifecycle state\n\n" + body,
                description_summary="Advance hook lifecycle state",
                description_body=body,
                interval=1,
                chops=[
                    ChopConfig(
                        name="hook_checks",
                        description="Complete hook checks",
                    )
                ],
            )
        }
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_list(argparse.Namespace(verbose=verbose))

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "description: Advance hook lifecycle state" in output
    assert ("details:" in output) is verbose
    assert (body in output) is verbose


# --- handle_axe_lumberjack_status Tests ---


@patch("sase.axe.cli.load_axe_config")
@patch("sase.axe.cli.read_lumberjack_status", return_value=None)
def test_handle_axe_lumberjack_status_none_running(
    mock_status: MagicMock,
    mock_load: MagicMock,
    default_axe_config: AxeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status display when no lumberjacks are running."""
    mock_load.return_value = default_axe_config
    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_status(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "not running" in output


@patch("sase.axe.cli.is_process_running", return_value=True)
@patch("sase.axe.cli.load_axe_config")
@patch("sase.axe.cli.read_lumberjack_status")
def test_handle_axe_lumberjack_status_with_running(
    mock_status: MagicMock,
    mock_load: MagicMock,
    mock_running: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test status display when a lumberjack is running."""
    from sase.axe.state import LumberjackStatus

    mock_load.return_value = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                description="Run hook status checks",
                interval=1,
                chops=[ChopConfig(name="hook_checks", description="Check hooks")],
            )
        }
    )
    mock_status.return_value = LumberjackStatus(
        name="hooks",
        pid=12345,
        started_at="2026-01-01T00:00:00",
        status="running",
        interval=1,
        chops=["hook_checks"],
        cycles_run=42,
        errors_encountered=0,
        uptime_seconds=100,
    )

    args = argparse.Namespace()
    with pytest.raises(SystemExit) as exc_info:
        handle_axe_lumberjack_status(args)
    assert exc_info.value.code == 0

    output = capsys.readouterr().out
    assert "hooks" in output
    assert "running" in output
    assert "12345" in output
    assert "42" in output
