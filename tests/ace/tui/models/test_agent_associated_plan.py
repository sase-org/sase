"""Associated-plan summary and cache tests for Agents-tab enrichment."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from sase.ace.tui.models.agent_associated_plan import resolve_agent_associated_plan
from sase.agent.bead_display import BeadIssueLookupSession
from sase.bead.model import Issue, IssueType
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def _write_plan(path: Path, goal: str, *, tier: str = "tale") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntier: {tier}\ngoal: {goal!r}\n---\n# Plan\n",
        encoding="utf-8",
    )
    return path


def test_pending_tale_maps_to_plan_and_uses_home_shortened_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    plan = _write_plan(
        home / ".sase" / "plans" / "202607" / "pending.md",
        "Deliver the pending plan",
    )
    monkeypatch.setattr(Path, "home", lambda: home)
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.goal == "Deliver the pending plan"
    assert summary.authored_tier == "tale"
    assert summary.effective_tier == "plan"
    assert summary.display_path == "~/.sase/plans/202607/pending.md"
    assert summary.actual_path == str(plan.resolve())
    assert summary.committed is None


def test_pending_epic_maps_to_epic(tmp_path: Path) -> None:
    plan = _write_plan(tmp_path / "epic.md", "Land every phase", tier="epic")

    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    )

    assert summary is not None
    assert summary.authored_tier == "epic"
    assert summary.effective_tier == "epic"


def test_explicit_uncommitted_approval_wins_and_selects_archive(
    tmp_path: Path,
) -> None:
    archived = _write_plan(tmp_path / "archive.md", "Keep the local plan")
    sdd = _write_plan(tmp_path / "workspace" / "plans" / "plan.md", "SDD copy")
    agent = make_agent(
        archived_plan_path=str(archived),
        sdd_plan_path=str(sdd),
        plan_path=str(archived),
        plan_committed=False,
        plan_action="tale",
        workspace_dir=str(tmp_path / "workspace"),
    )

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.actual_path == str(archived.resolve())
    assert summary.effective_tier == "none"
    assert summary.committed is False


def test_committed_tale_uses_sidecar_relative_sdd_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    relative = Path("sase/repos/plans/202607/approved plan.md")
    sdd = _write_plan(workspace / relative, "Ship the approved plan")
    archived = _write_plan(tmp_path / "archive.md", "Archived proposal")
    agent = make_agent(
        archived_plan_path=str(archived),
        sdd_plan_path=relative.as_posix(),
        plan_committed=True,
        plan_action="commit",
        workspace_dir=str(workspace),
    )

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.actual_path == str(sdd.resolve())
    assert summary.display_path == relative.as_posix()
    assert summary.effective_tier == "plan"
    assert summary.committed is True


def test_legacy_epic_action_prefers_sdd_and_overrides_authored_tier(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    archived = _write_plan(tmp_path / "archive.md", "Archived proposal")
    sdd = _write_plan(workspace / "plans" / "epic.md", "Approved epic")
    agent = make_agent(
        archived_plan_path=str(archived),
        sdd_plan_path=str(sdd),
        plan_action="epic",
        workspace_dir=str(workspace),
    )

    summary = resolve_agent_associated_plan(agent)

    assert summary is not None
    assert summary.actual_path == str(sdd.resolve())
    assert summary.effective_tier == "epic"
    assert summary.committed is True


def test_direct_metadata_wins_before_bead_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path / "direct.md", "Deliver the direct plan")
    agent = make_agent(
        archived_plan_path=str(plan),
        plan_path=str(plan),
        epic_bead_id="sase-1",
        workspace_dir=str(tmp_path),
    )

    def unexpected_lookup(*_args: object, **_kwargs: object) -> Issue | None:
        raise AssertionError("direct plan metadata must win")

    monkeypatch.setattr(plan_model, "_lookup_issue", unexpected_lookup)

    summary = resolve_agent_associated_plan(agent)
    assert summary is not None
    assert summary.goal == "Deliver the direct plan"


def test_phase_bead_resolves_parent_design(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    plan = _write_plan(tmp_path / "plans" / "epic.md", "Complete the epic")
    agent = make_agent(phase_bead_id="sase-1.2", workspace_dir=str(tmp_path))
    phase = Issue(id="sase-1.2", title="Phase", parent_id="sase-1")
    epic = Issue(
        id="sase-1",
        title="Epic",
        issue_type=IssueType.PLAN,
        design="plans/epic.md",
    )
    issues = {phase.id: phase, epic.id: epic}
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: issues.get(bead_id),
    )

    with BeadIssueLookupSession() as lookup_session:
        summary = resolve_agent_associated_plan(
            agent,
            lookup_session=lookup_session,
        )

    assert summary is not None
    assert summary.actual_path == str(plan.resolve())
    assert summary.display_path == "plans/epic.md"
    assert summary.goal == "Complete the epic"


def test_known_missing_plan_keeps_path_and_unavailable_metadata(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing plan.md"
    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(missing), plan_path=str(missing))
    )

    assert summary is not None
    assert summary.actual_path == str(missing.resolve())
    assert summary.goal is None
    assert summary.effective_tier is None
    assert not summary.exists
    assert not summary.readable
    assert not summary.frontmatter_readable


def test_damaged_frontmatter_keeps_readable_plan_association(tmp_path: Path) -> None:
    plan = tmp_path / "damaged.md"
    plan.write_text("---\ntier: [tale\n---\n# Plan\n", encoding="utf-8")

    summary = resolve_agent_associated_plan(
        make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    )

    assert summary is not None
    assert summary.exists
    assert summary.readable
    assert not summary.frontmatter_readable
    assert summary.goal is None
    assert summary.effective_tier is None


def test_frontmatter_cache_reuses_parse_until_mtime_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_plan(tmp_path / "cached.md", "First goal")
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    real_reader = plan_model.read_plan_frontmatter
    reads: list[Path] = []

    def read(path: Path) -> tuple[dict[str, object], str | None]:
        reads.append(path)
        return real_reader(path)

    monkeypatch.setattr(plan_model, "read_plan_frontmatter", read)

    assert resolve_agent_associated_plan(agent).goal == "First goal"  # type: ignore[union-attr]
    assert resolve_agent_associated_plan(agent).goal == "First goal"  # type: ignore[union-attr]
    assert reads == [plan.resolve()]

    previous_mtime = plan.stat().st_mtime_ns
    _write_plan(plan, "Second goal", tier="epic")
    os.utime(
        plan,
        ns=(plan.stat().st_atime_ns, max(plan.stat().st_mtime_ns, previous_mtime + 1)),
    )

    updated = resolve_agent_associated_plan(agent)
    assert updated is not None
    assert updated.goal == "Second goal"
    assert updated.effective_tier == "epic"
    assert reads == [plan.resolve(), plan.resolve()]


def test_returns_none_without_plan_or_bead_association() -> None:
    assert resolve_agent_associated_plan(make_agent(agent_name="utility")) is None
