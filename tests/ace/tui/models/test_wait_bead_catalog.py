"""Tests for the pure Wait-modal bead catalog and validation helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models import wait_bead_catalog as wbc
from sase.ace.tui.models.wait_bead_catalog import (
    WaitBeadCandidate,
    WaitBeadCatalog,
    classify_wait_bead_selection,
    filter_wait_bead_candidates,
    load_wait_bead_catalog,
    raw_wait_bead_inventory,
)
from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead_status_presentation import bead_status_presentation


def _issue(
    bead_id: str,
    *,
    title: str = "Title",
    status: Status = Status.OPEN,
    issue_type: IssueType = IssueType.TASK,
    created_at: str = "2026-01-01T00:00:00Z",
    updated_at: str = "2026-01-01T00:00:00Z",
) -> Issue:
    return Issue(
        id=bead_id,
        title=title,
        status=status,
        issue_type=issue_type,
        created_at=created_at,
        updated_at=updated_at,
    )


def _candidate(
    bead_id: str,
    *,
    title: str = "Title",
    status: str = "open",
    updated_at: str = "2026-01-01T00:00:00Z",
) -> WaitBeadCandidate:
    return WaitBeadCandidate(
        bead_id=bead_id,
        title=title,
        status=status,
        type_label="task",
        created_at="2026-01-01T00:00:00Z",
        updated_at=updated_at,
    )


def test_load_wait_bead_catalog_returns_unavailable_without_project_key() -> None:
    catalog = load_wait_bead_catalog(None)
    assert catalog.available is False
    assert catalog.candidates == ()


def test_raw_wait_bead_inventory_reuses_mtime_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issues = (
        _issue("sase-a", title="Active", status=Status.IN_PROGRESS),
        _issue("sase-b", title="Open"),
    )
    monkeypatch.setattr(wbc, "_index_token", lambda project: (1, 1))
    monkeypatch.setattr(wbc, "open_bead_candidates_for_project", lambda project: issues)
    monkeypatch.setattr(wbc, "closed_bead_ids_for_project", lambda project: frozenset())
    wbc._RAW_CACHE.clear()

    rows, available = raw_wait_bead_inventory("raw-inv")
    again, again_available = raw_wait_bead_inventory("raw-inv")

    assert available is True
    assert again_available is True
    assert rows == again
    assert {row["id"] for row in rows} == {"sase-a", "sase-b"}
    assert rows[0]["project"] == "raw-inv"


def test_load_wait_bead_catalog_returns_unavailable_when_store_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wbc, "canonical_beads_dir_for_project", lambda project: None)
    monkeypatch.setattr(wbc, "open_bead_candidates_for_project", lambda project: None)
    catalog = load_wait_bead_catalog("no-such-project")
    assert catalog.available is False
    assert catalog.candidates == ()


def test_load_wait_bead_catalog_orders_by_status_then_recency_then_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issues = (
        _issue("z-open", status=Status.OPEN, updated_at="2026-01-01T00:00:00Z"),
        _issue("a-open", status=Status.OPEN, updated_at="2026-01-01T00:00:00Z"),
        _issue("snoozed-1", status=Status.SNOOZED, updated_at="2026-01-05T00:00:00Z"),
        _issue("ready-1", status=Status.READY, updated_at="2026-01-05T00:00:00Z"),
        _issue(
            "in-progress-old",
            status=Status.IN_PROGRESS,
            updated_at="2026-01-01T00:00:00Z",
        ),
        _issue(
            "in-progress-new",
            status=Status.IN_PROGRESS,
            updated_at="2026-01-09T00:00:00Z",
        ),
        _issue("claimed-1", status=Status.CLAIMED, updated_at="2026-01-05T00:00:00Z"),
    )
    monkeypatch.setattr(
        wbc, "canonical_beads_dir_for_project", lambda project: Path("/does/not/exist")
    )
    monkeypatch.setattr(wbc, "open_bead_candidates_for_project", lambda project: issues)
    monkeypatch.setattr(wbc, "closed_bead_ids_for_project", lambda project: frozenset())

    catalog = load_wait_bead_catalog("proj")

    assert [c.bead_id for c in catalog.candidates] == [
        "in-progress-new",
        "in-progress-old",
        "claimed-1",
        "ready-1",
        "a-open",
        "z-open",
        "snoozed-1",
    ]


def test_load_wait_bead_catalog_excludes_own_bead_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issues = (_issue("epic-1"), _issue("epic-1.2"), _issue("other"))
    monkeypatch.setattr(
        wbc, "canonical_beads_dir_for_project", lambda project: Path("/does/not/exist")
    )
    monkeypatch.setattr(wbc, "open_bead_candidates_for_project", lambda project: issues)
    monkeypatch.setattr(wbc, "closed_bead_ids_for_project", lambda project: frozenset())

    catalog = load_wait_bead_catalog(
        "proj", own_bead_ids=frozenset({"epic-1", "epic-1.2"})
    )

    assert [c.bead_id for c in catalog.candidates] == ["other"]


def test_load_wait_bead_catalog_caches_by_index_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_key = f"wait-bead-cache-{tmp_path.name}"
    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        project.create("First", IssueType.PLAN)

    beads_dir = tmp_path / "beads"
    monkeypatch.setattr(
        "sase.bead.store_locator.get_project_beads_dirs_for_project",
        lambda project: [beads_dir] if project == project_key else [],
    )

    reads = {"count": 0}
    real_open = wbc.open_bead_candidates_for_project

    def counting_open(project: str) -> tuple[Issue, ...] | None:
        reads["count"] += 1
        return real_open(project)

    monkeypatch.setattr(wbc, "open_bead_candidates_for_project", counting_open)

    first = load_wait_bead_catalog(project_key)
    second = load_wait_bead_catalog(project_key)
    assert first.available is True
    assert second.available is True
    assert reads["count"] == 1

    with BeadProject.init(tmp_path, beads_dirname="beads") as project:
        project.create("Second", IssueType.PLAN)

    third = load_wait_bead_catalog(project_key)
    assert third.available is True
    assert reads["count"] == 2
    assert len(third.candidates) == 2


def test_filter_wait_bead_candidates_matches_id_and_title_case_insensitively() -> None:
    catalog = WaitBeadCatalog(
        candidates=(
            _candidate("sase-1", title="Fix login bug"),
            _candidate("sase-2", title="Improve throughput"),
        ),
        available=True,
    )

    by_id = filter_wait_bead_candidates(catalog, "SASE-1")
    assert [c.bead_id for c in by_id.rows] == ["sase-1"]

    by_title = filter_wait_bead_candidates(catalog, "login")
    assert [c.bead_id for c in by_title.rows] == ["sase-1"]

    empty_fragment = filter_wait_bead_candidates(catalog, "")
    assert len(empty_fragment.rows) == 2


def test_filter_wait_bead_candidates_reports_overflow_count() -> None:
    catalog = WaitBeadCatalog(
        candidates=tuple(_candidate(f"sase-{i}") for i in range(5)),
        available=True,
    )

    results = filter_wait_bead_candidates(catalog, "", limit=2)

    assert len(results.rows) == 2
    assert results.omitted == 3


def test_classify_empty_selection_is_neutral() -> None:
    preview = classify_wait_bead_selection(WaitBeadCatalog(available=True), [])
    assert preview.css_class == wbc.WAIT_BEAD_PREVIEW_NEUTRAL
    assert "closed" in preview.message
    assert preview.guard_armed is False


def test_classify_loading_catalog_is_neutral() -> None:
    preview = classify_wait_bead_selection(None, ["sase-1"], project_label="myproj")
    assert preview.css_class == wbc.WAIT_BEAD_PREVIEW_NEUTRAL
    assert "loading" in preview.message
    assert "myproj" in preview.message
    assert preview.guard_armed is False


def test_classify_unavailable_store_is_neutral_and_never_arms_guard() -> None:
    preview = classify_wait_bead_selection(WaitBeadCatalog(available=False), ["sase-1"])
    assert preview.css_class == wbc.WAIT_BEAD_PREVIEW_NEUTRAL
    assert "unavailable" in preview.message
    assert preview.guard_armed is False


def test_classify_own_bead_is_error_and_arms_guard() -> None:
    catalog = WaitBeadCatalog(candidates=(), available=True)
    preview = classify_wait_bead_selection(
        catalog, ["epic-1"], own_bead_ids=frozenset({"epic-1"})
    )
    assert preview.css_class == wbc.WAIT_BEAD_PREVIEW_ERROR
    assert "own bead" in preview.message
    assert preview.guard_armed is True


def test_classify_unknown_id_is_error_and_arms_guard() -> None:
    catalog = WaitBeadCatalog(candidates=(_candidate("sase-1"),), available=True)
    preview = classify_wait_bead_selection(
        catalog, ["sase-nope"], project_label="myproj"
    )
    assert preview.css_class == wbc.WAIT_BEAD_PREVIEW_ERROR
    assert "sase-nope" in preview.message
    assert "myproj" in preview.message
    assert preview.guard_armed is True


def test_classify_known_beads_is_valid_with_status_entries_and_aggregate() -> None:
    catalog = WaitBeadCatalog(
        candidates=(
            _candidate("sase-1", status="open"),
            _candidate("sase-2", status="in_progress"),
        ),
        available=True,
    )
    preview = classify_wait_bead_selection(catalog, ["sase-1", "sase-2"])
    assert preview.css_class == wbc.WAIT_BEAD_PREVIEW_VALID
    assert preview.guard_armed is False
    open_presentation = bead_status_presentation("open")
    assert f"sase-1 {open_presentation.tui_glyph}" in preview.message
    assert "2 beads · 1 open · 1 in progress" in preview.message


def test_classify_caps_preview_entries_at_three() -> None:
    catalog = WaitBeadCatalog(
        candidates=tuple(_candidate(f"sase-{i}") for i in range(5)),
        available=True,
    )
    preview = classify_wait_bead_selection(catalog, [f"sase-{i}" for i in range(5)])
    assert preview.css_class == wbc.WAIT_BEAD_PREVIEW_VALID
    assert "+2 more" in preview.message
    assert "5 beads" in preview.message


def test_classify_already_closed_id_is_valid_with_closed_note() -> None:
    catalog = WaitBeadCatalog(
        candidates=(),
        available=True,
        closed_ids=frozenset({"sase-1"}),
    )
    preview = classify_wait_bead_selection(catalog, ["sase-1"])
    assert preview.css_class == wbc.WAIT_BEAD_PREVIEW_VALID
    assert preview.guard_armed is False
    assert "sase-1 is already closed" in preview.message


def test_wait_bead_catalog_by_id_maps_candidates() -> None:
    candidate = _candidate("sase-1")
    catalog = WaitBeadCatalog(candidates=(candidate,), available=True)
    assert catalog.by_id == {"sase-1": candidate}
