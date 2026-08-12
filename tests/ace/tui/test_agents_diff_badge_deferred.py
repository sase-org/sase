"""Tests for the deferred, coalesced persisted diff-badge classification.

Persisted diff-badge classification reads every referenced diff file off the
startup-critical loader path by ``AgentDiffBadgeMixin``: a coalesced
background worker classifies the visible rows that still need it after the
first agents load applies, deduped by referenced path, then patches changed
rows in place by identity.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _loading_diff_badges as diff_badges_mod
from sase.ace.tui.actions.agents._loading_diff_badges import (
    AgentDiffBadgeMixin,
    _compute_diff_badges,
    carry_over_diff_badges,
)
from sase.ace.tui.models import _agent_status_diff as agent_status_diff_mod
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.nav_gate import NavigationGate


class _FakeApp(AgentDiffBadgeMixin):
    def __init__(self) -> None:
        self._agents_first_load_done = True
        self._diff_badge_scan_scheduled = False
        self._diff_badge_scan_running = False
        self._diff_badge_scan_pending = False
        self._diff_badge_scan_source = "unknown"
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._nav_gate = NavigationGate(window_s=0.25)
        self._scheduled: list[Any] = []
        self._timer_calls: list[tuple[float, Any]] = []
        self._patched: list[Agent] = []

    def _spawn_diff_badge_classification_task(self) -> None:
        """Record scheduling without starting a task in narrow sync tests."""
        self._scheduled.append(self._run_diff_badge_classification)

    def set_timer(self, delay: float, callback: Any) -> None:
        self._timer_calls.append((delay, callback))

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self._patched.append(agent)
        return True


def _agent(
    *,
    cl_name: str = "feat",
    raw_suffix: str = "20260615190000",
    status: str = "DONE",
    diff_path: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix=raw_suffix,
        diff_path=diff_path,
    )


def _agent_with_linked_diff(
    *,
    cl_name: str = "feat",
    raw_suffix: str = "20260615190000",
    linked_diff_path: str,
    workspace_dir: str = "/tmp/primary",
    linked_workspace_dir: str = "/tmp/linked",
) -> Agent:
    from sase.ace.tui.models.agent_types import LinkedRepoMetadata

    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix=raw_suffix,
        workspace_dir=workspace_dir,
        linked_repos=(
            LinkedRepoMetadata(name="linked-repo", workspace_dir=linked_workspace_dir),
        ),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: linked change",
                    "sha": "abcdef0123456789",
                    "cwd": linked_workspace_dir,
                    "diff_path": linked_diff_path,
                },
            ],
        },
    )


def _write_git_diff(path: Path, changed_path: str) -> None:
    path.write_text(
        f"""diff --git a/{changed_path} b/{changed_path}
