"""Cache and scan-budget tests for the per-agent skill-uses loader."""

from __future__ import annotations

import gc
import os
from pathlib import Path

import pytest

from sase.ace.tui import skill_uses as skill_uses_module
from sase.ace.tui.skill_uses import (
    _load_skill_uses_for_agent,
    load_skill_uses_for_agent_context,
)
from sase.skills import use_log as use_log_module
from sase.skills.use_log import SkillUseEvent, skill_use_log_path

from ._skill_uses_loader_helpers import (
    clear_skill_uses_cache_fixture,
    fake_project_fixture,
    make_agent,
    make_event,
    write_jsonl,
)


def test_cache_invalidates_on_mtime_change(fake_project: Path, tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    log_path = skill_use_log_path("skill-uses-test")
    initial = [
        make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    write_jsonl(log_path, initial)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    first = _load_skill_uses_for_agent(agent)
    assert len(first) == 1

    later = list(initial) + [
        make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
        )
    ]
    write_jsonl(log_path, later)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))

    for entry in skill_uses_module._skill_uses_cache.values():
        entry.last_read_monotonic = 0.0

    second = _load_skill_uses_for_agent(agent)
    assert [event.skill_name for event in second] == [
        "sase_questions",
        "sase_plan",
    ]


def test_targeted_scan_runs_once_per_agent_and_revalidates(
    fake_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_a = tmp_path / "artifacts" / "agent_a"
    artifacts_b = tmp_path / "artifacts" / "agent_b"
    artifacts_a.mkdir(parents=True)
    artifacts_b.mkdir(parents=True)
    log_path = skill_use_log_path("skill-uses-test")

    events = [
        make_event(
            skill_name="sase_plan",
            timestamp="2026-06-14T10:00:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            use_id="alpha-use",
        ),
        make_event(
            skill_name="sase_questions",
            timestamp="2026-06-14T10:01:00+00:00",
            agent_name="beta",
            artifacts_dir=str(artifacts_b),
            use_id="beta-use",
        ),
    ]
    write_jsonl(log_path, events)
    scan_count = 0
    real_query = use_log_module.query_skill_use_events

    def counting_query(log_path: Path, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal scan_count
        scan_count += 1
        return real_query(log_path, **kwargs)

    monkeypatch.setattr(
        skill_uses_module,
        "query_skill_use_events",
        counting_query,
    )

    agent_a = make_agent(
        artifacts_dir=artifacts_a,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    agent_b = make_agent(
        artifacts_dir=artifacts_b,
        agent_name="beta",
        workspace_dir=fake_project,
        raw_suffix="20260614-100001",
    )

    assert [
        item.event.skill_name for item in load_skill_uses_for_agent_context(agent_a)
    ] == ["sase_plan"]
    assert [
        item.event.skill_name for item in load_skill_uses_for_agent_context(agent_b)
    ] == ["sase_questions"]
    assert scan_count == 2

    events.append(
        make_event(
            skill_name="sase_memory_read",
            timestamp="2026-06-14T10:10:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_a),
            use_id="alpha-new-use",
        )
    )
    write_jsonl(log_path, events)
    future_mtime_ns = log_path.stat().st_mtime_ns + 10_000_000_000
    os.utime(log_path, ns=(future_mtime_ns, future_mtime_ns))
    for cache in (
        skill_uses_module._skill_uses_cache,
        skill_uses_module._skill_uses_context_cache,
    ):
        for entry in cache.values():
            entry.last_read_monotonic = 0.0

    assert [
        item.event.skill_name for item in load_skill_uses_for_agent_context(agent_a)
    ] == ["sase_memory_read", "sase_plan"]
    assert [
        item.event.skill_name for item in load_skill_uses_for_agent_context(agent_b)
    ] == ["sase_questions"]
    assert scan_count == 4


def test_unrelated_events_are_never_materialized(
    fake_project: Path, tmp_path: Path
) -> None:
    """Retention test for sase-1tw: the whole-project log stays on disk."""

    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            skill_name=f"other_{index}",
            timestamp=f"2026-06-14T10:{index // 60:02d}:{index % 60:02d}+00:00",
            agent_name="someone-else",
            artifacts_dir=str(tmp_path / "artifacts" / "other"),
            use_id=f"other-{index}",
        )
        for index in range(300)
    ]
    events.extend(
        make_event(
            skill_name=f"mine_{index}",
            timestamp=f"2026-06-14T11:{index:02d}:00+00:00",
            agent_name="alpha",
            artifacts_dir=str(artifacts_dir),
            use_id=f"mine-{index}",
        )
        for index in range(5)
    )
    write_jsonl(skill_use_log_path("skill-uses-test"), events)
    del events
    gc.collect()

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    result = _load_skill_uses_for_agent(agent)

    assert [event.skill_name for event in result] == [
        f"mine_{i}" for i in (4, 3, 2, 1, 0)
    ]
    gc.collect()
    live = [
        obj
        for obj in gc.get_objects()
        if isinstance(obj, SkillUseEvent) and obj.project == "skill-uses-test"
    ]
    # Only the agent's own events survive: the 300 unrelated rows are parsed
    # transiently at most and never retained.
    assert len(live) == 5


def test_scan_budget_bounds_sparse_agent_parse(
    fake_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir = tmp_path / "artifacts" / "agent_a"
    artifacts_dir.mkdir(parents=True)

    events = [
        make_event(
            skill_name=f"other_{index}",
            timestamp=f"2026-06-14T10:{index // 60:02d}:{index % 60:02d}+00:00",
            agent_name="someone-else",
            artifacts_dir=str(tmp_path / "artifacts" / "other"),
            use_id=f"other-{index}",
        )
        for index in range(100)
    ]
    write_jsonl(skill_use_log_path("skill-uses-test"), events)

    parse_count = 0
    real_from_mapping = use_log_module._event_from_mapping

    def counting_from_mapping(data):  # type: ignore[no-untyped-def]
        nonlocal parse_count
        parse_count += 1
        return real_from_mapping(data)

    monkeypatch.setattr(use_log_module, "_event_from_mapping", counting_from_mapping)

    agent = make_agent(
        artifacts_dir=artifacts_dir,
        agent_name="alpha",
        workspace_dir=fake_project,
    )
    assert _load_skill_uses_for_agent(agent) == ()
    # The sparse agent's miss scans the whole small log once, not once per
    # cache entry, and never parses more lines than the log holds.
    assert parse_count == 100

    # The whole-file snapshot cache is gone: only bounded per-agent tables.
    assert not hasattr(skill_uses_module, "_skill_uses_snapshot_cache")
