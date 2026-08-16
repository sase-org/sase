"""Context-building coverage for the registry-driven Copy as palette."""

from __future__ import annotations

import pytest

from sase.ace.testing.fixtures import make_patch
from sase.ace.tui.actions.clipboard._palette import build_copy_as_context
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.artifact_file_clipboard import artifact_file_clipboard_path
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from tests.ace.tui._copy_as_palette_helpers import (
    PaletteHarness,
    bead_pane,
    commit_entry,
    commit_pane,
    commit_target,
    file_entry,
    file_pane,
)


def test_commit_rows_join_registry_keys_availability_and_warm_previews() -> None:
    app = PaletteHarness()
    entry = commit_entry(
        "a",
        subject="Add the Copy as palette",
        plan="plan:202607/copy_as_palette.md",
    )
    app.commits_pane = commit_pane((entry,))

    context = build_copy_as_context(app)

    assert context is not None
    assert context.group == "artifacts_stitches"
    assert context.subtitle == "SASE · sase@aaaaaaa"
    assert [(row.target, row.key_display) for row in context.rows] == [
        ("sha", "%"),
        ("reference", "@"),
        ("link", "l"),
        ("message", "m"),
        ("repo_sha", "r"),
        ("plan", "p"),
        ("json", "J"),
        ("handoff", "!"),
        ("snapshot", "s"),
    ]
    previews = {row.target: row.preview for row in context.rows}
    assert previews["sha"] == "a" * 40
    assert previews["message"] == "Add the Copy as palette"
    assert previews["plan"] == "plan:202607/copy_as_palette.md"


def test_bead_rows_cover_every_default_target_with_warm_previews() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "beads"
    app.beads_pane = bead_pane()

    context = build_copy_as_context(app)

    assert context is not None
    assert context.group == "artifacts_beads"
    assert context.subtitle == "SASE · sase-copy.1 · Complete bead copy mode"
    assert [(row.target, row.key_display) for row in context.rows] == [
        ("id", "%"),
        ("reference", "@"),
        ("link", "l"),
        ("title", "t"),
        ("body", "b"),
        ("design", "d"),
        ("json", "J"),
        ("handoff", "!"),
        ("snapshot", "s"),
        ("bug", "u"),
    ]
    previews = {row.target: row.preview for row in context.rows}
    assert previews["id"] == "sase-copy.1"
    assert previews["title"] == "Complete bead copy mode"
    assert previews["body"] == "Polish the copy palette. Keep previews warm."
    assert previews["design"] == "plan:202608/copy_palette.md"


def test_bead_rows_hide_empty_optional_body_and_design_targets() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "beads"
    app.beads_pane = bead_pane(description="", notes="", design="")

    context = build_copy_as_context(app)

    assert context is not None
    targets = {row.target for row in context.rows}
    assert "body" not in targets
    assert "design" not in targets
    assert {
        "id",
        "title",
        "reference",
        "link",
        "json",
        "handoff",
        "snapshot",
    } <= targets


def test_files_rows_cover_every_default_target_with_warm_previews() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "files"
    entry = file_entry(
        "default:0123456789abcdef01234567",
        label="Copy notes",
        kind="markdown",
        path="/workspace/artifacts/copy.md",
        source_path="/workspace/notes/copy.md",
        size_bytes=2048,
    )
    app.files_pane = file_pane(
        (entry,),
        view_modes={entry.id: "markdown"},
    )

    context = build_copy_as_context(app)

    assert context is not None
    assert context.group == "artifacts_other"
    assert context.subtitle == "SASE · Copy notes"
    assert [(row.target, row.key_display) for row in context.rows] == [
        ("contents", "%"),
        ("reference", "@"),
        ("link", "L"),
        ("path", "p"),
        ("source", "o"),
        ("label", "l"),
        ("json", "j"),
        ("handoff", "!"),
        ("snapshot", "s"),
    ]
    assert {row.target: row.preview for row in context.rows} == {
        "contents": "markdown · 2.0 KiB",
        "reference": f"@file:{entry.id}",
        "link": f"[Copy notes](file:{entry.id})",
        "path": "/workspace/artifacts/copy.md",
        "source": "/workspace/notes/copy.md",
        "label": "Copy notes",
        "json": "markdown · 2.0 KiB · metadata",
        "handoff": f"@file:{entry.id} · new agent prompt",
        "snapshot": "current Artifacts pane",
    }


