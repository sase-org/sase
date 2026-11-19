"""Off-thread compute and in-place apply coverage for bead warmup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents._loading_bead_warmup import _AgentBeadWarmupResults
from sase.ace.tui.agent_completion import (
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
)
from sase.ace.tui.models.agent_bead import (
    _BEAD_DISPLAY_CACHE,
    _bead_display_cache_key,
    agent_has_confirmed_bead,
    warm_confirmed_bead_displays,
)
from sase.ace.tui.models.agent_wait_beads import _WAIT_BEAD_STATUS_CACHE
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.bead.model import Issue
from tests.ace.tui._agents_bead_warmup_helpers import (
    FakeApp,
    clear_bead_display_cache,
    confirmed_lookup,
    make_agent,
)

__all__ = [
    "test_apply_noop_without_results",
    "test_apply_patches_only_result_rows",
    "test_apply_patches_rows_losing_confirmed_bead",
    "test_apply_rematches_current_object_by_identity",
    "test_apply_wait_bead_status_results_keeps_singleton_id_and_adds_warm_glyph",
    "test_apply_wait_bead_status_results_passes_fresh_count_override",
    "test_apply_wait_bead_status_results_rebuilds_once_on_patch_failure",
    "test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key",
    "test_warm_confirmed_bead_displays_omits_missing_and_non_candidates",
    "test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation",
    "test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate",
    "test_warm_confirmed_bead_displays_reuses_store_for_batch",
]


def test_warm_confirmed_bead_displays_dedupes_lookups_by_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def counting_lookup(candidate_id: str, **_: object) -> Issue:
        calls.append(candidate_id)
        return Issue(id=candidate_id, title="", description="")

    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", counting_lookup)

    # a1 and a2 share a candidate + project + workspace, so one cache key; a3 is
    # a distinct candidate. Two unique keys → two bead-store lookups total.
    a1 = make_agent(agent_name="sase-x.3", cl_name="a1", raw_suffix="1")
    a2 = make_agent(agent_name="sase-x.3", cl_name="a2", raw_suffix="2")
    a3 = make_agent(agent_name="sase-y.4", cl_name="a3", raw_suffix="3")

    results = warm_confirmed_bead_displays([a1, a2, a3])

    assert calls == ["sase-x.3", "sase-y.4"]
    assert results == {a1.identity: True, a2.identity: True, a3.identity: True}


def test_warm_confirmed_bead_displays_omits_missing_and_non_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: None,
    )

    missing = make_agent(agent_name="sase-x.3", cl_name="missing", raw_suffix="1")
    ordinary = make_agent(agent_name="reviewer", cl_name="ordinary", raw_suffix="2")

    results = warm_confirmed_bead_displays([missing, ordinary])

    assert results == {}


def test_warm_confirmed_bead_displays_reports_deleted_confirmed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3", cl_name="deleted", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3 - stale description")
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue",
        lambda candidate_id, **_: None,
    )

    results = warm_confirmed_bead_displays([agent])

    assert results == {agent.identity: False}
    assert agent_has_confirmed_bead(agent) is False


def test_warm_confirmed_bead_displays_omits_unchanged_expired_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(agent_name="sase-x.3", cl_name="same", raw_suffix="1")
    key = _bead_display_cache_key(agent)
    assert key is not None
    _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3")
    monkeypatch.setattr("sase.agent.bead_display.lookup_bead_issue", confirmed_lookup)

    results = warm_confirmed_bead_displays([agent])

    assert results == {}
    assert agent_has_confirmed_bead(agent) is True


def test_warm_confirmed_bead_displays_reuses_store_for_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    beads_dir = workspace / "sdd" / "beads"
    beads_dir.mkdir(parents=True)
    issues = [
        _issue_payload("batch-x.3", "First"),
        _issue_payload("batch-y.4", "Second"),
    ]
    (beads_dir / "issues.jsonl").write_text(
        "".join(json.dumps(issue) + "\n" for issue in issues),
        encoding="utf-8",
    )

    from sase.bead import project as project_module

    real_bead_project = project_module.BeadProject
    constructions: list[Path] = []

    def counting_bead_project(
        root_dir: str | Path,
        beads_dirname: str = "sdd/beads",
    ) -> Any:
        constructions.append(Path(root_dir) / beads_dirname)
        return real_bead_project(root_dir, beads_dirname=beads_dirname)

    monkeypatch.setattr(project_module, "BeadProject", counting_bead_project)
    first = make_agent(
        agent_name="batch-x.3",
        cl_name="first",
        raw_suffix="1",
        project_file="",
        workspace_dir=str(workspace),
    )
    second = make_agent(
        agent_name="batch-y.4",
        cl_name="second",
        raw_suffix="2",
        project_file="",
        workspace_dir=str(workspace),
    )

    results = warm_confirmed_bead_displays([first, second])

    assert results == {first.identity: True, second.identity: True}
    assert constructions == [beads_dir]


def test_apply_patches_only_result_rows() -> None:
    app = FakeApp()
    confirmed = make_agent(agent_name="sase-x.3", cl_name="confirmed", raw_suffix="1")
    other = make_agent(agent_name="sase-y.4", cl_name="other", raw_suffix="2")
    app._agents = [confirmed, other]
    app._agents_with_children = [confirmed, other]

    app._apply_bead_warmup_results(
        _AgentBeadWarmupResults({confirmed.identity: True}, set())
    )

    assert app._patched == [confirmed]


def test_apply_patches_rows_losing_confirmed_bead() -> None:
    app = FakeApp()
    removed = make_agent(agent_name="sase-x.3", cl_name="removed", raw_suffix="1")
    other = make_agent(agent_name="sase-y.4", cl_name="other", raw_suffix="2")
    app._agents = [removed, other]
    app._agents_with_children = [removed, other]

    app._apply_bead_warmup_results(
        _AgentBeadWarmupResults({removed.identity: False}, set())
    )

    assert app._patched == [removed]


def test_apply_rematches_current_object_by_identity() -> None:
    """A refresh may rebuild the list; the patch lands on the live object."""
    app = FakeApp()
    snapshot = make_agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    rebuilt = make_agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [rebuilt]
    app._agents_with_children = [rebuilt]

    app._apply_bead_warmup_results(
        _AgentBeadWarmupResults({snapshot.identity: True}, set())
    )

    assert app._patched == [rebuilt]


def test_apply_noop_without_results() -> None:
    app = FakeApp()
    app._agents = [make_agent()]

    app._apply_bead_warmup_results(_AgentBeadWarmupResults({}, set()))

    assert app._patched == []


def test_apply_wait_bead_status_results_passes_fresh_count_override() -> None:
    app = FakeApp()
    waiter = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-1"],
        cl_name="waiter",
        raw_suffix="waiter",
    )
    _WAIT_BEAD_STATUS_CACHE.set(("proj", "sase-1"), "closed")
    app._agents = [waiter]
    app._agents_with_children = [waiter]

    app._apply_bead_warmup_results(_AgentBeadWarmupResults({}, {waiter.identity}))

    assert app._patched == [waiter]
    assert app._patch_kwargs == [
        {
            "wait_dependency_counts": WaitDependencyStatusCounts(
                beads=WaitBeadStatusCounts(closed=1)
            )
        }
    ]


def test_apply_wait_bead_status_results_keeps_singleton_id_and_adds_warm_glyph() -> (
    None
):
    app = FakeApp()
    waiter = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-1"],
        cl_name="waiter",
        raw_suffix="waiter",
    )
    cold_left, _, _ = format_agent_option(waiter, 0, is_selected=False)
    _WAIT_BEAD_STATUS_CACHE.set(("proj", "sase-1"), "in_progress")
    app._agents = [waiter]
    app._agents_with_children = [waiter]

    app._apply_bead_warmup_results(_AgentBeadWarmupResults({}, {waiter.identity}))

    assert "waiter (WAITING sase-1)" in cold_left.plain
    assert app._patched == [waiter]
    assert app._patch_kwargs == [
        {
            "wait_dependency_counts": WaitDependencyStatusCounts(
                beads=WaitBeadStatusCounts(in_progress=1)
            )
        }
    ]
    wait_counts = app._patch_kwargs[0]["wait_dependency_counts"]
    assert isinstance(wait_counts, WaitDependencyStatusCounts)
    warm_left, _, _ = format_agent_option(
        waiter,
        0,
        is_selected=False,
        wait_dependency_counts=wait_counts,
    )
    assert "waiter (WAITING ◐ sase-1)" in warm_left.plain


def test_apply_wait_bead_status_results_rebuilds_once_on_patch_failure() -> None:
    app = FakeApp()
    app._patch_success = False
    first = make_agent(
        status="WAITING",
        waiting_for_beads=["a"],
        cl_name="first",
        raw_suffix="first",
    )
    second = make_agent(
        status="WAITING",
        waiting_for_beads=["b"],
        cl_name="second",
        raw_suffix="second",
    )
    _WAIT_BEAD_STATUS_CACHE.set(("proj", "a"), "closed")
    _WAIT_BEAD_STATUS_CACHE.set(("proj", "b"), "open")
    app._agents = [first, second]
    app._agents_with_children = [first, second]

    app._apply_bead_warmup_results(
        _AgentBeadWarmupResults({}, {first.identity, second.identity})
    )

    assert app._patched == [first, second]
    assert app._refresh_calls == [{"list_changed": True, "defer_detail": True}]


def _issue_payload(issue_id: str, title: str) -> dict[str, object]:
    timestamp = "2026-07-12T00:00:00Z"
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": "plan",
        "parent_id": None,
        "owner": "",
        "assignee": "",
        "created_at": timestamp,
        "created_by": "",
        "updated_at": timestamp,
        "closed_at": None,
        "close_reason": None,
        "description": "",
        "notes": "",
        "design": "",
        "is_ready_to_work": False,
        "patch_name": "",
        "patch_bug_id": "",
        "dependencies": [],
    }
