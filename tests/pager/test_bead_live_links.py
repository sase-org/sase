"""Live bead-store resolution tests for pager links."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from sase.pager.app import SasePager
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    target_resolution_ref,
)
from sase.pager.link_context import LinkAnchor, LinkResolutionContext
from sase.pager.resolve import LinkTargetKind, resolve_link
from sase.pager.screen import PagerScreen
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


def _seed_beads(
    checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Issue, Issue, Issue]:
    with BeadProject.init(checkout):
        pass
    isolate_bead_store_resolution(monkeypatch, checkout, project_name="sase")
    with BeadProject(checkout) as project:
        first = project.create(
            "Pager first",
            IssueType.TASK,
            description="first detail",
            task_type="bug",
            size="small",
        )
        second = project.create(
            "Pager second",
            IssueType.TASK,
            description="second detail",
            task_type="bug",
            size="small",
        )
        third = project.create(
            "Pager third",
            IssueType.TASK,
            description="third detail",
            task_type="bug",
            size="small",
        )
        project.add_link(first.id, f"bead:{second.id}", "related", "first to second")
        project.add_link(second.id, f"bead:{third.id}", "related", "second to third")
    return first, second, third


def _bead_context(checkout: Path) -> LinkResolutionContext:
    return LinkResolutionContext(anchors=(LinkAnchor(checkout, workspace_num=1),))


def test_resolve_link_opens_live_bead_without_generated_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second, _third = _seed_beads(tmp_path, monkeypatch)
    calls: list[dict[str, object]] = []

    def fail_artifact_page_resolution(_ref: str, **kwargs: object) -> object:
        calls.append(kwargs)
        raise AssertionError("bead links should resolve from the live bead store")

    monkeypatch.setattr(
        "sase.pager._resolve_artifact_refs.resolve_cli_reference",
        fail_artifact_page_resolution,
    )

    resolution = resolve_link(f"bead:{first.id}", context=_bead_context(tmp_path))

    assert calls == []
    assert not (tmp_path / "pages").exists()
    assert resolution.target is not None
    assert resolution.target.kind is LinkTargetKind.DOCUMENT
    assert resolution.target.document is not None
    section = resolution.target.document.sections[0]
    assert section.subject_ref == f"bead:{first.id}"
    assert section.link_anchors == (LinkAnchor(tmp_path.resolve(), workspace_num=1),)
    assert section.owner is not None
    assert section.owner.project_key == "sase"
    assert "Pager first" in section.plain_text
    assert "LINKS (1)" in section.plain_text
    assert f"bead:{second.id}" in section.plain_text


def test_resolve_link_reports_missing_beads_without_materializing_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _first, _second, _third = _seed_beads(tmp_path, monkeypatch)
    calls: list[dict[str, object]] = []

    from sase.bead import cli_location

    real_resolve = cli_location.resolve_beads_location

    def spy_resolve_beads_location(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return real_resolve(*args, **kwargs)

    monkeypatch.setattr(
        cli_location, "resolve_beads_location", spy_resolve_beads_location
    )

    resolution = resolve_link("bead:sase-missing", context=_bead_context(tmp_path))

    assert resolution.target is None
    assert (
        resolution.unresolved_message
        == "bead:sase-missing could not be resolved - issue not found: sase-missing"
    )
    assert resolution.retryable is False
    assert calls
    assert all(call["require_existing"] is True for call in calls)
    assert all(call["materialize"] is False for call in calls)


def _hint_for_target(screen: PagerScreen, ref: str) -> str:
    layer = screen._label_layer
    assert layer is not None
    for label in layer.labels:
        if target_resolution_ref(label.target, screen.document.origin) == ref:
            return label.hint
    labels = [
        target_resolution_ref(label.target, screen.document.origin)
        for label in layer.labels
    ]
    raise AssertionError(f"{ref!r} not labelled; saw {labels!r}")


async def test_pager_follows_bead_links_and_preserves_trail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second, third = _seed_beads(tmp_path, monkeypatch)
    body = f"typed @bead:{second.id}\nbare {second.id}\n"
    section = PagerSection(
        identity=f"bead:{first.id}",
        title=first.id,
        kind="bead",
        body=body,
        subject_ref=f"bead:{first.id}",
        link_anchors=(LinkAnchor(tmp_path),),
        origin=PagerOrigin.BEAD,
    )
    source = PagerDocument(
        sections=(section,),
        title=first.id,
        origin=PagerOrigin.BEAD,
    )
    app = SasePager(source)

    async with app.run_test(size=(100, 28)) as pilot:
        screen = app.screen
        assert isinstance(screen, PagerScreen)
        await pilot.pause()

        await pilot.press(_hint_for_target(screen, f"bead:{second.id}"))
        await pilot.pause(0.2)
        await pilot.pause(0.2)

        assert screen.document.title == f"{second.id} · Pager second"
        assert screen._back_trail
        assert screen._forward_trail == []
        assert f"bead:{third.id}" in screen.document.sections[0].plain_text

        await pilot.press(_hint_for_target(screen, f"bead:{third.id}"))
        await pilot.pause(0.2)
        await pilot.pause(0.2)

        assert screen.document.title == f"{third.id} · Pager third"

        await pilot.press("backspace")
        await pilot.pause()

        assert screen.document.title == f"{second.id} · Pager second"
        assert screen._forward_trail
        footer = screen.query_one("#pager-footer", Static)
        assert "^I forward" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("tab")
        await pilot.pause()

        assert screen.document.title == f"{third.id} · Pager third"
