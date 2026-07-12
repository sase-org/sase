from pathlib import Path

from sase.axe.runner_utils import write_error_report


def _write_report(tmp_path: Path, **kwargs: object) -> str:
    report_path = write_error_report(
        str(tmp_path),
        agent_model="test-model",
        agent_llm_provider="test-provider",
        workflow_name="run",
        cl_name="test-cl",
        duration="1s",
        error_summary="RuntimeError: boom",
        error_traceback=None,
        **kwargs,
    )
    assert report_path is not None
    return Path(report_path).read_text(encoding="utf-8")


def test_write_error_report_includes_submitted_xprompt(tmp_path: Path) -> None:
    prompt = '  #fix_hook(hook_command="just test")\n\nkeep trailing spaces  '

    text = _write_report(tmp_path, submitted_xprompt=prompt)

    assert "## Submitted XPrompt" in text
    assert prompt in text
    assert "```markdown" in text


def test_write_error_report_fence_survives_backticks(tmp_path: Path) -> None:
    prompt = "Please inspect:\n```python\nprint('boom')\n```"

    text = _write_report(tmp_path, submitted_xprompt=prompt)

    assert "````markdown" in text
    assert prompt in text
    assert "## Error" in text


def test_write_error_report_falls_back_to_submitted_artifact(
    tmp_path: Path,
) -> None:
    (tmp_path / "submitted_xprompt.md").write_text("#submitted\n", encoding="utf-8")
    (tmp_path / "raw_xprompt.md").write_text("#raw\n", encoding="utf-8")

    text = _write_report(tmp_path)

    assert "#submitted\n" in text
    assert "#raw\n" not in text


def test_write_error_report_falls_back_to_raw_xprompt(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text("#raw\n", encoding="utf-8")

    text = _write_report(tmp_path)

    assert "## Submitted XPrompt" in text
    assert "#raw\n" in text


def test_write_error_report_adds_adjacent_context(tmp_path: Path) -> None:
    text = _write_report(
        tmp_path,
        workspace_dir="/tmp/ws",
        output_path="/tmp/output.log",
        agent_name="sase-x.1",
    )

    assert "| Agent name | sase-x.1 |" in text
    assert "| Artifact directory |" in text
    assert "| Workspace directory | /tmp/ws |" in text
    assert "| Output log path | /tmp/output.log |" in text


def test_write_error_report_includes_held_workspace_recovery(tmp_path: Path) -> None:
    text = _write_report(
        tmp_path,
        workspace_dir="/tmp/ws",
        held_workspace_num=17,
    )

    assert "| Held workspace | #17 |" in text
    assert "## Workspace recovery" in text
    assert "dismiss the failed agent" in text
