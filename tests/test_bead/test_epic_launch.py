"""Shared approved-epic launch helper tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.epic_launch import (
    _run_detached_worker,
    build_epic_launch_argv,
    parse_epic_launch_output,
    resolve_epic_launch_cwd,
    spawn_detached_epic_launch,
    update_epic_launch_metadata,
)


def test_build_and_parse_epic_launch_contract() -> None:
    assert build_epic_launch_argv("/tmp/epic plan.md") == [
        "sase",
        "bead",
        "work",
        "/tmp/epic plan.md",
        "--yes-to-all",
    ]
    parsed = parse_epic_launch_output(
        "✓ Archived        /plans/202607/epic plan.md (committed)\n"
        "✓ Plan linked     bead_id: sase-64 · /plans/202607/epic plan.md\n"
        "Epic: sase-64\n"
    )
    assert parsed.epic_id == "sase-64"
    assert parsed.archived_plan_path == "/plans/202607/epic plan.md"


def test_resolve_epic_launch_cwd_prefers_canonical_project_file(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sase_10"
    project_dir.mkdir()
    project_file = (
        tmp_path / "projects" / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    )
    primary = tmp_path / "primary"
    primary.mkdir()

    with (
        patch("sase.workspace_provider.get_workspace_name") as get_workspace_name,
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(primary),
        ) as get_workspace_directory,
    ):
        resolved = resolve_epic_launch_cwd(
            project_dir,
            agent_project_file=project_file,
        )

    assert resolved == primary
    get_workspace_name.assert_not_called()
    get_workspace_directory.assert_called_once_with("gh_sase-org__sase", 1)


@pytest.mark.parametrize("provider_name", ["sase", None])
def test_resolve_epic_launch_cwd_canonicalizes_compatibility_fallback(
    tmp_path: Path,
    provider_name: str | None,
) -> None:
    project_dir = tmp_path / "sase_10"
    primary = tmp_path / "primary"
    primary.mkdir()

    with (
        patch(
            "sase.workspace_provider.get_workspace_name",
            return_value=provider_name,
        ),
        patch(
            "sase.project_aliases.resolve_project_alias_ref",
            return_value="gh_sase-org__sase",
        ) as resolve_alias,
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(primary),
        ) as get_workspace_directory,
    ):
        resolved = resolve_epic_launch_cwd(project_dir)

    assert resolved == primary
    resolve_alias.assert_called_once_with("sase")
    get_workspace_directory.assert_called_once_with("gh_sase-org__sase", 1)


def test_resolve_epic_launch_cwd_rejects_invalid_project_file_identity(
    tmp_path: Path,
) -> None:
    with (
        patch("sase.workspace_provider.get_workspace_name") as get_workspace_name,
        patch("sase.running_field.get_workspace_directory") as get_workspace_directory,
        pytest.raises(ValueError, match="does not identify a valid SASE project"),
    ):
        resolve_epic_launch_cwd(
            tmp_path / "sase_10",
            agent_project_file="project.sase",
        )

    get_workspace_name.assert_not_called()
    get_workspace_directory.assert_not_called()


def test_spawn_detached_epic_launch_uses_worker_and_log(tmp_path: Path) -> None:
    process = type("Process", (), {"pid": 1234})()
    log_path = tmp_path / "logs" / "epic.log"
    with patch("sase.bead.epic_launch.subprocess.Popen", return_value=process) as popen:
        launched = spawn_detached_epic_launch(
            tmp_path / "plan.md",
            cwd=tmp_path,
            log_path=log_path,
            artifacts_dir=tmp_path / "artifacts",
            cl_name="demo",
        )

    assert launched.pid == 1234
    assert launched.log_path == log_path
    argv = popen.call_args.args[0]
    assert argv[1:4] == ["-m", "sase.bead.epic_launch", "--worker"]
    assert argv[-2:] == ["--cl-name", "demo"]
    assert popen.call_args.kwargs["start_new_session"] is True


def test_update_epic_launch_metadata_backfills_all_host_fields(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    meta_path = artifacts / "agent_meta.json"
    meta_path.write_text('{"name": "planner"}\n', encoding="utf-8")

    with patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        update_epic_launch_metadata(
            artifacts,
            epic_id="sase-64",
            sdd_plan_path="/plans/epic.md",
            started_at="2026-07-15T12:00:00+00:00",
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta == {
        "name": "planner",
        "epic_bead_id": "sase-64",
        "epic_started_at": "2026-07-15T12:00:00+00:00",
        "plan_committed": True,
        "sdd_plan_path": "/plans/epic.md",
    }
    update_index.assert_called_once_with(artifacts)


def test_detached_worker_reports_command_start_failure(tmp_path: Path) -> None:
    log_path = tmp_path / "epic.log"
    args = SimpleNamespace(
        plan_file=str(tmp_path / "plan.md"),
        cwd=str(tmp_path),
        log_path=str(log_path),
        artifacts_dir=None,
        cl_name="demo",
    )
    with (
        patch(
            "sase.bead.epic_launch.subprocess.run",
            side_effect=OSError("missing sase"),
        ),
        patch("sase.bead.epic_launch._notify_detached_completion") as notify,
    ):
        returncode = _run_detached_worker(args)

    assert returncode == 1
    assert "missing sase" in log_path.read_text(encoding="utf-8")
    assert notify.call_args.kwargs["returncode"] == -1
