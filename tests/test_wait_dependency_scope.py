"""Scoped wait views preserve named-wait decisions and membership."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    artifact_scope_keys,
    marker_scope_keys,
    resolve_wait_release,
    select_scope_rows,
)
from sase.scripts._chop_wait_checks_terminal import terminal_blockers
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_submitted_planner

_Row = tuple[Path, dict[str, Any], str]


def _row(artifact_dir: Path, project_name: str | None = None) -> _Row:
    return (
        artifact_dir,
        json.loads((artifact_dir / "agent_meta.json").read_text(encoding="utf-8")),
        project_name or artifact_dir.parents[2].name,
    )


def _index(rows: Iterable[_Row]) -> WaitDependencyIndex:
    index = WaitDependencyIndex.empty()
    index.add_many(rows)
    return index


def _make_waiter(
    tmp_path: Path,
    suffix: str,
    waiting_for: str,
    *,
    workflow_name: str | None = None,
    agent_session: str | None = None,
) -> Path:
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        suffix,
        f"waiter-{suffix}",
        workflow_name=workflow_name,
        agent_session=agent_session,
    )
    (artifact_dir / "waiting.json").write_text(
        json.dumps({"waiting_for": [waiting_for]}),
        encoding="utf-8",
    )
    return artifact_dir


def _assert_scoped_matches_full(
    rows: list[_Row], marker: dict[str, Any], waiter_dir: Path
) -> None:
    keys = marker_scope_keys(marker)
    assert keys is not None
    scoped_rows = select_scope_rows(rows, keys, include_dirs=(waiter_dir,))
    full_index = _index(rows)
    scoped_index = _index(scoped_rows)

    def decide(index: WaitDependencyIndex, selected_rows: list[_Row]):
        return resolve_wait_release(
            index,
            marker,
            waiter_dir=waiter_dir,
            closed_bead_ids=frozenset(),
            now=1_800_000_000.0,
            fresh_index=lambda: _index(selected_rows),
        )

    full_decision = decide(full_index, rows)
    scoped_decision = decide(scoped_index, scoped_rows)
    assert (
        scoped_decision.status.resolved,
        scoped_decision.status.blocked_on,
        scoped_decision.releasable,
        scoped_decision.confirmation_failed,
    ) == (
        full_decision.status.resolved,
        full_decision.status.blocked_on,
        full_decision.releasable,
        full_decision.confirmation_failed,
    )

    waiting_for = marker.get("waiting_for", [])
    resolved_deps = marker.get("resolved_deps", [])
    assert scoped_index.dependency_member_dirs(
        waiting_for,
        resolved_deps=resolved_deps,
        self_artifact_dir=waiter_dir,
    ) == full_index.dependency_member_dirs(
        waiting_for,
        resolved_deps=resolved_deps,
        self_artifact_dir=waiter_dir,
    )

    assert terminal_blockers(
        scoped_index,
        waiting_for,
        marker.get("wait_for_artifacts", []),
        marker.get("wait_for_hoods", []),
        scoped_decision.status.blocked_on,
        self_artifact_dir=waiter_dir,
    ) == terminal_blockers(
        full_index,
        waiting_for,
        marker.get("wait_for_artifacts", []),
        marker.get("wait_for_hoods", []),
        full_decision.status.blocked_on,
        self_artifact_dir=waiter_dir,
    )


def test_artifact_scope_keys_follow_index_identity_and_planner_superset() -> None:
    meta = {
        "name": "lane--plan",
        "workflow_name": "lane",
        "agent_session": "lane",
        "role_suffix": "--plan",
        "agent_clan": "research",
    }
    assert artifact_scope_keys(meta) == frozenset({"lane--plan", "lane", "research"})

    # The old parallel-family spelling still contributes its clan identity.
    legacy = {
        "name": "legacy-worker",
        "agent_family": "legacy-clan",
        "agent_family_parallel": True,
    }
    assert "legacy-clan" in artifact_scope_keys(legacy)


def test_marker_scope_keys_classify_named_and_unscopable_shapes() -> None:
    assert marker_scope_keys({"waiting_for": ["lane", "planner.plan"]}) == {
        "lane",
        "planner.plan",
        "planner--plan",
    }
    assert marker_scope_keys({"wait_for_beads": ["sase-a1"]}) == frozenset()

    for marker in (
        {"wait_for_artifacts": [{"name": "lane"}]},
        {"wait_for_fork_sources": [{"name": "lane"}]},
        {"wait_for_hoods": ["team"]},
        {"wait_for_epics_of": ["lane"]},
        {"wait_epic_follows": [{"target": "lane"}]},
        {"waiting_for": ["@team"]},
        {"waiting_for": [None]},
    ):
        assert marker_scope_keys(marker) is None


def test_select_scope_rows_keeps_matching_rows_and_explicit_waiter(
    tmp_path: Path,
) -> None:
    matching = make_agent(tmp_path, "proj", "20261011010101", "lane")
    unrelated = make_agent(tmp_path, "proj", "20261011010102", "other")
    waiter = make_agent(tmp_path, "proj", "20261011010103", "consumer")
    rows = [_row(matching), _row(unrelated), _row(waiter)]

    selected = select_scope_rows(rows, {"lane"}, include_dirs=(waiter,))
    assert [row[0] for row in selected] == [matching, waiter]


def test_scoped_named_waits_match_full_view_across_dependency_shapes(
    tmp_path: Path,
) -> None:
    rows: list[_Row] = []
    cases: list[tuple[dict[str, Any], Path]] = []

    def add(artifact_dir: Path) -> None:
        rows.append(_row(artifact_dir))

    def waiter(suffix: str, name: str, **kwargs: Any) -> Path:
        artifact_dir = _make_waiter(tmp_path, suffix, name, **kwargs)
        add(artifact_dir)
        cases.append(({"waiting_for": [name]}, artifact_dir))
        return artifact_dir

    # Named retries and a plan-to-code session.
    add(
        make_agent(
            tmp_path,
            "proj",
            "20261011020101",
            "retry",
            workflow_name="retry",
            agent_session="retry",
            done=True,
            outcome="completed",
        )
    )
    add(
        make_agent(
            tmp_path,
            "proj",
            "20261011020102",
            "retry.1",
            workflow_name="retry",
            agent_session="retry",
            done=True,
            outcome="completed",
        )
    )
    waiter("20261011020103", "retry.1")
    add(
        make_agent(
            tmp_path,
            "proj",
            "20261011020201",
            "lane--plan",
            workflow_name="lane",
            agent_session="lane",
            role_suffix="--plan",
            done=True,
            outcome="completed",
        )
    )
    add(
        make_agent(
            tmp_path,
            "proj",
            "20261011020202",
            "lane--code",
            workflow_name="lane",
            agent_session="lane",
            role_suffix="--code",
            parent_timestamp="20261011020201",
            done=True,
            outcome="completed",
        )
    )
    waiter("20261011020203", "lane")

    # Clan generations and a multi-step workflow.
    for timestamp, name, generation, outcome in (
        ("20261011020301", "research.1", "generation-a", "completed"),
        ("20261011020302", "research.2", "generation-a", "completed"),
        ("20261011020303", "research.3", "generation-b", None),
    ):
        member = make_agent(
            tmp_path,
            "proj",
            timestamp,
            name,
            done=outcome is not None,
            outcome=outcome,
            extra_meta={
                "agent_clan": "research",
                "agent_clan_generation": generation,
            },
        )
        if outcome is None:
            (member / "waiting.json").write_text(
                json.dumps({"waiting_for": ["upstream"]}),
                encoding="utf-8",
            )
        add(member)
    waiter("20261011020304", "research")

    for timestamp, name in (
        ("20261011020401", "pipeline.setup"),
        ("20261011020402", "pipeline.run"),
    ):
        add(
            make_agent(
                tmp_path,
                "proj",
                timestamp,
                name,
                workflow_name="pipeline",
                agent_session="pipeline",
                done=True,
                outcome="completed",
            )
        )
    waiter("20261011020403", "pipeline")

    # Submitted planner row: both canonical and legacy wait spellings resolve.
    planner = make_submitted_planner(tmp_path, "20261011020501", "planner")
    add(planner)
    waiter("20261011020502", "planner--plan")
    waiter("20261011020503", "planner.plan")

    # A queued dependency remains selected and unresolved.
    queued = make_agent(tmp_path, "proj", "20261011020601", "queued-worker")
    (queued / "waiting.json").write_text(
        json.dumps({"waiting_for": ["upstream"]}),
        encoding="utf-8",
    )
    add(queued)
    waiter("20261011020602", "queued-worker")

    # A newer failure and an unknown terminal outcome remain visible to both
    # resolution and terminal-blocker queries.
    add(
        make_agent(
            tmp_path,
            "proj",
            "20261011020701",
            "newer-failure",
            done=True,
            outcome="completed",
        )
    )
    add(
        make_agent(
            tmp_path,
            "proj",
            "20261011020702",
            "newer-failure",
            done=True,
            outcome="failed",
        )
    )
    waiter("20261011020703", "newer-failure")
    add(
        make_agent(
            tmp_path,
            "proj",
            "20261011020801",
            "future-outcome",
            done=True,
            outcome="future_terminal_state",
        )
    )
    waiter("20261011020802", "future-outcome")

    # Same name across projects and a waiter sharing its dependency's session.
    add(
        make_agent(
            tmp_path,
            "other-project",
            "20261011020901",
            "cross-project",
            done=True,
            outcome="completed",
        )
    )
    waiter("20261011020902", "cross-project")
    add(
        make_agent(
            tmp_path,
            "proj",
            "20261011021001",
            "shared--plan",
            workflow_name="shared",
            agent_session="shared",
            role_suffix="--plan",
            done=True,
            outcome="completed",
        )
    )
    waiter(
        "20261011021002",
        "shared",
        workflow_name="shared",
        agent_session="shared",
    )

    for marker, waiter_dir in cases:
        _assert_scoped_matches_full(rows, marker, waiter_dir)


def test_planner_alias_membership_does_not_depend_on_timestamp_collisions(
    tmp_path: Path,
) -> None:
    planner = make_submitted_planner(tmp_path, "20261011030101", "planner")
    collision = make_agent(
        tmp_path,
        "other-project",
        "20261011030101",
        "unrelated",
    )
    waiter = _make_waiter(tmp_path, "20261011030102", "planner.plan")
    rows = [_row(planner), _row(collision), _row(waiter)]

    selected = select_scope_rows(
        rows,
        marker_scope_keys({"waiting_for": ["planner.plan"]}) or (),
        include_dirs=(waiter,),
    )
    full = _index(rows)
    scoped = _index(selected)
    assert full.dependency_member_dirs(
        ["planner.plan"], self_artifact_dir=waiter
    ) == scoped.dependency_member_dirs(["planner.plan"], self_artifact_dir=waiter)
    assert str(planner) in full.dependency_member_dirs(
        ["planner.plan"], self_artifact_dir=waiter
    )
    assert str(collision) not in full.dependency_member_dirs(
        ["planner.plan"], self_artifact_dir=waiter
    )


@pytest.mark.parametrize(
    "marker",
    [
        {"wait_for_artifacts": [{"name": "lane"}]},
        {"wait_for_fork_sources": [{"name": "lane"}]},
        {"wait_for_hoods": ["team"]},
        {"wait_for_epics_of": ["lane"]},
        {"wait_epic_follows": [{"target": "lane"}]},
        {"waiting_for": ["@team"]},
    ],
)
def test_unscopable_markers_request_full_view(marker: dict[str, Any]) -> None:
    assert marker_scope_keys(marker) is None
