"""Durable-path MRU and unresolved-reference feedback for ``sase run``.

ACE's in-process launch body used to record ``<ctrl+p>`` VCS-xprompt MRU
entries and surface unknown ``#refs`` as a warning toast. Production now
runs ``launch_query()`` in the child ``sase run`` process, so both pieces
of feedback have to travel that path: record after a successful spawn, and
put the toast text on the ``RUN_LAUNCH`` result payload.
"""

from __future__ import annotations

import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.xprompt.unresolved import format_unresolved_references_toast


def _launch_result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=1234,
        workspace_num=7,
        workspace_dir="/workspace/7",
        output_path="/tmp/out.txt",
        project_file="/tmp/projects/proj/proj.sase",
        project_name="proj",
        workflow_name="ace(run)-260101_120000",
        cl_name="proj",
        timestamp="260101_120000",
    )


def _git_and_gh_patterns() -> dict[str, re.Pattern[str]]:
    return {
        "git": re.compile(r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))"),
        "gh": re.compile(r"(?:^|(?<=\s))#gh(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))"),
    }


def _run_successful_launch_query(
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    *,
    scan_unresolved: tuple[str, ...] = (),
    record_mru: MagicMock | None = None,
) -> dict[str, Any]:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    captured: dict[str, Any] = {}

    def _capture_emit(**kwargs: Any) -> None:
        captured.update(kwargs)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.agent.prompt_inputs.missing_required_input_names",
                return_value=[],
            )
        )
        stack.enter_context(
            patch(
                "sase.xprompt.unresolved.scan_query_for_unresolved_references",
                return_value=scan_unresolved,
            )
        )
        stack.enter_context(
            patch(
                "sase.workspace_provider.get_ref_patterns",
                return_value=_git_and_gh_patterns(),
            )
        )
        stack.enter_context(
            patch(
                "sase.main.query_handler._launch.launch_agents_from_cwd",
                return_value=[_launch_result()],
            )
        )
        stack.enter_context(
            patch(
                "sase.ops.commands.run.emit_run_launch_result",
                side_effect=_capture_emit,
            )
        )
        if record_mru is not None:
            stack.enter_context(
                patch(
                    "sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage",
                    record_mru,
                )
            )
        with pytest.raises(SystemExit) as exc_info:
            launch_query(query)

    assert exc_info.value.code == 0
    return captured


def test_launch_query_plain_prompt_records_no_vcs_mru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = MagicMock()

    _run_successful_launch_query(monkeypatch, "do work", record_mru=record)

    record.assert_not_called()


def test_launch_query_does_not_record_default_git_home_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.history.vcs_xprompt_mru import _load_vcs_xprompt_mru

    fake_mru = tmp_path / "vcs_xprompt_mru.json"
    monkeypatch.setattr("sase.history.vcs_xprompt_mru._MRU_FILE", fake_mru)

    _run_successful_launch_query(monkeypatch, "#git:home do work")

    assert _load_vcs_xprompt_mru() == []
    assert not fake_mru.exists()


def test_launch_query_records_explicit_vcs_ref_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = MagicMock()

    _run_successful_launch_query(monkeypatch, "#gh:sase do the work", record_mru=record)

    record.assert_called_once_with("#gh:sase")


def test_launch_query_does_not_record_mru_when_launch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main.query_handler._launch import launch_query

    monkeypatch.delenv("SASE_AGENT", raising=False)
    record = MagicMock()

    with (
        patch("sase.agent.prompt_inputs.missing_required_input_names", return_value=[]),
        patch(
            "sase.xprompt.unresolved.scan_query_for_unresolved_references",
            return_value=(),
        ),
        patch(
            "sase.workspace_provider.get_ref_patterns",
            return_value=_git_and_gh_patterns(),
        ),
        patch(
            "sase.main.query_handler._launch.launch_agents_from_cwd",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage",
            record,
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        launch_query("#gh:sase do work")

    assert exc_info.value.code == 1
    record.assert_not_called()


def test_launch_query_puts_unresolved_toast_on_result_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _run_successful_launch_query(
        monkeypatch,
        "do work #reviewww",
        scan_unresolved=("reviewww",),
    )

    assert captured["success"] is True
    assert captured["payload"]["warning_messages"] == [
        format_unresolved_references_toast(("reviewww",))
    ]


def test_launch_query_omits_warning_messages_when_all_refs_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _run_successful_launch_query(monkeypatch, "do work")

    assert captured["success"] is True
    assert "warning_messages" not in captured["payload"]


def test_leading_vcs_xprompt_prefix_matches_orphaned_multi_prompt_search() -> None:
    from sase.main.query_handler._launch import _leading_vcs_xprompt_prefix

    with patch(
        "sase.workspace_provider.get_ref_patterns",
        return_value=_git_and_gh_patterns(),
    ):
        assert _leading_vcs_xprompt_prefix("do work") is None
        assert _leading_vcs_xprompt_prefix("#git:home do work") == "#git:home"
        assert _leading_vcs_xprompt_prefix("#gh:sase do work") == "#gh:sase"
        assert _leading_vcs_xprompt_prefix("#git(sase) do work") == "#git:sase"
