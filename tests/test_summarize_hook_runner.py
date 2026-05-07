"""Tests for summarize-hook runner agent metadata and visibility."""

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.axe import summarize_hook_runner


def _run_summarize_hook_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    metahook: bool,
) -> tuple[int, MagicMock, MagicMock]:
    project_file = tmp_path / "projects" / "test" / "test.gp"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("NAME: my_feature\n", encoding="utf-8")
    hook_output = tmp_path / "hook.out"
    hook_output.write_text("hook failed\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts" / "summarize-hook" / "20260506120000"
    artifacts_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "sys.argv",
        [
            "summarize_hook_runner.py",
            "my_feature",
            str(project_file),
            "just test",
            str(hook_output),
            str(tmp_path / "runner.out"),
            "1",
            "260506_120000",
        ],
    )

    metadata_helper = MagicMock()
    write_done_marker = MagicMock()
    metric = MagicMock()
    metric.labels.return_value = metric

    patches = [
        patch.object(summarize_hook_runner, "init_telemetry"),
        patch.object(summarize_hook_runner, "register_push_on_exit"),
        patch.object(
            summarize_hook_runner,
            "create_artifacts_directory",
            return_value=str(artifacts_dir),
        ),
        patch.object(
            summarize_hook_runner,
            "detect_write_and_persist_review_agent_meta",
            metadata_helper,
        ),
        patch.object(summarize_hook_runner, "write_done_marker", write_done_marker),
        patch.object(summarize_hook_runner, "WORKFLOW_EXECUTIONS", metric),
        patch.object(summarize_hook_runner, "WORKFLOW_DURATION", metric),
    ]

    if metahook:
        patches.extend(
            [
                patch.object(
                    summarize_hook_runner,
                    "find_matching_metahook",
                    return_value=SimpleNamespace(name="known_failure"),
                ),
                patch.object(
                    summarize_hook_runner.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=1,
                        stdout="Known failure summary\n",
                    ),
                ),
                patch.object(
                    summarize_hook_runner, "set_hook_suffix", return_value=True
                ),
            ]
        )
    else:
        patches.extend(
            [
                patch.object(
                    summarize_hook_runner, "find_matching_metahook", return_value=None
                ),
                patch.object(
                    summarize_hook_runner,
                    "get_file_summary",
                    return_value="Generated failure summary",
                ),
                patch.object(
                    summarize_hook_runner, "set_hook_suffix", return_value=True
                ),
                patch(
                    "sase.notifications.senders.notify_workflow_complete",
                    MagicMock(),
                ),
            ]
        )

    with ExitStack() as stack:
        for context_manager in patches:
            stack.enter_context(context_manager)
        exit_code = summarize_hook_runner.main()

    return exit_code, metadata_helper, write_done_marker


def test_summarize_hook_runner_writes_review_meta_and_visible_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exit_code, metadata_helper, write_done_marker = _run_summarize_hook_runner(
        tmp_path, monkeypatch, metahook=False
    )

    assert exit_code == 0
    metadata_helper.assert_called_once()
    assert metadata_helper.call_args.args[2] == "my_feature"
    write_done_marker.assert_called_once()
    assert write_done_marker.call_args.kwargs["hidden"] is False


def test_summarize_hook_runner_metahook_return_writes_visible_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exit_code, metadata_helper, write_done_marker = _run_summarize_hook_runner(
        tmp_path, monkeypatch, metahook=True
    )

    assert exit_code == 0
    metadata_helper.assert_called_once()
    assert metadata_helper.call_args.args[2] == "my_feature"
    write_done_marker.assert_called_once()
    assert write_done_marker.call_args.kwargs["hidden"] is False
