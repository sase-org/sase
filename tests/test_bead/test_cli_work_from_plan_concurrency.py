"""Concurrency coverage for plan-file ``sase bead work`` launches."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from sase.bead.cli_work_from_plan import work_from_plan_file
from sase.bead.project import BeadProject
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore


EPIC_PLAN = """---
tier: epic
title: Plan-file rollout
goal: Exercise serialized plan-file launch.
phases:
  - id: core
    title: Build the core
    depends_on: []
    size: small
  - id: cli
    title: Add the CLI
    depends_on: [core]
    size: medium
  - id: verify
    title: Verify the result
    depends_on: [core, cli]
    size: large
---
# Plan

Execute the rollout.
"""


def test_concurrent_plan_file_launches_serialize_through_terminal_push(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.bead.cli_work_from_plan as plan_module

    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )
    first_source = project_dir / "first.md"
    second_source = project_dir / "second.md"
    first_source.write_text(
        EPIC_PLAN.replace("Plan-file rollout", "First rollout"),
        encoding="utf-8",
    )
    second_source.write_text(
        EPIC_PLAN.replace("Plan-file rollout", "Second rollout"),
        encoding="utf-8",
    )

    original_resolve = plan_module._resolve_context
    ready_to_launch = threading.Barrier(2)

    def resolve_together(*, dry_run: bool) -> tuple[object, SddStore, Path]:
        resolved = original_resolve(dry_run=dry_run)
        ready_to_launch.wait(timeout=2.0)
        return resolved

    monkeypatch.setattr(plan_module, "_resolve_context", resolve_together)
    monkeypatch.setattr(
        plan_module,
        "_commit_plan_file",
        lambda *_args, **_kwargs: True,
    )

    events: list[tuple[str, str]] = []
    events_lock = threading.Lock()
    first_push_started = threading.Event()
    release_first_push = threading.Event()
    push_count = 0

    def launch(_project: BeadProject, epic_id: str, **_kwargs: object) -> bool:
        with events_lock:
            events.append(("launch", epic_id))
        return True

    def terminal_push(_store: SddStore, *, no_push: bool) -> None:
        nonlocal push_count
        assert no_push is False
        with events_lock:
            push_count += 1
            current_push = push_count
            events.append(("push-start", str(current_push)))
        if current_push == 1:
            first_push_started.set()
            assert release_first_push.wait(timeout=2.0)
        with events_lock:
            events.append(("push-end", str(current_push)))

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        launch,
    )
    monkeypatch.setattr(plan_module, "_push_store_after_launch", terminal_push)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                work_from_plan_file,
                str(source),
                dry_run=False,
                yes=True,
                no_push=False,
                render=False,
            )
            for source in (first_source, second_source)
        ]
        assert first_push_started.wait(timeout=2.0)
        with events_lock:
            assert sum(kind == "launch" for kind, _value in events) == 1
        release_first_push.set()
        results = [future.result(timeout=5.0) for future in futures]

    epic_ids = {result.epic_id for result in results}
    assert None not in epic_ids
    assert len(epic_ids) == 2
    with events_lock:
        first_push_end = events.index(("push-end", "1"))
        second_launch = [
            index for index, (kind, _value) in enumerate(events) if kind == "launch"
        ][1]
    assert first_push_end < second_launch

    with BeadProject(project_dir) as project:
        for result in results:
            assert result.epic_id is not None
            phases = project.get_epic_children(result.epic_id)
            assert tuple(phase.id for phase in phases) == result.phase_bead_ids
            assert [len(phase.dependencies) for phase in phases] == [0, 1, 2]
            frontmatter, _body, _had_frontmatter = parse_frontmatter(
                result.archived_plan_path.read_text(encoding="utf-8")
            )
            assert frontmatter["bead_id"] == result.epic_id
