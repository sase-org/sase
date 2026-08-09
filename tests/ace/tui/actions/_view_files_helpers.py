"""Shared harnesses for view-file hint action tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from sase.ace.tui.actions.hints._files import FileViewingMixin
from sase.ace.tui.actions.hints._processing import InputProcessingMixin
from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, *_args) -> None:
        return None


class _ViewApp(InputProcessingMixin, FileViewingMixin):
    """Minimal app combining the hint view mixins for routing tests."""

    def __init__(self, hint_mappings: dict[int, str]) -> None:
        self._hint_mappings = hint_mappings
        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        self._hint_patch_name = "cs"
        self.notify = MagicMock()
        self.app = SimpleNamespace(push_screen=MagicMock())
        self.suspend_recorder = _SuspendRecorder()

    def suspend(self):
        return self.suspend_recorder


def _make_app(*paths: str) -> _ViewApp:
    return _ViewApp({i + 1: path for i, path in enumerate(paths)})


def _commit_spec(
    *,
    sha: str = "abcdef1234567890",
    diff_path: str | None = None,
) -> CommitViewSpec:
    return CommitViewSpec(
        short_sha=sha[:12],
        sha=sha,
        repo_name="sase",
        cwd="/workspace/sase",
        subject="feat: add commit viewer",
        message="feat: add commit viewer\n\nBody line",
        diff_path=diff_path,
        is_primary=True,
    )


def _report_spec(
    report_path: str,
    *,
    status: str = "failure",
) -> SlowToolCallReportSpec:
    response_summary = (
        {"stdout_preview": "succeeded"}
        if status == "success"
        else {"stderr_preview": "failed"}
    )
    return SlowToolCallReportSpec(
        entry=ToolCallEntry(
            recorded_at="2026-07-07T14:35:02+00:00",
            runtime="codex",
            event="ToolUse",
            status=status,
            tool_name="Bash",
            tool_use_id="call_1",
            duration_ms=30_000,
            tool_input_summary={"command": "just test"},
            tool_response_summary=response_summary,
            source_path="/artifacts/tool_calls.jsonl",
            line_number=4,
        ),
        source_label=None,
        agent_name="agent--code",
        report_path=report_path,
    )