def test_files_rows_filter_binary_contents_and_missing_source_from_warm_state() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "files"
    entry = file_entry(
        "default:fedcba987654321001234567",
        label="Copy image",
        kind="image",
        path="/workspace/artifacts/copy.png",
        source_path=None,
        size_bytes=4096,
    )
    app.files_pane = file_pane(
        (entry,),
        view_modes={entry.id: "image"},
    )

    context = build_copy_as_context(app)

    assert context is not None
    targets = {row.target for row in context.rows}
    assert "contents" not in targets
    assert "source" not in targets
    assert targets == {
        "reference",
        "link",
        "path",
        "label",
        "json",
        "handoff",
        "snapshot",
    }


def test_files_pdf_row_previews_the_source_path_its_copy_actually_yields() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "files"
    entry = file_entry(
        "explicit:aaaaaaaaaaaaaaaaaaaaaaaa",
        label="Copy report",
        kind="pdf",
        path="/workspace/artifacts/report.pdf",
        source_path="/workspace/notes/report.md",
        size_bytes=8192,
    )
    app.files_pane = file_pane((entry,), view_modes={entry.id: "pdf"})

    context = build_copy_as_context(app)

    assert context is not None
    path = next(row for row in context.rows if row.target == "path")
    copied = artifact_file_clipboard_path(entry)
    assert copied is not None
    assert path.preview == copied.text == "/workspace/notes/report.md"


def test_files_vcs_row_keeps_materializable_path_and_contents_targets() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "files"
    entry = file_entry(
        "default:bbbbbbbbbbbbbbbbbbbbbbbb",
        label="Tracked notes",
        kind="markdown",
        path=None,
        source_path="/workspace/notes/tracked.md",
        size_bytes=2048,
        vcs_repo="sase",
        vcs_sha="a" * 40,
        vcs_relpath="docs/tracked.md",
    )
    app.files_pane = file_pane((entry,), view_modes={entry.id: "markdown"})

    context = build_copy_as_context(app)

    assert context is not None
    rows = {row.target: row for row in context.rows}
    assert rows["path"].preview == "docs/tracked.md"
    assert rows["contents"].preview == "markdown · 2.0 KiB"


def test_marked_files_keep_partially_representable_targets_with_warm_counts() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "files"
    text = file_entry(
        "default:111111111111111111111111",
        label="Copy text",
        kind="file",
        path="/workspace/artifacts/copy.txt",
        source_path="/workspace/source/copy.txt",
        size_bytes=1024,
    )
    image = file_entry(
        "default:222222222222222222222222",
        label="Copy image",
        kind="image",
        path="/workspace/artifacts/copy.png",
        source_path=None,
        size_bytes=4096,
    )
    visible_order = (
        ArtifactEntryTarget(pane_id="files", parts=(image.id,)),
        ArtifactEntryTarget(pane_id="files", parts=(text.id,)),
    )
    app.files_pane = file_pane(
        (text, image),
        view_modes={text.id: "text", image.id: "image"},
        target_order=visible_order,
    )
    app._artifacts_marked_targets = {"files": set(visible_order)}

    context = build_copy_as_context(app)

    assert context is not None
    previews = {row.target: row.preview for row in context.rows}
    assert previews["contents"] == "1/2 marked · copyable contents"
    assert previews["source"] == "1/2 marked · source paths"
    assert previews["link"] == "2 marked · Markdown links"


