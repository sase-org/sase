"""Focused phase-bead plan metadata and cache tests."""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path

import pytest

import sase.ace.tui.models.agent_associated_plan as plan_model
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_associated_plan import (
    PhaseBeadSummary,
    resolve_agent_plan_enrichment,
)
from tests.ace.tui.widgets._agent_display_helpers import make_agent


@pytest.fixture(autouse=True)
def _clear_plan_caches() -> Iterator[None]:
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()
    yield
    plan_model._PLAN_FILE_CACHE.clear()
    plan_model._PLAN_ASSOCIATION_CACHE.clear()


def _write_epic(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "tier: epic\n"
        "title: Epic phase metadata\n"
        "goal: Deliver the selected phase safely\n"
        "phases:\n"
        "  - id: core\n"
        "    title: Canonical phase summary\n"
        "    depends_on: []\n"
        "    description: Normalize the authoritative validator payload.\n"
        "    size: small\n"
        "---\n"
        "# Plan\n",
        encoding="utf-8",
    )
    return path


def _phase_agent(tmp_path: Path, reference: str = "plans/epic.md") -> Agent:
    return make_agent(
        agent_name="sase-1.1",
        epic_bead_id="sase-1",
        phase_bead_id="sase-1.1",
        epic_plan_ref=reference,
        sdd_plan_path=reference,
        plan_committed=True,
        workspace_dir=str(tmp_path),
    )


def test_phase_display_keeps_relative_reference_for_external_sdd_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_epic(tmp_path / "sidecar" / "epic.md")
    reference = "sase/repos/plans/202607/external epic.md"
    monkeypatch.setattr(
        plan_model,
        "_resolve_plan_reference",
        lambda _reference, _agent: plan.resolve(),
    )

    enrichment = resolve_agent_plan_enrichment(
        _phase_agent(tmp_path / "workspace", reference)
    )

    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.actual_plan_path == str(plan.resolve())
    assert enrichment.phase_bead.display_plan_path == reference


def test_modern_phase_normalizes_epic_title_once(tmp_path: Path) -> None:
    plan = _write_epic(tmp_path / "plans" / "epic.md")
    plan.write_text(
        plan.read_text(encoding="utf-8").replace(
            "title: Epic phase metadata",
            "title: >-\n  Epic   phase\n  metadata",
        ),
        encoding="utf-8",
    )

    enrichment = resolve_agent_plan_enrichment(_phase_agent(tmp_path))

    assert enrichment.phase_bead is not None
    assert enrichment.phase_bead.epic_title == "Epic phase metadata"


def test_unreadable_modern_phase_keeps_only_identity_and_known_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _write_epic(tmp_path / "plans" / "epic.md")
    monkeypatch.setattr(plan_model.os, "access", lambda *_args: False)
    monkeypatch.setattr(
        plan_model,
        "validate_plan",
        lambda *_args: pytest.fail("unreadable phase plans must not be validated"),
    )

    enrichment = resolve_agent_plan_enrichment(_phase_agent(tmp_path))

    assert enrichment.phase_bead == PhaseBeadSummary(
        id="sase-1.1",
        description=None,
        actual_plan_path=str(plan.resolve()),
        display_plan_path="plans/epic.md",
        plan_exists=True,
        plan_readable=False,
        epic_title=None,
    )


def test_phase_bead_cache_refreshes_description_and_title_after_plan_edit(
    tmp_path: Path,
) -> None:
    plan = _write_epic(tmp_path / "plans" / "epic.md")
    agent = _phase_agent(tmp_path)

    first = resolve_agent_plan_enrichment(agent).phase_bead
    cached = resolve_agent_plan_enrichment(agent).phase_bead
    assert first is not None
    assert cached == first
    assert first.description == "Normalize the authoritative validator payload."
    assert first.epic_title == "Epic phase metadata"

    previous_mtime = plan.stat().st_mtime_ns
    updated_content = (
        plan.read_text(encoding="utf-8")
        .replace("title: Epic phase metadata", "title: Updated epic title")
        .replace(
            "description: Normalize the authoritative validator payload.",
            "description: Updated selected phase description.",
        )
    )
    plan.write_text(updated_content, encoding="utf-8")
    os.utime(
        plan,
        ns=(plan.stat().st_atime_ns, max(plan.stat().st_mtime_ns, previous_mtime + 1)),
    )

    updated = resolve_agent_plan_enrichment(agent).phase_bead
    assert updated is not None
    assert updated.description == "Updated selected phase description."
    assert updated.epic_title == "Updated epic title"
