"""Tests for the PR_ORIGIN Patch scalar."""

from __future__ import annotations

from rich.console import Console

from sase.ace.display import display_patch
from sase.ace.patch import Patch, parse_project_file
from sase.ace.query.highlighting import PR_ORIGIN_VALUE_STYLES
from sase.ace.tui.widgets.patch_detail import PatchDetail


def test_pr_origin_parse_tri_state_and_absence_defaults_unknown(tmp_path) -> None:
    project = tmp_path / "project.sase"
    project.write_text(
        """\
NAME: from_sase
PR: https://example.test/pull/1
PR_ORIGIN: sase
STATUS: WIP

NAME: from_external
PR: https://example.test/pull/2
PR_ORIGIN: external
STATUS: WIP

NAME: explicit_unknown
PR: https://example.test/pull/3
PR_ORIGIN: unknown
STATUS: WIP

NAME: absent_origin
PR: https://example.test/pull/4
STATUS: WIP
""",
        encoding="utf-8",
    )

    patches = {patch.name: patch for patch in parse_project_file(str(project))}

    assert patches["from_sase"].pr_origin == "sase"
    assert patches["from_external"].pr_origin == "external"
    assert patches["explicit_unknown"].pr_origin == "unknown"
    assert patches["absent_origin"].pr_origin == "unknown"


def test_display_patch_renders_pr_origin() -> None:
    patch = Patch(
        name="from_external",
        description="External PR",
        parent=None,
        pr_url="https://example.test/pull/2",
        pr_origin="external",
        status="WIP",
    )
    console = Console(record=True, force_terminal=True)

    display_patch(patch, console)

    text = console.export_text()
    assert "PR_ORIGIN: external" in text


def test_patch_detail_renders_pr_origin() -> None:
    patch = Patch(
        name="from_external",
        description="External PR",
        parent=None,
        pr_url="https://example.test/pull/2",
        pr_origin="external",
        status="WIP",
    )
    widget = PatchDetail()
    content, _, _, _, _ = widget._build_display_content(patch, "")

    assert "PR_ORIGIN: external" in content.renderable.plain


def test_pr_origin_shared_styles_cover_tri_state() -> None:
    assert set(PR_ORIGIN_VALUE_STYLES) == {"sase", "external", "unknown"}
    assert "#FF5F5F" in PR_ORIGIN_VALUE_STYLES["external"]


def test_display_patch_renders_adopted_note_for_external() -> None:
    patch = Patch(
        name="from_external",
        description="External PR",
        parent=None,
        pr_url="https://example.test/pull/2",
        pr_origin="external",
        status="WIP",
    )
    console = Console(record=True, force_terminal=True)

    display_patch(patch, console)

    text = console.export_text()
    assert "Adopted from an external PR" in text


def test_display_patch_omits_adopted_note_for_sase_origin() -> None:
    patch = Patch(
        name="from_sase",
        description="Tracked PR",
        parent=None,
        pr_url="https://example.test/pull/1",
        pr_origin="sase",
        status="WIP",
    )
    console = Console(record=True, force_terminal=True)

    display_patch(patch, console)

    text = console.export_text()
    assert "Adopted from an external PR" not in text


def test_patch_detail_renders_adopted_note_for_external() -> None:
    patch = Patch(
        name="from_external",
        description="External PR",
        parent=None,
        pr_url="https://example.test/pull/2",
        pr_origin="external",
        status="WIP",
    )
    widget = PatchDetail()
    content, _, _, _, _ = widget._build_display_content(patch, "")

    assert "Adopted from an external PR" in content.renderable.plain


def test_patch_detail_omits_adopted_note_for_unknown_origin() -> None:
    patch = Patch(
        name="unknown_origin",
        description="Undetermined PR",
        parent=None,
        pr_url="https://example.test/pull/3",
        pr_origin="unknown",
        status="WIP",
    )
    widget = PatchDetail()
    content, _, _, _, _ = widget._build_display_content(patch, "")

    assert "Adopted from an external PR" not in content.renderable.plain
