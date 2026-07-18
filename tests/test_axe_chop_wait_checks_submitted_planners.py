"""Submitted-planner wait_checks chop script tests."""

import json
from pathlib import Path

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)

from tests._axe_chop_wait_checks_helpers import (
    make_submitted_planner,
    make_waiting_agent,
    run_wait_checks,
    write_workflow_state,
)


def test_submitted_planner_resolves_plan_row_wait(tmp_path: Path, monkeypatch) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "planner--plan")
    planner_dir = make_submitted_planner(tmp_path, "20260625184716", "planner")
    # A real submitted planner finalizes its handoff workflow_state as completed
    # before blocking in review (still no done.json anywhere).
    write_workflow_state(planner_dir)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )
    assert dependency_resolution_status(index, ["planner--plan"]).resolved
    # The whole plan chain is still in review, so the family/root wait stays
    # parked even though the planner row resolves.
    assert not dependency_resolution_status(index, ["planner"]).resolved

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planner--plan"]}


def test_renamed_plan_root_does_not_shadow_submitted_planner_alias(
    tmp_path: Path,
) -> None:
    planner_dir = make_submitted_planner(
        tmp_path,
        "20260718010101",
        "planner",
        agent_name="planner--plan",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )
    assert dependency_resolution_status(index, ["planner--plan"]).resolved
    assert not dependency_resolution_status(index, ["planner"]).resolved

    (planner_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    approved_index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )
    assert dependency_resolution_status(
        approved_index,
        ["planner--plan"],
    ).resolved


def test_submitted_planner_legacy_dot_plan_alias_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "planner.plan")
    make_submitted_planner(tmp_path, "20260625184716", "planner")

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planner.plan"]}


def test_submitted_planner_does_not_resolve_family_wait(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "planner")
    make_submitted_planner(tmp_path, "20260625184716", "planner")

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_submitted_planner_minimal_meta_resolves_plan_row_wait(
    tmp_path: Path, monkeypatch
) -> None:
    # A freshly submitted plan (no replan/promotion yet) carries only its base
    # name, role suffix, submission marker, and plan path.
    waiter_dir = make_waiting_agent(tmp_path, "planner--plan")
    make_submitted_planner(tmp_path, "20260625184716", "planner", promoted=False)

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planner--plan"]}


def test_submitted_planner_without_plan_path_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "planner--plan")
    make_submitted_planner(tmp_path, "20260625184716", "planner", plan_path=None)

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
