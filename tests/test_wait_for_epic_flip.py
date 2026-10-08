"""Flip-phase regressions: ``for_epic`` defaults to true (sase-1h7.10).

Gates the default flip: user-authored agent waits follow launched epics
unless explicitly opted out, while generated intra-epic sequencing waits
(``%w(<agents>, for_epic=false)``) and pre-feature markers release exactly
as before.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    resolve_wait_release,
)
from sase.macro.directives import extract_prompt_directives
from tests._agent_names_fixtures import make_agent

NOW = 1_800_000_000.0


def _index(*artifact_dirs: Path) -> WaitDependencyIndex:
    index = WaitDependencyIndex.empty()
    index.add_many(
        (
            artifact_dir,
            json.loads((artifact_dir / "agent_meta.json").read_text(encoding="utf-8")),
            "proj",
        )
        for artifact_dir in artifact_dirs
    )
    return index


def _agent(
    tmp_path: Path,
    suffix: str,
    name: str,
    *,
    done: bool = True,
    outcome: str | None = "completed",
    extra_meta: dict[str, object] | None = None,
    agent_session: str | None = None,
) -> Path:
    return make_agent(
        tmp_path,
        "proj",
        suffix,
        name,
        agent_session=agent_session or name,
        done=done,
        outcome=outcome,
        extra_meta=extra_meta,
    )


def _waiter_dir(
    tmp_path: Path,
    suffix: str = "waiter",
    *,
    extra_meta: dict[str, object] | None = None,
) -> Path:
    artifact_dir = (
        tmp_path / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {"name": "waiter", "model": "test"}
    if extra_meta:
        meta.update(extra_meta)
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return artifact_dir


def _decide(
    index: WaitDependencyIndex,
    marker: dict[str, Any],
    waiter_dir: Path,
    *,
    closed: frozenset[str] | None = None,
    now: float = NOW,
) -> Any:
    return resolve_wait_release(
        index,
        marker,
        waiter_dir=waiter_dir,
        closed_bead_ids=closed,
        now=now,
        dismissed_artifact_dir=None,
        fresh_index=lambda: index,
    )


def test_default_arms_colon_and_parenthesized_agent_waits() -> None:
    _, directives = extract_prompt_directives("%wait:planner")
    assert directives.wait_for_epics_of == ["planner"]
    _, directives = extract_prompt_directives("%w:planner")
    assert directives.wait_for_epics_of == ["planner"]
    _, directives = extract_prompt_directives("%wait(planner)")
    assert directives.wait_for_epics_of == ["planner"]


def test_repeat_chain_wait_follows_previous_epic() -> None:
    # `%repeat:k` waits on run k-1 via an injected `%wait:<prev_name>`.
    _, directives = extract_prompt_directives("%wait:linter.1")
    assert directives.wait_for_epics_of == ["linter.1"]


def test_generated_intra_epic_wait_never_arms() -> None:
    # Phase and land segments pair the agent wait with a phase-bead wait and
    # opt the agent leg out explicitly.
    _, directives = extract_prompt_directives("%w(e1.p1, for_epic=false)\n%w(bead=p1)")
    assert directives.wait == ["e1.p1"]
    assert directives.wait_for_epics_of == []


def test_land_agent_releases_on_phase_beads_under_default(tmp_path: Path) -> None:
    phase = _agent(tmp_path, "20261001090000", "e1.p1")
    waiter = _waiter_dir(tmp_path)
    index = _index(phase)
    # Marker as the runner writes it for a generated land segment: the agent
    # leg opted out, the phase-bead leg authoritative.
    marker: dict[str, Any] = {
        "waiting_for": ["e1.p1"],
        "wait_for_epics_of": [],
        "wait_for_beads": ["p1"],
    }
    parked = _decide(index, marker, waiter)
    assert parked.releasable is False
    released = _decide(index, marker, waiter, closed=frozenset({"p1"}))
    assert released.releasable is True
    assert released.patch is None


def test_delegated_phase_worker_follow_parks_until_child_epic_closes(
    tmp_path: Path,
) -> None:
    worker = _agent(
        tmp_path,
        "20261001090000",
        "phase-1",
        extra_meta={
            "epic_bead_id": "sase-7k",
            "phase_bead_id": "sase-7k.1",
            "created_epics": [{"bead_id": "sase-7m"}],
        },
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(worker)
    # A user-authored default wait on the worker follows the child epic it
    # launched; the inherited epic never counts, so there is no deadlock.
    marker: dict[str, Any] = {
        "waiting_for": ["phase-1"],
        "wait_for_epics_of": ["phase-1"],
    }
    first = _decide(index, marker, waiter)
    assert [f.state for f in first.follows] == ["following"]
    assert first.patch is not None
    assert list(first.patch.wait_for_beads) == ["sase-7m"]
    assert first.releasable is False

    promoted: dict[str, Any] = {
        "waiting_for": ["phase-1"],
        "wait_for_epics_of": ["phase-1"],
        "wait_for_beads": list(first.patch.wait_for_beads),
        "resolved_deps": list(first.patch.resolved_deps),
        "wait_epic_follows": [dict(entry) for entry in first.patch.wait_epic_follows],
    }
    second = _decide(index, promoted, waiter, closed=frozenset({"sase-7m"}))
    assert second.follows == ()
    assert second.patch is None
    assert second.releasable is True


def test_old_marker_without_armed_field_never_follows(tmp_path: Path) -> None:
    planner = _agent(
        tmp_path,
        "20261001090000",
        "planner",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    decision = _decide(index, {"waiting_for": ["planner"]}, waiter)
    assert decision.follows == ()
    assert decision.patch is None
    assert decision.releasable is True


def test_waiter_launched_after_epic_closed_releases_next_pass(
    tmp_path: Path,
) -> None:
    planner = _agent(
        tmp_path,
        "20261001090000",
        "planner",
        extra_meta={"created_epics": [{"bead_id": "sase-7k"}]},
    )
    waiter = _waiter_dir(tmp_path)
    index = _index(planner)
    marker: dict[str, Any] = {
        "waiting_for": ["planner"],
        "wait_for_epics_of": ["planner"],
    }
    first = _decide(index, marker, waiter, closed=frozenset({"sase-7k"}))
    assert [f.state for f in first.follows] == ["following"]
    assert first.patch is not None
    assert first.releasable is False

    promoted: dict[str, Any] = {
        "waiting_for": ["planner"],
        "wait_for_epics_of": ["planner"],
        "wait_for_beads": list(first.patch.wait_for_beads),
        "resolved_deps": list(first.patch.resolved_deps),
        "wait_epic_follows": [dict(entry) for entry in first.patch.wait_epic_follows],
    }
    second = _decide(index, promoted, waiter, closed=frozenset({"sase-7k"}))
    assert second.follows == ()
    assert second.patch is None
    assert second.releasable is True
