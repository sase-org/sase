"""Launch-specific bookkeeping at the placeholder-to-durable handle seam."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
    KillAndEditLastLaunchMixin,
)
from sase.ace.tui.actions.agent_workflow._launch_procs import LaunchProcMixin
from sase.ace.tui.actions.agent_workflow._launch_records import (
    LaunchRecordContext,
    push_launch_record,
)
from sase.ace.tui.actions.agent_workflow._types import RelaunchOperation
from sase.ace.tui.proc_observer import ObservedProc


class _LaunchHandleApp(KillAndEditLastLaunchMixin, LaunchProcMixin):
    def __init__(self) -> None:
        self.submissions: list[dict[str, Any]] = []
        self.bulk_prompts: list[list[str]] = []

    def _submit_durable_proc(self, argv: list[str], **kwargs: Any) -> ObservedProc:
        del argv
        self.submissions.append(kwargs)
        proc_id = f"pending-{len(self.submissions)}"
        return ObservedProc(
            proc_id=proc_id,
            proc_type="launch",
            cl_name=kwargs["cl_name"],
            project_file=kwargs["project_file"],
            status="pending",
            message="pending",
            started_at=datetime.now(),
            display_name=kwargs["display_name"],
        )

    def _edit_and_relaunch_agents_bulk(
        self,
        raw_prompts: list[str],
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
        **kwargs: object,
    ) -> None:
        del project_file, cl_name, is_project_agent, kwargs
        self.bulk_prompts.append(list(raw_prompts))


def _context() -> LaunchRecordContext:
    return LaunchRecordContext(
        display_name="bulk",
        project_file="/tmp/demo.sase",
        cl_name="demo",
        is_project_agent=True,
    )


def _submit(app: _LaunchHandleApp, prompt: str) -> ObservedProc:
    proc = app._submit_launch_proc(
        display_name="launch demo",
        cl_name="demo",
        project_file="/tmp/demo.sase",
        prompt=prompt,
        submitted_prompt=prompt,
    )
    assert proc is not None
    return proc


def test_launch_handle_rekeys_recovery_prompt_and_record() -> None:
    app = _LaunchHandleApp()
    proc = _submit(app, "do work")
    record = push_launch_record(
        app,
        proc_ids=(proc.proc_id,),
        prompt="do work",
        context=_context(),
        submitted_prompts={proc.proc_id: "do work"},
    )
    assert record is not None

    on_handle = app.submissions[0]["on_handle"]
    on_handle(proc.proc_id, "durable-1")

    assert app._launch_submitted_prompts == {"durable-1": "do work"}
    assert record.proc_ids == ("durable-1",)
    assert record.submitted_prompts == {"durable-1": "do work"}


def test_bulk_launch_handles_rekey_independently_and_keep_prompt_order() -> None:
    app = _LaunchHandleApp()
    first = _submit(app, "first prompt")
    second = _submit(app, "second prompt")
    record = push_launch_record(
        app,
        proc_ids=(first.proc_id, second.proc_id),
        prompt="shared",
        context=_context(),
        submitted_prompts={
            first.proc_id: "first prompt",
            second.proc_id: "second prompt",
        },
    )
    assert record is not None

    app.submissions[1]["on_handle"](second.proc_id, "durable-2")
    app.submissions[0]["on_handle"](first.proc_id, "durable-1")
    app._mount_inflight_launch_prompt(
        record,
        relaunch_operation=RelaunchOperation("test"),
    )

    assert record.proc_ids == ("durable-1", "durable-2")
    assert app._launch_submitted_prompts == {
        "durable-2": "second prompt",
        "durable-1": "first prompt",
    }
    assert app.bulk_prompts == [["first prompt", "second prompt"]]
