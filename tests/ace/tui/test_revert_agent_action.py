"""Tests for the Agents-tab revert action gate and task submission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.revert_agent import (
    BulkRevertPreview,
    BulkRevertResult,
    RevertCommit,
    RevertPreview,
    RevertResult,
    RevertTarget,
)
from sase.ace.tui.actions.agents._revert import AgentRevertMixin
from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata


class _FakeApp(AgentRevertMixin):
    def __init__(self, agent: Agent | None, current_tab: str = "agents") -> None:
        self.current_tab = current_tab
        self._selected = agent
        self.notifications: list[tuple[str, str]] = []
        self.submitted: list[dict[str, Any]] = []
        self.pushed_modals: list[Any] = []
        self.modal_callbacks: list[Any] = []
        self.refresh_sources: list[str] = []
        self._agents_with_children: list[Agent] = []
        self._marked_agents: set[Any] = set()

    def _get_selected_agent(self) -> Agent | None:
        return self._selected

    def notify(self, message: str, severity: str = "information", **_: Any) -> None:
        self.notifications.append((message, severity))

    def _submit_tracked_task(self, task_type: str, *args: Any, **kwargs: Any) -> object:
        self.submitted.append({"task_type": task_type, "kwargs": kwargs})
        return object()

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.modal_callbacks.append(callback)

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        self.refresh_sources.append(source)

    def _prune_stale_marked_agents(self) -> None:
        live = {a.identity for a in self._agents_with_children}
        self._marked_agents &= live


def _agent(
    status: str,
    *,
    name: str | None = "foo",
    ws: str | None = None,
    cl: str = "cl",
    linked_repos: tuple[LinkedRepoMetadata, ...] = (),
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file="/proj/cl/spec",
        status=status,
        start_time=None,
        agent_name=name,
        workspace_num=0,
        workspace_dir=ws,
        linked_repos=linked_repos,
    )


def _bulk_app(marked: list[Agent], current_tab: str = "agents") -> _FakeApp:
    """A FakeApp whose marked set + children are the given agents."""
    app = _FakeApp(None, current_tab=current_tab)
    app._agents_with_children = list(marked)
    app._marked_agents = {a.identity for a in marked}
    return app


def test_noop_on_non_agents_tab() -> None:
    app = _FakeApp(_agent("DONE"), current_tab="patches")
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert app.notifications == []


def test_notifies_when_no_agent_selected() -> None:
    app = _FakeApp(None)
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert app.notifications == [("No agent selected", "warning")]


def test_rejects_running_agent() -> None:
    app = _FakeApp(_agent("RUNNING"))
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert app.notifications[-1][1] == "warning"
    assert "done or failed" in app.notifications[-1][0]


def test_warns_when_no_agent_name(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name=None, ws=str(tmp_path)))
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert "agent name" in app.notifications[-1][0]


def test_warns_when_no_workspace() -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=None))
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert "workspace" in app.notifications[-1][0].lower()


def test_submits_preview_task_for_done_agent(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=str(tmp_path)))
    app._start_revert_selected_agent()

    assert len(app.submitted) == 1
    submitted = app.submitted[0]
    assert submitted["task_type"] == "revert_preview"
    assert "foo" in submitted["kwargs"]["dedup_key"]
    assert submitted["kwargs"]["reload_on_complete"] is False


def test_single_preview_dedup_key_includes_linked_repo(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "sase-core"
    primary.mkdir()
    linked.mkdir()
    app = _FakeApp(
        _agent(
            "DONE",
            name="foo",
            ws=str(primary),
            linked_repos=(
                LinkedRepoMetadata(
                    name="sase-core",
                    workspace_dir=str(linked),
                ),
            ),
        )
    )

    app._start_revert_selected_agent()

    assert len(app.submitted) == 1
    dedup = app.submitted[0]["kwargs"]["dedup_key"]
    # Dedup is built from stable intent data (agent + project + branch + linked
    # repo names), never the short-lived claimed workspace path.
    assert "sase-core" in dedup
    assert str(primary) not in dedup
    assert str(linked) not in dedup


def test_failed_retried_agent_is_revertable(tmp_path: Path) -> None:
    app = _FakeApp(_agent("FAILED (RETRIED)", name="foo", ws=str(tmp_path)))
    app._start_revert_selected_agent()
    assert len(app.submitted) == 1
    assert app.submitted[0]["task_type"] == "revert_preview"


def test_confirm_modal_submits_revert_and_callback_refreshes(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=str(tmp_path)))
    preview = RevertPreview(
        agent_name="foo",
        scope="agent",
        workspace_dir=str(tmp_path),
        commits=(
            RevertCommit(sha="abc", full_sha="abc123", subject="s", agent_tag="foo"),
        ),
    )

    app._open_confirm_revert_modal(preview, app._selected, None)
    assert len(app.pushed_modals) == 1

    # Decline -> nothing submitted.
    app.modal_callbacks[0](False)
    assert app.submitted == []

    # Confirm -> a revert task is submitted.
    app.modal_callbacks[0](True)
    assert len(app.submitted) == 1
    assert app.submitted[0]["task_type"] == "revert_agent"

    # Simulate task completion success -> Agents tab refresh scheduled.
    on_complete = app.submitted[0]["kwargs"]["on_complete"]

    class _Completion:
        success = True
        payload = None

    on_complete(_Completion())
    assert app.refresh_sources == ["revert_agent"]


def _submit_single_revert(app: _FakeApp, tmp_path: Path) -> Any:
    """Push a confirm modal, accept it, and return the execute on_complete."""
    agent = app._selected
    assert agent is not None
    preview = RevertPreview(
        agent_name="foo",
        scope="agent",
        workspace_dir=str(tmp_path),
        commits=(
            RevertCommit(sha="abc", full_sha="abc123", subject="s", agent_tag="foo"),
        ),
    )
    app._open_confirm_revert_modal(preview, agent, None)
    app.modal_callbacks[0](True)
    return app.submitted[0]["kwargs"]["on_complete"]


def test_failed_push_completion_with_revert_still_refreshes(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=str(tmp_path)))
    on_complete = _submit_single_revert(app, tmp_path)

    # Local revert succeeded but the push failed: success is False yet the
    # payload carries reverted_shas, so the Agents tab must still refresh.
    class _Completion:
        success = False
        payload = RevertResult(
            False,
            "Reverted 1 commit(s) for 'foo' locally, but push to GitHub failed: boom",
            reverted_shas=("abc123",),
            pushed=False,
            error="git push failed: boom",
        )

    on_complete(_Completion())
    assert app.refresh_sources == ["revert_agent"]


def test_failed_completion_without_revert_does_not_refresh(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=str(tmp_path)))
    on_complete = _submit_single_revert(app, tmp_path)

    # The revert itself failed (rolled back, no commit): nothing changed, so
    # no refresh should be scheduled.
    class _Completion:
        success = False
        payload = RevertResult(
            False,
            "Revert failed and was rolled back: conflict",
            error="conflict",
        )

    on_complete(_Completion())
    assert app.refresh_sources == []


# ---------------------------------------------------------------------------
# Bulk (marked-agent) revert
# ---------------------------------------------------------------------------


def test_no_marks_keeps_selected_agent_behavior(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=str(tmp_path)))
    # No marks -> single selected-agent preview, not a bulk dedup key.
    app._start_revert_selected_agent()
    assert len(app.submitted) == 1
    dedup = app.submitted[0]["kwargs"]["dedup_key"]
    # Stable intent data: agent + project file + Patch name, not the
    # short-lived workspace path the agent ran in.
    assert dedup == "revert_preview:foo:/proj/cl/spec:cl"
    assert str(tmp_path) not in dedup
    assert "bulk" not in dedup


def test_marks_route_to_single_bulk_preview(tmp_path: Path) -> None:
    foo = _agent("DONE", name="foo", ws=str(tmp_path), cl="cl")
    bar = _agent("DONE", name="bar", ws=str(tmp_path), cl="cl")
    app = _bulk_app([foo, bar])

    app._start_revert_selected_agent()

    assert len(app.submitted) == 1
    submitted = app.submitted[0]
    assert submitted["task_type"] == "revert_preview"
    dedup = submitted["kwargs"]["dedup_key"]
    assert dedup.startswith("revert_preview:bulk:")
    assert "bar,foo" in dedup  # sorted agent names
    assert submitted["kwargs"]["reload_on_complete"] is False


def test_bulk_preview_dedup_key_includes_linked_repo(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "sase-core"
    primary.mkdir()
    linked.mkdir()
    linked_meta = (
        LinkedRepoMetadata(
            name="sase-core",
            workspace_dir=str(linked),
        ),
    )
    foo = _agent(
        "DONE",
        name="foo",
        ws=str(primary),
        cl="cl",
        linked_repos=linked_meta,
    )
    bar = _agent(
        "DONE",
        name="bar",
        ws=str(primary),
        cl="cl",
        linked_repos=linked_meta,
    )
    app = _bulk_app([foo, bar])

    app._start_revert_selected_agent()

    assert len(app.submitted) == 1
    dedup = app.submitted[0]["kwargs"]["dedup_key"]
    # The linked repo name (stable intent data) drives the dedup key; the
    # claimed workspace paths never do.
    assert "sase-core" in dedup
    assert str(primary) not in dedup
    assert str(linked) not in dedup


def test_stale_marks_warn_and_do_not_submit() -> None:
    foo = _agent("DONE", name="foo", ws=None, cl="cl_foo")
    app = _bulk_app([])  # no live children
    app._marked_agents = {foo.identity}  # mark references a vanished row

    app._start_revert_selected_agent()

    assert app.submitted == []
    assert app.notifications[-1] == ("No marked agents remain", "warning")


def test_non_revertable_marks_skipped_with_feedback(tmp_path: Path) -> None:
    done = _agent("DONE", name="foo", ws=str(tmp_path), cl="cl_foo")
    running = _agent("RUNNING", name="bar", ws=str(tmp_path), cl="cl_bar")
    app = _bulk_app([done, running])

    app._start_revert_selected_agent()

    # The running agent is skipped (with feedback) but the done one proceeds.
    assert len(app.submitted) == 1
    assert app.submitted[0]["task_type"] == "revert_preview"
    assert any("Skipping" in msg and sev == "warning" for msg, sev in app.notifications)


def test_all_non_revertable_marks_do_not_submit(tmp_path: Path) -> None:
    a = _agent("RUNNING", name="foo", ws=str(tmp_path), cl="cl_foo")
    b = _agent("RUNNING", name="bar", ws=str(tmp_path), cl="cl_bar")
    app = _bulk_app([a, b])

    app._start_revert_selected_agent()

    assert app.submitted == []
    assert any("revertable" in msg for msg, _ in app.notifications)


def test_mixed_workspace_marks_error_and_do_not_submit(tmp_path: Path) -> None:
    ws1 = tmp_path / "w1"
    ws2 = tmp_path / "w2"
    ws1.mkdir()
    ws2.mkdir()
    foo = _agent("DONE", name="foo", ws=str(ws1), cl="cl_foo")
    bar = _agent("DONE", name="bar", ws=str(ws2), cl="cl_bar")
    app = _bulk_app([foo, bar])

    app._start_revert_selected_agent()

    assert app.submitted == []
    assert app.pushed_modals == []
    assert any(
        "multiple workspaces" in msg and sev == "error"
        for msg, sev in app.notifications
    )


def test_mixed_patch_branch_marks_error_and_do_not_submit(
    tmp_path: Path,
) -> None:
    # Same workspace but two different Patch branches: a single fresh
    # checkout cannot represent both, so the bulk revert is rejected.
    foo = _agent("DONE", name="foo", ws=str(tmp_path), cl="cl_foo")
    bar = _agent("DONE", name="bar", ws=str(tmp_path), cl="cl_bar")
    app = _bulk_app([foo, bar])

    app._start_revert_selected_agent()

    assert app.submitted == []
    assert app.pushed_modals == []
    assert any(
        "Patch branches" in msg and sev == "error" for msg, sev in app.notifications
    )


def test_confirm_bulk_preview_submits_execute_and_refreshes(tmp_path: Path) -> None:
    app = _FakeApp(None)
    preview = BulkRevertPreview(
        workspace_dir=str(tmp_path),
        targets=(
            RevertTarget("foo", "foo", str(tmp_path)),
            RevertTarget("bar", "bar", str(tmp_path)),
        ),
        commits=(
            RevertCommit(sha="abc", full_sha="abc123", subject="s", agent_tag="foo"),
        ),
        matched_target_names=("foo", "bar"),
    )
    representative = _agent("DONE", name="foo", ws=str(tmp_path), cl="cl_foo")

    app._open_confirm_bulk_revert_modal(preview, representative)
    assert len(app.pushed_modals) == 1

    # Decline -> nothing submitted.
    app.modal_callbacks[0](False)
    assert app.submitted == []

    # Confirm -> one bulk execute task is submitted.
    app.modal_callbacks[0](True)
    assert len(app.submitted) == 1
    assert app.submitted[0]["task_type"] == "revert_agent"
    assert app.submitted[0]["kwargs"]["dedup_key"].startswith("revert_agent:bulk:")

    on_complete = app.submitted[0]["kwargs"]["on_complete"]

    class _Completion:
        success = True
        payload = None

    on_complete(_Completion())
    assert app.refresh_sources == ["revert_agent"]


def test_failed_bulk_push_completion_with_revert_still_refreshes(
    tmp_path: Path,
) -> None:
    app = _FakeApp(None)
    preview = BulkRevertPreview(
        workspace_dir=str(tmp_path),
        targets=(
            RevertTarget("foo", "foo", str(tmp_path)),
            RevertTarget("bar", "bar", str(tmp_path)),
        ),
        commits=(
            RevertCommit(sha="abc", full_sha="abc123", subject="s", agent_tag="foo"),
        ),
        matched_target_names=("foo", "bar"),
    )
    representative = _agent("DONE", name="foo", ws=str(tmp_path), cl="cl_foo")
    app._open_confirm_bulk_revert_modal(preview, representative)
    app.modal_callbacks[0](True)
    on_complete = app.submitted[0]["kwargs"]["on_complete"]

    # Local bulk revert succeeded but the push failed: refresh anyway.
    class _Completion:
        success = False
        payload = BulkRevertResult(
            False,
            "Reverted 1 commit(s) across 2 agent(s) locally, "
            "but push to GitHub failed: boom",
            reverted_shas=("abc123",),
            agent_names=("foo", "bar"),
            pushed=False,
            error="git push failed: boom",
        )

    on_complete(_Completion())
    assert app.refresh_sources == ["revert_agent"]
