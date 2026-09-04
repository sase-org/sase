"""Targeted-hydration coverage for the Plans/document-provider pane."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.widgets.artifacts.entry_navigation import (
    ArtifactEntryTarget,
    HydrationOutcome,
)
from sase.ace.tui.widgets.artifacts.plans_data import PlansSnapshot
from sase.ace.tui.widgets.artifacts.plans_data_models import PlansProject
from sase.ace.tui.widgets.artifacts.plans_navigation import PlansNavigationMixin
from sase.plan_search.model import Plan, PlanSearchMatch
from tests.ace.tui._artifacts_plans_helpers import _snapshot


class _Pane(PlansNavigationMixin):
    """Bare stand-in exposing only what ``hydrate_ref``/``install_hydrated_row`` need."""

    def __init__(
        self,
        snapshot: PlansSnapshot,
        *,
        project_scope: str | None,
        provider_kind: str = "plan",
    ) -> None:
        self._snapshot = snapshot
        self.project_scope = project_scope
        self.provider_kind = provider_kind


def _match(path: Path) -> PlanSearchMatch:
    return PlanSearchMatch(
        plan=Plan(
            source="repo",
            kind="epic",
            path=str(path),
            relpath="202608/deep_archive.md",
            name="deep_archive",
            title="Deep archive plan",
            status="done",
            created_at="2026-08-01 10:00:00",
            prompt_link="",
            summary="Deep archive summary.",
            body="Deep archive body.",
            frontmatter={"tier": "epic", "status": "done"},
        ),
        matched_fields=[],
        score=1.0,
    )


def test_hydrate_ref_resolves_archived_document_via_scoped_directory_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deep-archived doc outside the preview window resolves via one narrow scan."""
    snapshot = _snapshot(tmp_path)
    pane = _Pane(snapshot, project_scope="alpha")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_navigation.resolve_projects",
        lambda _scope: (PlansProject("alpha", "Alpha", str(tmp_path / "workspace")),),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_navigation.project_document_roots",
        lambda _project, **_kwargs: {"plans": tmp_path},
    )

    hydrated_path = tmp_path / "202608" / "deep_archive.md"
    hydrated_match = _match(hydrated_path)
    calls: list[object] = []

    def fake_search(*args: object, **kwargs: object) -> list[PlanSearchMatch]:
        calls.append(kwargs.get("document_corpora"))
        return [hydrated_match]

    monkeypatch.setattr("sase.plan_search.facade.search", fake_search)

    outcome = pane.hydrate_ref("plan", str(hydrated_path))

    assert outcome.outcome is HydrationOutcome.FETCHED
    project, role, match = outcome.payload
    assert project == "alpha"
    assert role == "plans"
    assert match is hydrated_match
    # Scoped to the one containing directory, never the whole archive root.
    assert calls == [((tmp_path / "202608", "plans"),)]

    before = len(pane._snapshot.archive)
    target = pane.install_hydrated_row(outcome.payload)

    assert target == ArtifactEntryTarget(
        "ref:plan", ("alpha", "archive", str(hydrated_path))
    )
    assert len(pane._snapshot.archive) == before + 1
    assert any(
        item.match.plan.path == str(hydrated_path) for item in pane._snapshot.archive
    )

    # Idempotent: re-installing the identical row does not duplicate it.
    replay = pane.install_hydrated_row(outcome.payload)
    assert replay == target
    assert len(pane._snapshot.archive) == before + 1


def test_hydrate_ref_reports_absent_when_search_misses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    pane = _Pane(snapshot, project_scope="alpha")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_navigation.resolve_projects",
        lambda _scope: (PlansProject("alpha", "Alpha", str(tmp_path / "workspace")),),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_navigation.project_document_roots",
        lambda _project, **_kwargs: {"plans": tmp_path},
    )
    monkeypatch.setattr("sase.plan_search.facade.search", lambda *a, **k: [])

    outcome = pane.hydrate_ref("plan", str(tmp_path / "202608" / "missing.md"))
    assert outcome.outcome is HydrationOutcome.ABSENT


def test_hydrate_ref_unsupported_for_notification_id_payload(tmp_path: Path) -> None:
    """A proposal's identity is a notification id, not a path -- never hydrated."""
    pane = _Pane(_snapshot(tmp_path), project_scope="alpha")

    outcome = pane.hydrate_ref("plan", "proposal-1")
    assert outcome.outcome is HydrationOutcome.UNSUPPORTED


def test_hydrate_ref_unsupported_outside_every_known_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot(tmp_path)
    pane = _Pane(snapshot, project_scope="alpha")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_navigation.resolve_projects",
        lambda _scope: (PlansProject("alpha", "Alpha", str(tmp_path / "workspace")),),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_navigation.project_document_roots",
        lambda _project, **_kwargs: {"plans": tmp_path / "plans-only"},
    )

    outcome = pane.hydrate_ref("plan", str(tmp_path / "elsewhere" / "doc.md"))
    assert outcome.outcome is HydrationOutcome.UNSUPPORTED
