import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec import _write_done_marker_and_update_index
from sase.axe.run_agent_exec_markers import (
    clear_workflow_pdf_activity,
    update_workflow_pdf_status,
)
from sase.axe.run_agent_exec_plan_artifacts import write_plan_path_artifact
from sase.axe.run_agent_runner_setup import (
    preprocess_prompt_xprompts,
    refresh_sibling_repos_for_workspace,
    setup_artifacts_directory,
    write_submitted_xprompt_artifact,
)
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV, resolve_sibling_repos_for_project


def test_write_submitted_xprompt_artifact_preserves_exact_prompt(
    tmp_path: Path,
) -> None:
    prompt = "  #alias\n\nbody\n  "

    path = write_submitted_xprompt_artifact(str(tmp_path), prompt)

    assert Path(path).name == "submitted_xprompt.md"
    assert Path(path).read_text(encoding="utf-8") == prompt


def test_submitted_xprompt_artifact_does_not_change_raw_xprompt_behavior(
    tmp_path: Path,
) -> None:
    submitted = "#alias original"
    resolved = "#real original"

    write_submitted_xprompt_artifact(str(tmp_path), submitted)
    with (
        patch("sase.xprompt.resolve_xprompt_aliases", return_value=resolved),
        patch("sase.xprompt._parsing.extract_vcs_workflow_tag", return_value=None),
        patch(
            "sase.xprompt.processor.process_xprompt_references", return_value="expanded"
        ),
    ):
        preprocess_prompt_xprompts(submitted, str(tmp_path))

    assert (tmp_path / "submitted_xprompt.md").read_text(encoding="utf-8") == submitted
    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == resolved


def test_setup_artifacts_directory_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with (
        patch(
            "sase.axe.run_agent_runner_setup.create_artifacts_directory",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.axe.run_agent_runner_setup.convert_timestamp_to_artifacts_format",
            return_value="20260520220000",
        ),
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: calls.append(path),
        ),
    ):
        setup_artifacts_directory(
            timestamp="260520_220000",
            project_file="/tmp/project/project.gp",
            cl_name="feature",
            is_home_mode=False,
        )

    assert calls == [str(tmp_path)]
    assert (tmp_path / "workflow_state.json").is_file()


def test_refresh_sibling_repos_for_workspace_updates_env_meta_without_prompt_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "sase"
    sibling = tmp_path / "sase-core"
    workspace = tmp_path / "sase_7"
    primary.mkdir()
    sibling.mkdir()
    workspace.mkdir()
    project_file = tmp_path / "project.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\nNAME: main\n")
    resolution = resolve_sibling_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(workspace),
        workspace_num=7,
        config={"sibling_repos": [{"name": "core", "path": "../sase-core"}]},
        materialize=False,
    )
    monkeypatch.setenv(SIBLING_REPOS_JSON_ENV, "stale")
    meta = {"pid": 123, "workspace_dir": "/placeholder"}

    with (
        patch(
            "sase.sibling_repos.resolve_sibling_repos_for_project",
            return_value=resolution,
        ),
        patch(
            "sase.axe.run_agent_runner_setup."
            "update_agent_artifact_index_for_marker_mutation",
        ),
    ):
        prompt = refresh_sibling_repos_for_workspace(
            project_file=str(project_file),
            workspace_dir=str(workspace),
            workspace_num=7,
            artifacts_dir=str(tmp_path),
            agent_meta=meta,
            prompt="Do work",
        )

    assert prompt == "Do work"
    assert meta["workspace_dir"] == str(workspace)
    assert meta["sibling_repos"] == resolution.to_jsonable()
    written = json.loads((tmp_path / "agent_meta.json").read_text(encoding="utf-8"))
    assert written["sibling_repos"][0]["workspace_dir"] == str(tmp_path / "sase-core_7")
    assert json.loads(os.environ[SIBLING_REPOS_JSON_ENV])[0]["name"] == "core"


def test_done_marker_write_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_markers."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        done_path = _write_done_marker_and_update_index(
            str(tmp_path),
            {"outcome": "completed"},
        )

    assert Path(done_path) == tmp_path / "done.json"
    assert calls == [str(tmp_path)]
    assert '"outcome": "completed"' in Path(done_path).read_text(encoding="utf-8")


def test_plan_path_artifact_write_updates_artifact_index(tmp_path: Path) -> None:
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_plan_artifacts."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        write_plan_path_artifact(str(tmp_path), "/tmp/plan.md")

    assert calls == [str(tmp_path)]
    assert (tmp_path / "plan_path.json").read_text(encoding="utf-8") == (
        '{"plan_path": "/tmp/plan.md"}'
    )


def test_workflow_pdf_status_updates_artifact_index(tmp_path: Path) -> None:
    state_path = tmp_path / "workflow_state.json"
    state_path.write_text('{"status": "running"}', encoding="utf-8")
    calls: list[str] = []

    with patch(
        "sase.axe.run_agent_exec_markers."
        "update_agent_artifact_index_for_marker_mutation",
        side_effect=lambda path: calls.append(path),
    ):
        update_workflow_pdf_status(
            str(tmp_path),
            {"stage": "source_started", "index": 1, "total": 2, "source_path": "a.md"},
        )
        clear_workflow_pdf_activity(str(tmp_path))

    assert calls == [str(tmp_path), str(tmp_path)]
    data = state_path.read_text(encoding="utf-8")
    assert '"pdf_status"' in data
    assert '"activity"' not in data
