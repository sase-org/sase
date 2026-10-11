"""Parity between batched and sequential wait-dependency index builds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.core.wait_dependency_resolution import WaitDependencyIndex


def _write_artifact(
    root: Path,
    timestamp: str,
    meta: dict[str, Any],
    *,
    done: dict[str, Any] | None = None,
    waiting: dict[str, Any] | None = None,
    plan_path_json: dict[str, Any] | None = None,
) -> Path:
    artifact_dir = root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if done is not None:
        (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")
    if waiting is not None:
        (artifact_dir / "waiting.json").write_text(
            json.dumps(waiting), encoding="utf-8"
        )
    if plan_path_json is not None:
        (artifact_dir / "plan_path.json").write_text(
            json.dumps(plan_path_json), encoding="utf-8"
        )
    return artifact_dir


def _planner_meta(
    name: str,
    *,
    plan_path: str | None = "sdd/plans/202610/example.md",
    approved: bool = False,
    feedback: bool = False,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "name": name,
        "workflow_name": name,
        "agent_session": name,
        "role_suffix": "--plan",
        "plan_submitted_at": ["2026-10-11T00:00:00+00:00"],
    }
    if plan_path is not None:
        meta["plan_path"] = plan_path
    if approved:
        meta["plan_approved"] = True
    if feedback:
        meta["feedback_submitted_at"] = ["2026-10-11T01:00:00+00:00"]
    return meta


def _build_corpus(root: Path) -> list[tuple[str, dict[str, Any]]]:
    """Create artifact dirs covering the batch-index-build corpus.

    Returns ``(timestamp, meta)`` pairs in a fixed order; callers read the
    meta back from disk so batch and sequential builds see identical inputs.
    """
    specs: list[
        tuple[
            str,
            dict[str, Any],
            dict[str, Any] | None,
            dict[str, Any] | None,
            dict[str, Any] | None,
        ]
    ] = []
    # Regular workflow members.
    specs.append(
        (
            "20260718000001",
            {"name": "worker-a", "workflow_name": "flow", "agent_session": "flow"},
            {"outcome": "completed"},
            None,
            None,
        )
    )
    specs.append(
        (
            "20260718000002",
            {"name": "worker-b", "workflow_name": "flow", "agent_session": "flow"},
            {"outcome": "failed"},
            None,
            None,
        )
    )
    # Duplicate name: newest timestamp wins in ``named``.
    specs.append(
        (
            "20260718000003",
            {"name": "dup"},
            {"outcome": "completed"},
            None,
            None,
        )
    )
    specs.append(
        (
            "20260718000004",
            {"name": "dup"},
            {"outcome": "failed"},
            None,
            None,
        )
    )
    # Multi-member clan, generation 1 (recorded tribe comes from the mock).
    gen1 = "20260718020000"
    specs.append(
        (
            "20260718020100",
            {
                "name": "review.one",
                "agent_clan": "review",
                "agent_clan_generation": gen1,
                "clan_tribe": "epic",
            },
            {"outcome": "completed"},
            None,
            None,
        )
    )
    specs.append(
        (
            "20260718020101",
            {
                "name": "review.two",
                "agent_clan": "review",
                "agent_clan_generation": gen1,
            },
            {"outcome": "completed"},
            None,
            None,
        )
    )
    # Same clan, generation 2 (no recorded tribe: member resolution applies).
    specs.append(
        (
            "20260718030100",
            {
                "name": "review.three",
                "agent_clan": "review",
                "agent_clan_generation": "20260718030000",
                "clan_tribe": "epic",
            },
            {"outcome": "completed"},
            None,
            None,
        )
    )
    # Solo clan without any clan record.
    specs.append(
        (
            "20260718040100",
            {
                "name": "solo.one",
                "agent_clan": "solo",
                "agent_clan_generation": "20260718040100",
                "clan_tribe": "epic",
            },
            {"outcome": "completed"},
            None,
            None,
        )
    )
    # Legacy agent-family clan fallback.
    specs.append(
        (
            "20260718040200",
            {
                "name": "fam.worker",
                "agent_family": "fam",
                "agent_family_parallel": True,
            },
            {"outcome": "completed"},
            None,
            None,
        )
    )
    # Posthoc tribe member (agent_tribes entry supplied by the test).
    specs.append(
        (
            "20260718010000",
            {"name": "posthoc-worker", "cl_name": "cl-posthoc"},
            {"outcome": "completed"},
            None,
            None,
        )
    )
    # Direct tribe member.
    specs.append(
        (
            "20260718010001",
            {"name": "tribe-worker", "tribe": "epic"},
            {"outcome": "completed"},
            None,
            None,
        )
    )
    # Submitted planner with plan_path.json marker.
    specs.append(
        (
            "20260718050000",
            _planner_meta("planner-a"),
            None,
            None,
            {"plan_path": "sdd/plans/202610/example.md"},
        )
    )
    # Submitted planner with meta-only plan_path (no marker file).
    specs.append(
        (
            "20260718050001",
            _planner_meta("planner-b"),
            None,
            None,
            None,
        )
    )
    # Submitted planner shape but no plan path anywhere: not a planner row.
    specs.append(
        (
            "20260718050002",
            _planner_meta("planner-c", plan_path=None),
            None,
            None,
            None,
        )
    )
    # Approved planner: preconditions fail, marker must be ignored.
    specs.append(
        (
            "20260718050003",
            _planner_meta("planner-d", approved=True),
            None,
            None,
            {"plan_path": "sdd/plans/202610/example.md"},
        )
    )
    # Feedback planner: preconditions fail.
    specs.append(
        (
            "20260718050004",
            _planner_meta("planner-e", feedback=True),
            None,
            None,
            {"plan_path": "sdd/plans/202610/example.md"},
        )
    )
    # Non-plan row carrying a stray plan_path.json: must be ignored.
    specs.append(
        (
            "20260718050005",
            {"name": "regular"},
            None,
            None,
            {"plan_path": "sdd/plans/202610/example.md"},
        )
    )
    # Queued row that already crossed its barrier (slot queue marker).
    specs.append(
        (
            "20260718060000",
            {"name": "queued-crossed", "wait_completed_at": "2026-10-11T00:00:00Z"},
            None,
            {"waiting_for": ["worker-a"], "slot_requested_at": "2026-10-11T00:00:00Z"},
            None,
        )
    )
    # Dependency-parked row: queued and still behind its barrier.
    specs.append(
        (
            "20260718060001",
            {"name": "queued-parked"},
            None,
            {"waiting_for": ["worker-a"]},
            None,
        )
    )
    # Unfinished row with no waiting marker and no done.json.
    specs.append(
        (
            "20260718060002",
            {"name": "unfinished"},
            None,
            None,
            None,
        )
    )

    created: list[tuple[str, dict[str, Any]]] = []
    for timestamp, meta, done, waiting, plan_json in specs:
        artifact_dir = _write_artifact(
            root,
            timestamp,
            meta,
            done=done,
            waiting=waiting,
            plan_path_json=plan_json,
        )
        stored = json.loads((artifact_dir / "agent_meta.json").read_text())
        created.append((timestamp, stored))
    return created


def _assert_indexes_equal(
    batch: WaitDependencyIndex, sequential: WaitDependencyIndex
) -> None:
    assert batch.named == sequential.named
    assert batch.workflows == sequential.workflows
    assert batch.agent_sessions == sequential.agent_sessions
    assert batch.clans == sequential.clans
    assert batch.tribes == sequential.tribes
    assert batch.effective_clan_tribes == sequential.effective_clan_tribes
    assert batch.artifacts == sequential.artifacts
    assert batch.artifacts_by_dir == sequential.artifacts_by_dir


def test_add_many_matches_sequential_add(tmp_path: Path, monkeypatch) -> None:
    from sase.core import agent_clan_record

    root = tmp_path / "artifacts"
    root.mkdir()
    corpus = _build_corpus(root)

    gen1 = "20260718020000"

    def _fake_load_clan_record(clan_name: str, **kwargs: Any) -> Any:
        if clan_name == "review":
            return {
                "generations": {
                    gen1: {"tribe": {"value": "epic", "source": "edited"}},
                }
            }
        return None

    monkeypatch.setattr(agent_clan_record, "load_clan_record", _fake_load_clan_record)

    posthoc_tribes = {
        ("workflow", "cl-posthoc", "20260718010000"): "epic",
    }

    rows = [(root / timestamp, meta, "proj") for timestamp, meta in corpus]

    batch = WaitDependencyIndex.empty()
    batch.agent_tribes.update(posthoc_tribes)
    batch.add_many(rows)

    sequential = WaitDependencyIndex.empty()
    sequential.agent_tribes.update(posthoc_tribes)
    for artifact_dir, meta, project_name in rows:
        sequential.add(artifact_dir, dict(meta), project_name=project_name)

    _assert_indexes_equal(batch, sequential)

    # The corpus must actually exercise the optimized paths.
    assert ("review", gen1) in batch.effective_clan_tribes
    assert batch.effective_clan_tribes[("review", gen1)] == "epic"
    assert ("review", "20260718030000") in batch.effective_clan_tribes
    assert any(
        candidate.name == "posthoc-worker"
        for members in batch.tribes.values()
        for candidate in members
    )
    # Submitted planners resolve under their canonical row names.
    assert "planner-a--plan" in batch.named
    assert "planner-b--plan" in batch.named
    assert "planner-c--plan" not in batch.named
    assert "planner-d--plan" not in batch.named
    # Queued / parked flags survive batching.
    assert batch.artifacts_by_dir[str(root / "20260718060000")].is_queued
    assert not batch.artifacts_by_dir[str(root / "20260718060000")].is_dependency_parked
    assert batch.artifacts_by_dir[str(root / "20260718060001")].is_dependency_parked


def test_add_many_matches_sequential_add_with_archived_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    from tests._agent_names_fixtures import make_agent
    from tests._dismissed_completion_helpers import (
        add_archive_identity,
        rebuild_completion_archive,
        write_dismissed_completion,
    )

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    archived_dir = make_agent(tmp_path, "proj", "20260720120100", "archived-worker")
    add_archive_identity(archived_dir)
    write_dismissed_completion(tmp_path, archived_dir, "archived-worker", status="DONE")
    rebuild_completion_archive()

    live_dir = make_agent(
        tmp_path,
        "proj",
        "20260720120200",
        "live-worker",
        done=True,
        outcome="completed",
    )

    projects_root = tmp_path / ".sase" / "projects"
    live_meta = json.loads((live_dir / "agent_meta.json").read_text())
    archived_meta = json.loads((archived_dir / "agent_meta.json").read_text())
    rows = [
        (live_dir, live_meta, "proj"),
        (archived_dir, archived_meta, "proj"),
    ]
    _ = projects_root

    batch = WaitDependencyIndex.empty()
    batch.add_many([(path, dict(meta), proj) for path, meta, proj in rows])

    sequential = WaitDependencyIndex.empty()
    for path, meta, proj in rows:
        sequential.add(path, dict(meta), project_name=proj)

    _assert_indexes_equal(batch, sequential)
    archived_candidate = batch.artifacts_by_dir[str(archived_dir)]
    assert archived_candidate.archived_completion is not None
    assert archived_candidate.is_resolved


def test_add_many_skips_plan_path_reads_without_preconditions(
    tmp_path: Path, monkeypatch
) -> None:
    import sase.core.wait_dependency_resolution._index as index_module

    root = tmp_path / "artifacts"
    root.mkdir()
    corpus = _build_corpus(root)

    real_marker = index_module.plan_path_marker
    calls: list[str] = []

    def _counting_marker(artifact_dir: Path) -> str | None:
        calls.append(str(artifact_dir))
        return real_marker(artifact_dir)

    monkeypatch.setattr(index_module, "plan_path_marker", _counting_marker)

    index = WaitDependencyIndex.empty()
    index.add_many([(root / timestamp, meta, "proj") for timestamp, meta in corpus])

    # Only rows whose meta-only preconditions hold need a marker read:
    # planner-a (marker file), planner-b (meta-only path), and planner-c
    # (no path anywhere, still needs the marker to prove absence). Every
    # other row, including the approved/feedback planners and the stray
    # marker on a regular row, skips it.
    assert sorted(calls) == sorted(
        [
            str(root / "20260718050000"),
            str(root / "20260718050001"),
            str(root / "20260718050002"),
        ]
    )


def test_add_many_refreshes_each_touched_generation_once(
    tmp_path: Path, monkeypatch
) -> None:
    import sase.core.wait_dependency_resolution._index as index_module

    root = tmp_path / "artifacts"
    root.mkdir()
    corpus = _build_corpus(root)
    rows = [(root / timestamp, meta, "proj") for timestamp, meta in corpus]

    real_refresh = index_module.WaitDependencyIndex._refresh_effective_clan_tribe
    refresh_calls: list[tuple[str, str]] = []

    def _counting_refresh(
        self: WaitDependencyIndex, clan_name: str, generation: str
    ) -> None:
        refresh_calls.append((clan_name, generation))
        real_refresh(self, clan_name, generation)

    monkeypatch.setattr(
        index_module.WaitDependencyIndex,
        "_refresh_effective_clan_tribe",
        _counting_refresh,
    )

    index = WaitDependencyIndex.empty()
    index.add_many(rows)

    touched = {
        ("review", "20260718020000"),
        ("review", "20260718030000"),
        ("solo", "20260718040100"),
        ("fam", "20260718040200"),
    }
    assert set(refresh_calls) == touched
    assert len(refresh_calls) == len(touched)
