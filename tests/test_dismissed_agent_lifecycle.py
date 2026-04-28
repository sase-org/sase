"""End-to-end tests for the dismissed-agent name lifecycle (sase-10 phase 6).

These tests stitch together the helpers that earlier phases delivered —
prefix allocation, dismissal-time rename, reference rewrites, and
revive-time prefix stripping — and exercise them through the dismiss and
revive mixins on a shared in-memory + on-disk fixture so a regression in
any one phase will surface here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._dismissing import AgentDismissingMixin
from sase.ace.tui.actions.agents._revive import AgentRevivalMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.names import (
    collect_dismissed_taken_names,
    find_named_agent,
    is_dismissed_prefixed,
)


class FakeFullApp(AgentDismissingMixin, AgentRevivalMixin):
    """App stub that exposes both the dismiss and revive flows."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.changespecs = []  # type: ignore[assignment]
        self._agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self._scheduled: list[tuple[Callable[..., object], tuple[object, ...]]] = []
        self.notifications: list[tuple[str, str]] = []
        self.load_count = 0
        self.refilter_count = 0
        self.notification_refreshes = 0
        self.notification_refreshes_async = 0
        self.async_refreshes = 0
        self.restored: list[tuple[tuple[AgentType, str, str | None], str | None]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _load_agents(self) -> None:
        self.load_count += 1

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        self.refilter_count += 1

    def _refresh_notification_count(self) -> None:
        self.notification_refreshes += 1

    async def _refresh_notification_count_async(self) -> None:
        self.notification_refreshes_async += 1

    def _schedule_agents_async_refresh(self) -> None:
        self.async_refreshes += 1

    def _refresh_agents_display(self, *, list_changed: bool) -> None:
        pass

    def call_later(self, callback: Callable[..., object], *args: object) -> None:
        self._scheduled.append((callback, args))

    def _restore_agent_artifacts(
        self,
        agent: Agent,
        *,
        parent_artifacts_dir: str | None = None,
    ) -> None:
        self.restored.append((agent.identity, parent_artifacts_dir))


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "DONE",
        "start_time": datetime(2026, 4, 28, 12, 0, 0),
        "raw_suffix": "20260428120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _patch_isolated_home(tmp_path: Path):  # type: ignore[no-untyped-def]
    def _path_home() -> Path:
        return tmp_path

    return [
        patch.object(Path, "home", _path_home),
        patch(
            "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
            tmp_path / "dismissed_bundles",
        ),
        patch(
            "sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE",
            tmp_path / "dismissed_agents.json",
        ),
        patch(
            "sase.ace.dismissed_agents._OLD_BUNDLES_FILE",
            tmp_path / "old_bundles.json",
        ),
    ]


def _make_artifact_dir(tmp_path: Path, project: str, ts: str) -> Path:
    artifact_dir = (
        tmp_path / ".sase" / "projects" / project / "artifacts" / "ace-run" / ts
    )
    artifact_dir.mkdir(parents=True)
    return artifact_dir


def _flush_persistence(app: FakeFullApp) -> None:
    """Drain pending ``call_later`` callbacks synchronously."""
    while app._scheduled:
        callback, args = app._scheduled.pop(0)
        result = callback(*args)
        if asyncio.iscoroutine(result):
            asyncio.run(result)


# ---------------------------------------------------------------------------
# End-to-end lifecycle: complete -> wait/resume -> dismiss -> revive
# ---------------------------------------------------------------------------


def test_full_lifecycle_dismiss_then_revive_named_agent(tmp_path: Path) -> None:
    """Walk one named agent through dismiss + revive with a live dependent.

    ``foo`` completes; ``bar`` waits on ``foo`` and references it via
    ``%w:foo`` and ``#resume:foo`` in its prompt and ``wait_for`` marker.
    Dismissing ``foo`` must produce ``260428.foo`` everywhere — in-memory,
    in the dismissed bundle, in the dependent's wait marker, and inside
    the dependent's prompt. Reviving ``foo`` must restore the live name
    in every one of those places.
    """
    completion_day = datetime(2026, 4, 28, 12, 0, 0)
    foo_dir = _make_artifact_dir(tmp_path, "proj", "20260428100000")
    bar_dir = _make_artifact_dir(tmp_path, "proj", "20260428110000")

    (foo_dir / "agent_meta.json").write_text(json.dumps({"name": "foo"}))
    (foo_dir / "done.json").write_text(json.dumps({"outcome": "completed"}))
    (bar_dir / "agent_meta.json").write_text(
        json.dumps({"name": "bar", "wait_for": ["foo"]})
    )
    (bar_dir / "raw_xprompt.md").write_text(
        "Run after foo:\n%w:foo\n#resume:foo run more\n"
    )

    foo = _make_agent(
        cl_name="feature_foo",
        raw_suffix="20260428100000",
        stop_time=completion_day,
        agent_name="foo",
        artifacts_dir=str(foo_dir),
    )
    bar = _make_agent(
        cl_name="feature_bar",
        raw_suffix="20260428110000",
        stop_time=completion_day,
        agent_name="bar",
        artifacts_dir=str(bar_dir),
        status="WAITING",
        waiting_for=["foo"],
    )

    app = FakeFullApp()
    app._agents_with_children = [foo, bar]
    app._dismissed_agent_objects = []

    patches = _patch_isolated_home(tmp_path)
    for p in patches:
        p.start()
    try:
        # Pre-conditions: name resolves to the live artifact dir.
        pre = find_named_agent("foo")
        assert pre is not None
        assert pre.artifacts_dir == str(foo_dir)

        # ---- Dismiss ---------------------------------------------------
        app._dismiss_done_agent(foo)
        _flush_persistence(app)

        assert foo.agent_name == "260428.foo"
        assert is_dismissed_prefixed(foo.agent_name)
        # Live dependent followed the rename in memory.
        assert bar.waiting_for == ["260428.foo"]
        # Dependent's on-disk marker + prompt followed the rename too.
        assert json.loads((bar_dir / "agent_meta.json").read_text())["wait_for"] == [
            "260428.foo"
        ]
        prompt_after = (bar_dir / "raw_xprompt.md").read_text()
        assert "%w:260428.foo" in prompt_after
        assert "#resume:260428.foo" in prompt_after
        assert "%w:foo" not in prompt_after
        assert "#resume:foo " not in prompt_after

        # The prefixed name is reachable through the dismissed-bundle scan.
        assert "260428.foo" in collect_dismissed_taken_names()
        post_dismiss = find_named_agent("260428.foo")
        assert post_dismiss is not None
        assert post_dismiss.outcome == "dismissed"
        # The bare live name no longer resolves anywhere on the active path.
        assert find_named_agent("foo") is None

        # ---- Revive ----------------------------------------------------
        # Re-add the revived agent to the live list so the rewrite walker can
        # also update the in-memory dependent (mirrors the loader's behaviour
        # post-revive).
        app._agents_with_children = [foo, bar]
        # Recreate the artifact dir so the disk rewrite has something to walk
        # through; the dismiss flow deleted the agent's marker files but left
        # the directory empty.
        foo_dir.mkdir(parents=True, exist_ok=True)

        app._do_revive_agent(foo)

        assert foo.agent_name == "foo"
        # Dependent's in-memory wait reference was restored.
        assert bar.waiting_for == ["foo"]
        # Dependent's on-disk references were restored.
        assert json.loads((bar_dir / "agent_meta.json").read_text())["wait_for"] == [
            "foo"
        ]
        prompt_revived = (bar_dir / "raw_xprompt.md").read_text()
        assert "%w:foo" in prompt_revived
        assert "#resume:foo" in prompt_revived
        assert "260428.foo" not in prompt_revived
        # The dismissed-bundle scan no longer surfaces the prefixed name.
        assert "260428.foo" not in collect_dismissed_taken_names()
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# Workflow parent + child consistency through the full lifecycle
# ---------------------------------------------------------------------------


def test_workflow_parent_and_children_consistent_through_lifecycle(
    tmp_path: Path,
) -> None:
    """A workflow parent + named child both pick up and shed the prefix."""
    completion_day = datetime(2026, 4, 28, 12, 0, 0)
    parent_dir = _make_artifact_dir(tmp_path, "proj", "20260428100000")

    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="cl_a",
        raw_suffix="20260428100000",
        workflow="wf",
        stop_time=completion_day,
        agent_name="root",
        artifacts_dir=str(parent_dir),
    )
    named_child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="cl_a",
        raw_suffix="20260428100000_c0",
        parent_workflow="wf",
        parent_timestamp="20260428100000",
        stop_time=completion_day,
        agent_name="root.plan",
    )
    unnamed_child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="cl_a",
        raw_suffix="20260428100000_c1",
        parent_workflow="wf",
        parent_timestamp="20260428100000",
    )

    app = FakeFullApp()
    app._agents_with_children = [parent, named_child, unnamed_child]

    patches = _patch_isolated_home(tmp_path)
    for p in patches:
        p.start()
    try:
        with (
            patch(
                "sase.ace.tui.actions.agents._dismissing."
                "find_workflow_workspace_from_running_field",
                return_value=None,
            ),
            patch(
                "sase.ace.tui.actions.agents._dismissing.release_workspace",
                create=True,
            ),
        ):
            app._dismiss_done_agent(parent)
            _flush_persistence(app)

        assert parent.agent_name == "260428.root"
        assert named_child.agent_name == "260428.root.plan"
        assert unnamed_child.agent_name is None

        # Both renamed names reached the dismissed taken-set.
        taken = collect_dismissed_taken_names()
        assert "260428.root" in taken
        assert "260428.root.plan" in taken

        # The same revive handles parent + workflow children together.
        app._do_revive_agent(parent)

        assert parent.agent_name == "root"
        assert named_child.agent_name == "root.plan"
        # The unnamed child stays unnamed — revive only strips real prefixes.
        assert unnamed_child.agent_name is None
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# Same-day collisions
# ---------------------------------------------------------------------------