--- a/{changed_path}
+++ b/{changed_path}
@@ -1 +1 @@
-old
+new
""",
        encoding="utf-8",
    )


# --- scheduling / coalescing -------------------------------------------------


def test_schedule_noop_before_first_load() -> None:
    app = _FakeApp()
    app._agents_first_load_done = False

    app._schedule_diff_badge_classification(source="apply")

    assert app._scheduled == []
    assert app._diff_badge_scan_scheduled is False


def test_schedule_queues_worker_after_first_load() -> None:
    app = _FakeApp()

    app._schedule_diff_badge_classification(source="apply")

    assert app._diff_badge_scan_scheduled is True
    assert app._diff_badge_scan_source == "apply"
    assert app._scheduled == [app._run_diff_badge_classification]


def test_schedule_collapses_to_one_queued_worker() -> None:
    app = _FakeApp()

    app._schedule_diff_badge_classification(source="apply")
    app._schedule_diff_badge_classification(source="auto_refresh")

    # Second request while one is already queued must not enqueue again.
    assert len(app._scheduled) == 1


def test_schedule_marks_pending_while_running() -> None:
    app = _FakeApp()
    app._diff_badge_scan_running = True

    app._schedule_diff_badge_classification(source="artifact_watcher")

    assert app._diff_badge_scan_pending is True
    assert app._scheduled == []


# --- candidate scope ---------------------------------------------------------


def test_candidates_include_unclassified_primary_diff_row(tmp_path: Path) -> None:
    app = _FakeApp()
    diff_path = tmp_path / "commit.diff"
    _write_git_diff(diff_path, "src/app.py")
    with_diff = _agent(cl_name="withdiff", raw_suffix="1", diff_path=str(diff_path))
    app._agents = [with_diff]

    assert app._diff_badge_candidates() == [with_diff]


def test_candidates_exclude_already_classified_row(tmp_path: Path) -> None:
    app = _FakeApp()
    diff_path = tmp_path / "commit.diff"
    _write_git_diff(diff_path, "src/app.py")
    already_classified = _agent(
        cl_name="classified", raw_suffix="1", diff_path=str(diff_path)
    )
    already_classified.diff_has_real_edits = True
    app._agents = [already_classified]

    assert app._diff_badge_candidates() == []


def test_candidates_exclude_row_without_any_diff_reference() -> None:
    app = _FakeApp()
    bare = _agent(cl_name="bare", raw_suffix="1")
    app._agents = [bare]

    assert app._diff_badge_candidates() == []


def test_candidates_include_unclassified_linked_commit_row(tmp_path: Path) -> None:
    app = _FakeApp()
    linked_diff = tmp_path / "linked.diff"
    _write_git_diff(linked_diff, "src/lib.rs")
    with_linked = _agent_with_linked_diff(
        cl_name="linked", raw_suffix="1", linked_diff_path=str(linked_diff)
    )
    app._agents = [with_linked]

    assert app._diff_badge_candidates() == [with_linked]


def test_candidates_exclude_row_with_both_fields_already_classified(
    tmp_path: Path,
) -> None:
    app = _FakeApp()
    diff_path = tmp_path / "commit.diff"
    _write_git_diff(diff_path, "src/app.py")
    linked_diff = tmp_path / "linked.diff"
    _write_git_diff(linked_diff, "src/lib.rs")
    agent = _agent_with_linked_diff(
        cl_name="both", raw_suffix="1", linked_diff_path=str(linked_diff)
    )
    agent.diff_path = str(diff_path)
    agent.diff_has_real_edits = True
    agent.linked_file_change_hint = False
    app._agents = [agent]

    assert app._diff_badge_candidates() == []


# --- carry-over across reloads ----------------------------------------------


def test_carry_over_copies_primary_badge_when_diff_path_unchanged() -> None:
    previous = _agent(cl_name="feat", raw_suffix="1", diff_path="/tmp/x.diff")
    previous.diff_has_real_edits = True
    fresh = _agent(cl_name="feat", raw_suffix="1", diff_path="/tmp/x.diff")

    carry_over_diff_badges([previous], [fresh])

    assert fresh.diff_has_real_edits is True


def test_carry_over_skips_primary_badge_when_diff_path_changed() -> None:
    """A row whose persisted diff advanced must not reuse the stale answer."""
    previous = _agent(cl_name="feat", raw_suffix="1", diff_path="/tmp/x.diff")
    previous.diff_has_real_edits = True
    fresh = _agent(cl_name="feat", raw_suffix="1", diff_path="/tmp/y.diff")

    carry_over_diff_badges([previous], [fresh])

    assert fresh.diff_has_real_edits is None


def test_carry_over_copies_linked_hint_when_paths_unchanged() -> None:
    previous = _agent_with_linked_diff(
        cl_name="feat", raw_suffix="1", linked_diff_path="/tmp/linked.diff"
    )
    previous.linked_file_change_hint = True
    fresh = _agent_with_linked_diff(
        cl_name="feat", raw_suffix="1", linked_diff_path="/tmp/linked.diff"
    )

    carry_over_diff_badges([previous], [fresh])

    assert fresh.linked_file_change_hint is True


def test_carry_over_skips_linked_hint_when_paths_changed() -> None:
    previous = _agent_with_linked_diff(
        cl_name="feat", raw_suffix="1", linked_diff_path="/tmp/linked-old.diff"
    )
    previous.linked_file_change_hint = True
    fresh = _agent_with_linked_diff(
        cl_name="feat", raw_suffix="1", linked_diff_path="/tmp/linked-new.diff"
    )

    carry_over_diff_badges([previous], [fresh])

    assert fresh.linked_file_change_hint is None


def test_carry_over_skips_rows_with_no_prior_classification() -> None:
    previous = _agent(cl_name="feat", raw_suffix="1", diff_path="/tmp/x.diff")
    fresh = _agent(cl_name="feat", raw_suffix="1", diff_path="/tmp/x.diff")

    carry_over_diff_badges([previous], [fresh])

    assert fresh.diff_has_real_edits is None


def test_carry_over_does_not_overwrite_already_classified_fresh_row() -> None:
    previous = _agent(cl_name="feat", raw_suffix="1", diff_path="/tmp/x.diff")
    previous.diff_has_real_edits = True
    fresh = _agent(cl_name="feat", raw_suffix="1", diff_path="/tmp/x.diff")
    fresh.diff_has_real_edits = False

    carry_over_diff_badges([previous], [fresh])

    assert fresh.diff_has_real_edits is False


# --- compute (off-thread body): dedup by referenced path ---------------------


def test_compute_dedupes_shared_path_across_candidates(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """N references over M unique paths must cost exactly M classify calls."""
    shared = tmp_path / "shared.diff"
    _write_git_diff(shared, "src/app.py")
    other = tmp_path / "other.diff"
    _write_git_diff(other, "src/other.py")

    a = _agent(cl_name="a", raw_suffix="1", diff_path=str(shared))
    b = _agent(cl_name="b", raw_suffix="2", diff_path=str(shared))
    c = _agent(cl_name="c", raw_suffix="3", diff_path=str(other))

    calls: list[str] = []
    real_diff_has_real_edits = agent_status_diff_mod.diff_has_real_edits

    def _counting(path: str) -> bool:
        calls.append(path)
        return real_diff_has_real_edits(path)

    monkeypatch.setattr(agent_status_diff_mod, "diff_has_real_edits", _counting)

    results = _compute_diff_badges([a, b, c])

    assert sorted(calls) == sorted([str(shared), str(other)])
    assert results[a.identity] == (True, None)
    assert results[b.identity] == (True, None)
    assert results[c.identity] == (True, None)


def test_compute_dedupes_multiple_linked_references_on_one_row(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from sase.ace.tui.models.agent_types import LinkedRepoMetadata

    shared_linked = tmp_path / "shared-linked.diff"
    _write_git_diff(shared_linked, "src/lib.rs")
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feat",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 6, 15, 19, 0, 0),
        raw_suffix="1",
        workspace_dir="/tmp/primary",
        linked_repos=(
            LinkedRepoMetadata(name="repo-a", workspace_dir="/tmp/repo-a"),
            LinkedRepoMetadata(name="repo-b", workspace_dir="/tmp/repo-b"),
        ),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: first",
                    "sha": "1111111111111111",
                    "cwd": "/tmp/repo-a",
                    "diff_path": str(shared_linked),
                },
                {
                    "message": "feat: second",
                    "sha": "2222222222222222",
                    "cwd": "/tmp/repo-b",
                    "diff_path": str(shared_linked),
                },
            ],
        },
    )

    calls: list[str] = []
    real_diff_has_real_edits = agent_status_diff_mod.diff_has_real_edits

    def _counting(path: str) -> bool:
        calls.append(path)
        return real_diff_has_real_edits(path)

    monkeypatch.setattr(agent_status_diff_mod, "diff_has_real_edits", _counting)

    results = _compute_diff_badges([agent])

    assert calls == [str(shared_linked)]
    assert results[agent.identity] == (None, True)


def test_compute_keys_by_identity_not_object() -> None:
    a = _agent(cl_name="a", raw_suffix="1")
    b = _agent(cl_name="b", raw_suffix="2")

    results = _compute_diff_badges([a, b])

    assert set(results) == {a.identity, b.identity}


# --- apply by identity -------------------------------------------------------


def test_apply_patches_only_changed_rows() -> None:
    app = _FakeApp()
    changed = _agent(cl_name="changed", raw_suffix="1")
    same = _agent(cl_name="same", raw_suffix="2")
    same.diff_has_real_edits = True
    app._agents = [changed, same]
    app._agents_with_children = [changed, same]

    app._apply_diff_badge_results(
        {changed.identity: (True, None), same.identity: (True, None)}
    )

    assert changed.diff_has_real_edits is True
    assert app._patched == [changed]  # unchanged row not repainted


def test_apply_rematches_current_object_by_identity() -> None:
    """A refresh may rebuild the list; the badge lands on the live object."""
    app = _FakeApp()
    snapshot = _agent(cl_name="feat", raw_suffix="1")
    rebuilt = _agent(cl_name="feat", raw_suffix="1")
    app._agents = [rebuilt]
    app._agents_with_children = [rebuilt]

    app._apply_diff_badge_results({snapshot.identity: (True, None)})

    assert rebuilt.diff_has_real_edits is True
    assert snapshot.diff_has_real_edits is None
    assert app._patched == [rebuilt]


# --- full async worker -------------------------------------------------------


@pytest.mark.asyncio
async def test_run_defers_behind_navigation_gate(tmp_path: Path) -> None:
    app = _FakeApp()
    diff_path = tmp_path / "commit.diff"
    _write_git_diff(diff_path, "src/app.py")
    app._agents = [_agent(diff_path=str(diff_path))]
    app._nav_gate.record()  # user is mid j/k burst

    await app._run_diff_badge_classification()

    # Deferred via set_timer; no compute/apply happened this pass.
    assert len(app._timer_calls) == 1
    assert app._patched == []
    # Coalescing state stays armed so the retry isn't dropped.
    assert app._diff_badge_scan_scheduled is False


@pytest.mark.asyncio
async def test_run_computes_applies_and_clears_running(tmp_path: Path) -> None:
    app = _FakeApp()
    diff_path = tmp_path / "commit.diff"
    _write_git_diff(diff_path, "src/app.py")
    agent = _agent(cl_name="feat", raw_suffix="1", diff_path=str(diff_path))
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._diff_badge_scan_scheduled = True

    await app._run_diff_badge_classification()

    assert agent.diff_has_real_edits is True
    assert app._patched == [agent]
    assert app._diff_badge_scan_scheduled is False
    assert app._diff_badge_scan_running is False


@pytest.mark.asyncio
async def test_run_rearms_when_pending(tmp_path: Path) -> None:
    app = _FakeApp()
    diff_path = tmp_path / "commit.diff"
    _write_git_diff(diff_path, "src/app.py")
    agent = _agent(diff_path=str(diff_path))
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._diff_badge_scan_pending = True

    await app._run_diff_badge_classification()

    # Trailing request consumed and a fresh worker queued.
    assert app._diff_badge_scan_pending is False
    assert app._scheduled == [app._run_diff_badge_classification]


@pytest.mark.asyncio
async def test_run_noop_without_candidates() -> None:
    app = _FakeApp()
    app._agents = [_agent(status="DONE")]
    app._diff_badge_scan_scheduled = True

    await app._run_diff_badge_classification()

    assert app._diff_badge_scan_running is False
    assert app._patched == []


@pytest.mark.asyncio
async def test_diff_badge_worker_does_not_block_loop_pump(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A stuck worker thread must not keep loop messages from progressing."""
    app = _FakeApp()
    diff_path = tmp_path / "commit.diff"
    _write_git_diff(diff_path, "src/app.py")
    agent = _agent(diff_path=str(diff_path))
    app._agents = [agent]
    app._agents_with_children = [agent]
    app._diff_badge_scan_scheduled = True
    entered = threading.Event()
    release = threading.Event()

    def _slow_compute(
        candidates: list[Agent],
    ) -> dict[tuple[AgentType, str, str | None], tuple[bool | None, bool | None]]:
        entered.set()
        release.wait(timeout=1.0)
        return {candidate.identity: (True, None) for candidate in candidates}

    monkeypatch.setattr(diff_badges_mod, "_compute_diff_badges", _slow_compute)
    try:
        AgentDiffBadgeMixin._spawn_diff_badge_classification_task(app)
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)

        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
        assert app._diff_badge_scan_running is True
    finally:
        release.set()
        tasks = list(getattr(app, "_diff_badge_async_tasks", ()))
        if tasks:
            await asyncio.gather(*tasks)
