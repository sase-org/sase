from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_exec import _write_done_marker_and_update_index
from sase.axe.run_agent_runner_setup import (
    preprocess_prompt_xprompts,
    setup_artifacts_directory,
    write_submitted_xprompt_artifact,
)


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
