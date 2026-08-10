"""Associated-plan cache behavior and invalidation tests."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
import sase.ace.tui.models._agent_associated_plan_cache as cache_model
from sase.ace.tui.models.agent_associated_plan import resolve_agent_plan_enrichment
from sase.bead.model import BeadTier, Issue, IssueType
from tests.ace.tui.models._agent_associated_plan_helpers import (
    resolve_agent_associated_plan,
    write_epic,
    write_plan,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def test_bead_tier_preserves_known_epic_fallback_on_association_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epic = Issue(
        id="sase-1",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans/missing.md",
    )
    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda _agent, bead_id, **_kwargs: epic if bead_id == epic.id else None,
    )
    agent = make_agent(agent_name="sase-1", workspace_dir=str(tmp_path))

    first = resolve_agent_associated_plan(agent)
    assert first is not None
    assert first.phase_availability == "unavailable"

    monkeypatch.setattr(
        plan_model,
        "_lookup_issue",
        lambda *_args, **_kwargs: pytest.fail("association cache was not reused"),
    )
    cached = resolve_agent_associated_plan(agent)
    assert cached is not None
    assert cached.phase_availability == "unavailable"


def test_phase_note_association_cache_reuses_lookup_and_refreshes_after_ttl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 10.0
    monkeypatch.setattr(cache_model, "monotonic", lambda: now)
    write_epic(tmp_path / "plans" / "epic.md")
    agent = make_agent(
        agent_name="sase-1.1",
        epic_bead_id="sase-1",
        phase_bead_id="sase-1.1",
        epic_plan_ref="plans/epic.md",
        sdd_plan_path="plans/epic.md",
        plan_committed=True,
        workspace_dir=str(tmp_path),
    )
    issue = Issue(
        id="sase-1.1",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id="sase-1",
        notes="first note",
    )
    lookups: list[str] = []

    def lookup(_agent: object, bead_id: str, **_kwargs: object) -> Issue | None:
        lookups.append(bead_id)
        return issue if bead_id == issue.id else None

    monkeypatch.setattr(plan_model, "_lookup_issue", lookup)

    first = resolve_agent_plan_enrichment(agent).phase_bead
    cached = resolve_agent_plan_enrichment(agent).phase_bead

    assert first is not None
    assert cached is not None
    assert first.notes == "first note"
    assert cached.notes == "first note"
    assert lookups == [issue.id]

    issue.notes = "second note"
    now += 61.0

    refreshed = resolve_agent_plan_enrichment(agent).phase_bead

    assert refreshed is not None
    assert refreshed.notes == "second note"
    assert lookups == [issue.id, issue.id]


def test_frontmatter_cache_reuses_parse_until_mtime_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_plan(tmp_path / "cached.md", "First goal")
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    real_reader = Path.read_text
    reads: list[Path] = []

    def read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        reads.append(path)
        return real_reader(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read)

    assert resolve_agent_associated_plan(agent).goal == "First goal"  # type: ignore[union-attr]
    assert resolve_agent_associated_plan(agent).goal == "First goal"  # type: ignore[union-attr]
    assert reads == [plan.resolve()]

    previous_mtime = plan.stat().st_mtime_ns
    write_plan(plan, "Second goal", tier="epic")
    os.utime(
        plan,
        ns=(plan.stat().st_atime_ns, max(plan.stat().st_mtime_ns, previous_mtime + 1)),
    )

    updated = resolve_agent_associated_plan(agent)
    assert updated is not None
    assert updated.goal == "Second goal"
    assert updated.effective_tier == "epic"
    assert reads == [plan.resolve(), plan.resolve()]


def test_title_is_normalized_cached_and_invalidated_with_file_signature(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "title.md"
    plan.write_text(
        "---\n"
        "tier: tale\n"
        "title: >-\n"
        "  Full\n"
        "  plan   title\n"
        "goal: Keep cached metadata responsive\n"
        "size: small\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    real_reader = Path.read_text
    reads = 0

    def read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        nonlocal reads
        reads += 1
        return real_reader(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read)

    first = resolve_agent_associated_plan(agent)
    cached = resolve_agent_associated_plan(agent)
    assert first is not None
    assert cached is not None
    assert first.title == "Full plan title"
    assert cached.title == first.title
    assert reads == 1

    previous_mtime = plan.stat().st_mtime_ns
    write_plan(
        plan,
        "Keep cached metadata responsive",
        title="Updated title",
    )
    os.utime(
        plan,
        ns=(plan.stat().st_atime_ns, max(plan.stat().st_mtime_ns, previous_mtime + 1)),
    )

    updated = resolve_agent_associated_plan(agent)
    assert updated is not None
    assert updated.title == "Updated title"
    assert reads == 2


def test_epic_phase_cache_reuses_validation_until_signature_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = write_epic(tmp_path / "cached epic.md")
    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))
    real_validator = plan_model.validate_plan
    validations: list[tuple[str, str]] = []

    def validate(  # type: ignore[no-untyped-def]
        content: str,
        tier: str,
        *,
        mode: str = "authoring",
    ):
        validations.append((content, mode))
        return real_validator(content, tier, mode=mode)

    monkeypatch.setattr(plan_model, "validate_plan", validate)

    first = resolve_agent_associated_plan(agent)
    cached = resolve_agent_associated_plan(agent)
    assert first is not None
    assert cached is not None
    assert cached.phases == first.phases
    assert len(validations) == 1
    assert validations[0][1] == "launch"

    previous_mtime = plan.stat().st_mtime_ns
    updated_content = (
        plan.read_text(encoding="utf-8")
        .replace(
            "Responsive roadmap",
            "Responsive phase roadmap",
        )
        .replace("    size: medium\n", "    size: large\n")
    )
    plan.write_text(updated_content, encoding="utf-8")
    os.utime(
        plan,
        ns=(plan.stat().st_atime_ns, max(plan.stat().st_mtime_ns, previous_mtime + 1)),
    )

    updated = resolve_agent_associated_plan(agent)
    assert updated is not None
    assert updated.phases[2].title == "Responsive phase roadmap"
    assert updated.phases[2].size == "large"
    assert len(validations) == 2
    assert validations[1][1] == "launch"