def test_same_day_two_named_foo_get_unique_dismissed_names_then_revive(
    tmp_path: Path,
) -> None:
    """Two same-day ``foo`` agents get unique dismissed names; both revive."""
    completion_day = datetime(2026, 4, 28, 12, 0, 0)
    a_dir = _make_artifact_dir(tmp_path, "proj", "20260428100000")
    b_dir = _make_artifact_dir(tmp_path, "proj", "20260428110000")

    foo_a = _make_agent(
        cl_name="cl_a",
        raw_suffix="20260428100000",
        stop_time=completion_day,
        agent_name="foo",
        artifacts_dir=str(a_dir),
    )
    foo_b = _make_agent(
        cl_name="cl_b",
        raw_suffix="20260428110000",
        stop_time=completion_day,
        agent_name="foo",
        artifacts_dir=str(b_dir),
    )

    app = FakeFullApp()
    app._agents_with_children = [foo_a, foo_b]
    app._agents = [foo_a, foo_b]

    patches = _patch_isolated_home(tmp_path)
    for p in patches:
        p.start()
    try:
        app._do_dismiss_all([foo_a, foo_b])
        _flush_persistence(app)

        names = sorted(a.agent_name or "" for a in [foo_a, foo_b])
        assert names == ["260428.foo", "260428.foo.2"]

        # Each prefixed name resolves through find_named_agent's bundle path.
        assert find_named_agent("260428.foo") is not None
        assert find_named_agent("260428.foo.2") is not None

        # Revive each one. The first revive frees ``foo``; the second hits
        # the now-claimed ``foo`` slot and falls back to a fresh auto-name.
        app._do_revive_agent(foo_a)
        first_live_name = foo_a.agent_name
        # foo_a's prefix was stripped — even with the collision suffix, the
        # name regains its original form because no other agent claims it.
        assert first_live_name == "foo"

        # Add foo_a back to the active scan so its name registers as taken.
        # _do_revive_agent already removed it from _dismissed_agent_objects
        # by clearing identities; reseed _agents_with_children for the
        # second revive's allocator.
        app._agents_with_children = [foo_a]

        app._do_revive_agent(foo_b)
        assert foo_b.agent_name is not None
        # Either an auto-name fallback (when the first revive's "foo" is
        # observable through scan), or the unique base "foo.2" preserved
        # from the dismissal collision suffix. Both keep the agents
        # distinct, which is the lifecycle invariant.
        assert foo_b.agent_name != first_live_name
        assert not is_dismissed_prefixed(foo_b.agent_name)
    finally:
        for p in patches:
            p.stop()
