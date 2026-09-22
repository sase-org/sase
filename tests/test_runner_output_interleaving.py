"""Runner shared-output ordering: line-buffered stdio plus marker-last shutdown."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_CHILD_SCRIPT = textwrap.dedent("""\
    import sys
    from unittest.mock import MagicMock

    import sase.axe.run_agent_runner as runner
    from sase.axe.run_agent_runner_lifecycle import (
        RunnerShutdownContext,
        RunnerShutdownDeps,
        RunnerShutdownState,
        finalize_runner_shutdown,
    )

    output_path = sys.argv[1]
    artifacts_dir = sys.argv[2]
    # Enter through the real runner entry point with an unparseable argv.
    # Argument parsing exits(1) after the line-buffering setup, so this
    # proves main() enables line buffering without running an agent.
    sys.argv = ["run_agent_runner"]
    try:
        runner.main()
    except SystemExit as exc:
        assert exc.code == 1, exc.code
    else:
        raise AssertionError("main() should exit on unparseable argv")
    assert sys.stdout.line_buffering is True
    for i in range(30):
        print(f"stdout-{i:02d}")
        print(f"stderr-{i:02d}", file=sys.stderr)
    context = RunnerShutdownContext(
        project_file="/tmp/project.sase",
        workflow_name="run",
        cl_name="feature",
        artifacts_timestamp="20260712120000",
        artifacts_dir=artifacts_dir,
        output_path=output_path,
        submitted_xprompt="do work",
        prompt="do work",
        is_home_mode=True,
    )
    state = RunnerShutdownState(
        success=True,
        duration="1s",
        workspace_num=0,
        workspace_dir="/tmp/workspace-0",
        current_artifacts_dir=artifacts_dir,
        running_marker_path=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_hidden=False,
        saved_path=None,
        diff_path=None,
        markdown_pdf_paths=[],
        markdown_source_count=0,
        image_paths=[],
        video_paths=[],
        step_output=None,
        exec_outcome="completed",
        error_summary=None,
        error_traceback_str=None,
        suppress_completion_notification=True,
        runtime="1s",
    )
    deps = RunnerShutdownDeps(
        update_artifact_index=MagicMock(),
        was_killed=MagicMock(return_value=False),
        all_steps_hidden=MagicMock(return_value=True),
        write_error_report=MagicMock(),
        write_error_done_marker=MagicMock(),
        send_completion_notification=MagicMock(),
        auto_dismiss_completed_agent=MagicMock(),
    )
    finalize_runner_shutdown(context=context, state=state, deps=deps)
    """)


def test_runner_stdout_stderr_interleave_with_marker_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interleaved stdio keeps order in the shared file; the marker is last.

    The child mirrors the runner: both streams share one output file (as
    with ``spawn_prepared_detached_process``), stdout is line-buffered at
    entry, and shutdown flushes stdio before appending the completion
    marker. Without either change the block-buffered stdout flush would land
    after the stderr lines and after the marker.
    """
    monkeypatch.delenv("SASE_AGENT_AUTO_DISMISS", raising=False)
    output_path = tmp_path / "runner.log"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    with open(output_path, "w", encoding="utf-8") as log_file:
        subprocess.run(
            [
                sys.executable,
                "-c",
                _CHILD_SCRIPT,
                str(output_path),
                str(artifacts_dir),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=120,
        )
    lines = output_path.read_text(encoding="utf-8").splitlines()
    stream_lines = [line for line in lines if line.startswith(("stdout-", "stderr-"))]
    assert stream_lines == [
        f"{stream}-{i:02d}" for i in range(30) for stream in ("stdout", "stderr")
    ]
    assert lines[-3:] == [
        "=== AGENT_RUN_COMPLETE ===",
        "Status: SUCCESS",
        "Duration: 1s",
    ]