@pytest.mark.parametrize(
    ("winner", "loser"),
    tuple(
        zip(
            (
                "snapshot",
                "reference",
                "handoff",
                "link",
                "json",
                "contents",
                "path",
                "source",
            ),
            (
                "reference",
                "handoff",
                "link",
                "json",
                "contents",
                "path",
                "source",
                "label",
            ),
            strict=True,
        )
    ),
)
def test_files_collision_winners_match_dispatch_precedence(
    winner: str,
    loser: str,
) -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "files"
    entry = file_entry(
        "default:0123456789abcdef01234567",
        label="Copy notes",
        kind="markdown",
        path="/workspace/artifacts/copy.md",
        source_path="/workspace/notes/copy.md",
        size_bytes=2048,
    )
    app.files_pane = file_pane(
        (entry,),
        view_modes={entry.id: "markdown"},
    )
    app._keymap_registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "copy_mode": {
                        "keys": {
                            "artifacts_other": {
                                winner: "x",
                                loser: "x",
                            }
                        }
                    }
                }
            }
        }
    )

    context = build_copy_as_context(app)

    assert context is not None
    assert next(row for row in context.rows if row.key == "x").target == winner
    assert loser not in {row.target for row in context.rows}


def test_commit_plan_target_is_filtered_when_warm_row_has_no_plan() -> None:
    app = PaletteHarness()
    app.commits_pane = commit_pane((commit_entry("a", subject="No linked plan"),))

    context = build_copy_as_context(app)

    assert context is not None
    assert "plan" not in {row.target for row in context.rows}


def test_marked_commit_context_uses_visible_order_and_plural_labels() -> None:
    app = PaletteHarness()
    first = commit_entry("a", subject="First visible")
    second = commit_entry("b", subject="Second visible")
    visible_order = (commit_target(second), commit_target(first))
    app.commits_pane = commit_pane(
        (first, second),
        target_order=visible_order,
    )
    app._artifacts_marked_targets = {"stitches": set(visible_order)}

    context = build_copy_as_context(app)

    assert context is not None
    assert context.subtitle == "2 marked stitches · SASE"
    sha = next(row for row in context.rows if row.target == "sha")
    message = next(row for row in context.rows if row.target == "message")
    assert sha.label == "commit SHAs"
    assert message.label == "commit messages"
    assert sha.preview == f"{'b' * 40} · +1"
    assert message.preview == "Second visible · +1"


def test_patch_context_filters_missing_pr_fields_and_uses_display_name() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "patches"
    patch = make_patch(name="copy_as_palette", cl=None)
    patch.project_display_name = "SASE"  # type: ignore[attr-defined]
    app.patches = [patch]

    context = build_copy_as_context(app)

    assert context is not None
    assert context.subtitle == "SASE · copy_as_palette"
    targets = {row.target for row in context.rows}
    assert "bug" not in targets
    assert "pr_number" not in targets
    assert "link" not in targets
    assert {"raw", "name", "spec", "snapshot"} <= targets


def test_duplicate_and_rebound_accelerators_follow_dispatch_precedence() -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = "patches"
    app.patches = [make_patch(name="copy_as_palette")]
    app._keymap_registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "copy_mode": {
                        "keys": {
                            "patches": {
                                "raw": "q",
                                "name": "q",
                                "spec": "j",
                                "snapshot": "k",
                            }
                        }
                    }
                }
            }
        }
    )

    context = build_copy_as_context(app)

    assert context is not None
    by_key = {row.key: row.target for row in context.rows}
    assert by_key["q"] == "raw"
    assert "name" not in {row.target for row in context.rows}
    assert by_key["j"] == "spec"
    assert by_key["k"] == "snapshot"


@pytest.mark.parametrize(
    ("tab", "warning"),
    [
        ("stitches", "No stitches entry to copy"),
        ("beads", "No beads entry to copy"),
        ("ref:plan", "No plans entry to copy"),
        ("files", "No files entry to copy"),
    ],
)
def test_empty_artifacts_context_warns(tab: str, warning: str) -> None:
    app = PaletteHarness()
    app.current_artifacts_subtab = tab

    assert build_copy_as_context(app) is None
    assert app.notifications == [(warning, "warning")]


def test_agent_and_axe_contexts_require_a_live_selection() -> None:
    app = PaletteHarness()
    app.current_tab = "agents"
    assert build_copy_as_context(app) is None
    assert app.notifications[-1] == ("No agent selected", "warning")

    app.current_tab = "axe"
    assert build_copy_as_context(app) is None
    assert app.notifications[-1] == ("No AXE item to copy", "warning")
