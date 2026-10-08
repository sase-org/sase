"""Associated-plan cache behavior and invalidation tests."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
import sase.ace.tui.models._agent_associated_plan_cache as cache_model
from sase.ace.tui.models._agent_associated_plan_summary import (
    _ASSOCIATED_PLAN_SHEET_CACHE,
    associated_plan_sheet_for,
)
from sase.ace.tui.models.agent_associated_plan import resolve_agent_plan_enrichment
from sase.bead.model import BeadNote, BeadTier, Issue, IssueType
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
    _ASSOCIATED_PLAN_SHEET_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    _ASSOCIATED_PLAN_SHEET_CACHE.clear()


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
        notes=[
            BeadNote(
                id="note-1",
                timestamp="2026-01-01T00:00:00Z",
                author="test",
                text="first note",
            )
        ],
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
    assert first.notes == "[2026-01-01T00:00:00Z · test] first note"
    assert cached.notes == "[2026-01-01T00:00:00Z · test] first note"
    assert lookups == [issue.id]

    issue.notes = [
        BeadNote(
            id="note-1",
            timestamp="2026-01-01T00:02:00Z",
            author="test",
            text="second note",
        )
    ]
    now += 61.0

    refreshed = resolve_agent_plan_enrichment(agent).phase_bead

    assert refreshed is not None
    assert refreshed.notes == "[2026-01-01T00:02:00Z · test] second note"
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


def test_accepted_sheet_cache_tracks_sibling_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sibling creation, change, and removal each refresh the accepted sheet."""
    import json as _json

    import sase.sdd.plan_decision_handoff as handoff

    plan = tmp_path / "decided.md"
    plan.write_text(
        "---\n"
        "tier: tale\n"
        "title: Decided plan\n"
        "goal: Cover sheet invalidation\n"
        "size: small\n"
        "decisions:\n"
        "  tui_note:\n"
        "    ask: Authored ask text?\n"
        "    memory: [tui.md]\n"
        '    requested: "please also update the tui memory note"\n'
        "    default: true\n"
        "    answer: true\n"
        "decided_by: reviewer\n"
        "decided_via: tui\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    sibling = tmp_path / "decided.plan-decisions.json"

    def write_sibling(ask: str) -> None:
        sibling.write_text(
            _json.dumps(
                {
                    "schema": 1,
                    "definitions": [
                        {
                            "id": "tui_note",
                            "kind": "toggle",
                            "ask": ask,
                            "default": True,
                            "effective_default": True,
                            "memory": {"selectors": ["tui.md"]},
                            "resolved": [],
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        now_ns = sibling.stat().st_mtime_ns
        os.utime(sibling, ns=(sibling.stat().st_atime_ns, now_ns + 1_000_000))

    real_load = handoff.load_stamped_decisions
    loads: list[str] = []

    def counting_load(path: object, tier: object = None) -> object:
        loads.append(str(path))
        return real_load(path, tier)  # type: ignore[arg-type]

    monkeypatch.setattr(handoff, "load_stamped_decisions", counting_load)

    agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))

    def sheet_ask() -> str | None:
        resolve_agent_associated_plan(agent)
        sheet, decided_by, _via = associated_plan_sheet_for(str(plan))
        assert sheet is not None
        assert decided_by == "reviewer"
        rows = sheet.get("rows")
        assert isinstance(rows, list) and len(rows) == 1
        return rows[0].get("ask")

    # No sibling: the neutral synthesis of the authored map applies, loaded once.
    assert sheet_ask() == "Authored ask text?"
    assert sheet_ask() == "Authored ask text?"
    assert len(loads) == 1

    # Sibling creation refreshes the accepted sheet.
    write_sibling("Frozen sibling ask?")
    assert sheet_ask() == "Frozen sibling ask?"
    assert len(loads) == 2

    # An unchanged tree never re-reads.
    assert sheet_ask() == "Frozen sibling ask?"
    assert len(loads) == 2

    # Sibling change refreshes again.
    write_sibling("Frozen sibling ask v2?")
    assert sheet_ask() == "Frozen sibling ask v2?"
    assert len(loads) == 3

    # Sibling removal falls back without stale frozen provenance.
    sibling.unlink()
    assert sheet_ask() == "Authored ask text?"
    assert len(loads) == 4


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


def test_sibling_mtime_change_reloads_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.ace.tui.models._agent_associated_plan_summary as summary_model
    from sase.sdd.plan_decision_freeze import sibling_path_for_plan
    from tests.ace.tui.models._agent_associated_plan_helpers import write_plan
    from tests.ace.tui.widgets._agent_display_helpers import make_agent

    summary_model._ASSOCIATED_PLAN_SHEET_CACHE.clear()
    summary_model._ASSOCIATED_PLAN_SHEET_SIGNATURES.clear()
    try:
        plan = write_plan(tmp_path / "sibling.md", "Sibling goal")
        agent = make_agent(archived_plan_path=str(plan), plan_path=str(plan))
        calls = {"n": 0}
        try:
            import sase.sdd.plan_decision_handoff as handoff

            real_load = handoff.load_stamped_decisions
        except Exception:
            real_load = None  # type: ignore[assignment]

        def _counting(path: object, tier: object = None):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            assert tier in ("tale", "epic")
            if real_load is None:
                return None
            return real_load(path, tier=tier)  # type: ignore[arg-type]

        monkeypatch.setattr(
            "sase.sdd.plan_decision_handoff.load_stamped_decisions", _counting
        )
        assert resolve_agent_associated_plan(agent) is not None
        assert calls["n"] == 1
        assert resolve_agent_associated_plan(agent) is not None
        assert calls["n"] == 1
        sibling = sibling_path_for_plan(plan)
        sibling.write_text('{"schema": 1, "definitions": []}', encoding="utf-8")
        assert resolve_agent_associated_plan(agent) is not None
        assert calls["n"] == 2
    finally:
        summary_model._ASSOCIATED_PLAN_SHEET_CACHE.clear()
        summary_model._ASSOCIATED_PLAN_SHEET_SIGNATURES.clear()
