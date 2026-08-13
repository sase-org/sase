"""Copy-mode coverage for every non-PR Artifacts sub-tab."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, MagicMock

import pytest

from sase.ace.tui.actions.clipboard import _artifact_reference_resolution as _resolution
from sase.ace.tui.actions.clipboard._representations import (
    ArtifactReferenceSelection,
)
from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from sase.core.artifact_file_types import ArtifactFile
from tests.ace.tui._artifacts_copy_helpers import CopyHarness


def test_copy_mode_rejects_empty_artifacts_without_using_hidden_pr_state() -> None:
    app = CopyHarness()
    assert app.patches == []

    app.action_start_copy_mode()

    assert app._copy_mode_active is False
    assert app.copy_footer_updates == 0
    assert app.notifications == [("No stitches entry to copy", "warning")]
    assert app.artifacts_footer_restores == 0
    assert app.tab_footer_restores == 0


async def test_percent_rejects_empty_files_pane() -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "files"
        await page.expect_state("artifacts_subtab", "files")
        footer = page.query_one_widget("#keybinding-footer", KeybindingFooter)

        await page.press("%")

        assert page.app._copy_mode_active is False
        assert footer._last_layout_inputs is not None
        assert footer._last_layout_inputs[1] is None


@pytest.mark.parametrize("subtab", ["stitches", "ref:plan", "files"])
def test_each_artifacts_copy_menu_supports_snapshot_and_names_unknown_keys(
    subtab: str,
) -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = subtab

    assert app._handle_copy_key("s") is True
    assert app.snapshot_copies == 1
    assert app.artifacts_footer_restores == 1

    assert app._handle_copy_key("n") is False
    label = {"stitches": "Stitch", "ref:plan": "Plan", "files": "File"}[subtab]
    assert app.notifications[-1][0].startswith(f"Unknown copy key ({label}:")
    assert app.artifacts_footer_restores == 2


def test_document_percent_n_never_copies_a_patch_name() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "ref:plan"
    app.patches = [SimpleNamespace(name="hidden-pr")]
    app._copy_cl_name = MagicMock()  # type: ignore[method-assign]

    assert app._handle_copy_key("n") is False

    app._copy_cl_name.assert_not_called()
    assert "Plan:" in app.notifications[-1][0]


def test_files_percent_unknown_key_never_reaches_patch_dispatch() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "files"
    app.patches = [SimpleNamespace(name="hidden-pr")]
    app._copy_cl_name = MagicMock()  # type: ignore[method-assign]

    assert app._handle_copy_key("n") is False

    app._copy_cl_name.assert_not_called()
    assert "File:" in app.notifications[-1][0]


def _artifact_file(
    path: Path,
    *,
    artifact_id: str = "default:0123456789abcdef01234567",
    label: str = "copy target",
    kind: str = "file",
    source_path: str | None = None,
) -> ArtifactFile:
    return ArtifactFile(
        id=artifact_id,
        label=label,
        kind=kind,  # type: ignore[arg-type]
        path=str(path),
        source_path=source_path,
        project="sase",
    )


def _files_pane(*entries: ArtifactFile) -> SimpleNamespace:
    targets = tuple(("file", entry.id) for entry in entries)
    by_target = dict(zip(targets, entries, strict=True))
    selected = entries[0] if entries else None
    return SimpleNamespace(
        selected_entry=selected,
        selected_view_mode="text" if selected is not None else None,
        selected_entry_target=lambda: targets[0] if targets else None,
        entry_targets=lambda: targets,
        entries_for_targets=lambda requested: tuple(
            by_target[target] for target in requested if target in by_target
        ),
        project_scope="sase",
        project_file="/tmp/sase.sase",
        snapshot=SimpleNamespace(display_name="sase"),
    )


def test_files_copy_targets_cover_contents_paths_source_and_label(
    tmp_path: Path,
) -> None:
    stored = tmp_path / "stored.txt"
    stored.write_text("artifact contents", encoding="utf-8")
    source = tmp_path / "source.txt"
    source.write_text("source contents", encoding="utf-8")
    entry = _artifact_file(stored, source_path=str(source))
    app = CopyHarness()
    app.current_artifacts_subtab = "files"
    app.files_pane = _files_pane(entry)

    for key in ("percent_sign", "p", "o", "l"):
        assert app._handle_copy_key(key) is True

    assert [value for value, _message in app.copies] == [
        "artifact contents",
        str(stored),
        str(source),
        entry.label,
    ]


def test_files_marked_paths_preserve_visible_order(tmp_path: Path) -> None:
    first = _artifact_file(
        tmp_path / "first.txt",
        artifact_id="default:111111111111111111111111",
        label="first",
    )
    second = _artifact_file(
        tmp_path / "second.txt",
        artifact_id="default:222222222222222222222222",
        label="second",
    )
    app = CopyHarness()
    app.current_artifacts_subtab = "files"
    app.files_pane = _files_pane(first, second)
    app._artifacts_marked_targets = {"files": {("file", first.id), ("file", second.id)}}

    assert app._handle_copy_key("p") is True

    assert app.copies == [(f"{first.path}\n{second.path}", "Copied 2 stored paths")]


def test_files_binary_contents_refuse_with_kind_named_warning(
    tmp_path: Path,
) -> None:
    entry = _artifact_file(tmp_path / "image.png", kind="image")
    pane = _files_pane(entry)
    pane.selected_view_mode = "image"
    app = CopyHarness()
    app.current_artifacts_subtab = "files"
    app.files_pane = pane

    assert app._handle_copy_key("percent_sign") is True

    assert app.copies == []
    assert app.notifications[-1] == (
        "Cannot copy image contents; that artifact file is binary",
        "warning",
    )


def test_files_reference_resolution_is_context_free_and_serializes_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _artifact_file(tmp_path / "stored.txt")
    pane = _files_pane(entry)
    items = _resolution.reference_items_for_targets(
        "files",
        pane,
        (("file", entry.id),),
    )
    selection = ArtifactReferenceSelection(
        subtab="files",
        items=items,
        marked=False,
        prompt_project="sase",
        prompt_display_name="sase",
        prompt_project_file="/tmp/sase.sase",
    )
    context = MagicMock(side_effect=AssertionError("context should not be built"))
    monkeypatch.setattr(_resolution, "artifact_ref_context", context)

    resolved = _resolution.resolve_artifact_selection(
        selection,
        include_metadata=True,
    )

    context.assert_not_called()
    assert resolved.items[0].reference == f"file:{entry.id}"
    assert resolved.items[0].metadata is not None
    assert resolved.items[0].metadata["ref"] == f"file:{entry.id}"
    assert json.loads(json.dumps(resolved.items[0].metadata))["label"] == entry.label


@pytest.mark.parametrize("key", ["at", "exclamation_mark"])
def test_files_generic_reference_keys_degrade_safely_on_empty_scaffold(
    key: str,
) -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "files"

    assert app._handle_copy_key(key) is True

    assert app.notifications[-1] == ("No files entry selected", "warning")


def test_commits_copy_targets_use_the_visible_commit_and_terminal_plan_tag() -> None:
    app = CopyHarness()
    entry = SimpleNamespace(
        repo="sase",
        commit=SimpleNamespace(full_id="a" * 40),
    )
    message = (
        "Subject\n\nSASE_PLAN=plan:202607/old.md\nSASE_PLAN=plan:202607/current.md"
    )
    app.commits_pane = SimpleNamespace(
        _selected_entry=lambda: entry,
        _view_spec=lambda _entry: SimpleNamespace(message=message),
    )

    for key in ("percent_sign", "m", "r", "p"):
        assert app._handle_copy_key(key) is True

    assert [value for value, _message in app.copies] == [
        "a" * 40,
        message,
        f"sase@{'a' * 40}",
        "plan:202607/current.md",
    ]


def test_plans_copy_targets_use_the_selected_plan_payload() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "ref:plan"
    proposal = SimpleNamespace(
        plan_path="/tmp/plan.md",
        title="Copy all artifacts",
        body="# Copy all artifacts\n\nBody.",
    )
    row = SimpleNamespace(
        proposal=proposal,
        active=None,
        archive=None,
        bead_link=None,
    )
    app.plans_pane = SimpleNamespace(
        selected_row=lambda: row,
        selected_preview=lambda: None,
    )

    for key in ("p", "t", "b"):
        assert app._handle_copy_key(key) is True

    assert [value for value, _message in app.copies] == [
        proposal.plan_path,
        proposal.title,
        proposal.body,
    ]


def test_plans_owner_copy_targets_preserve_the_bead_link() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "ref:plan"
    bead_link = SimpleNamespace(
        bead_id="sase-b2",
        reference="plan:202607/bead_and_agent_artifact_refs.md",
    )
    row = SimpleNamespace(
        proposal=None,
        active=SimpleNamespace(
            document=SimpleNamespace(
                path="/tmp/plan.md",
                frontmatter={"title": "Artifact references"},
                body="Body",
            )
        ),
        archive=None,
        bead_link=bead_link,
    )
    app.plans_pane = SimpleNamespace(
        selected_row=lambda: row,
        selected_preview=lambda: None,
    )

    assert app._handle_copy_key("percent_sign") is True
    assert app._handle_copy_key("d") is True

    assert app.copies == [
        ("sase-b2", "Copied owning bead id"),
        (
            bead_link.reference,
            "Copied owning bead design reference",
        ),
    ]


def test_plans_design_copy_warns_when_selected_row_has_no_bead_design() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "ref:plan"
    row = SimpleNamespace(
        proposal=SimpleNamespace(
            plan_path="/tmp/proposal.md",
            title="Proposal",
            body="Body",
        ),
        active=None,
        archive=None,
        bead_link=None,
    )
    app.plans_pane = SimpleNamespace(
        selected_row=lambda: row,
        selected_preview=lambda: None,
    )

    assert app._handle_copy_key("d") is True

    assert app.copies == []
    assert app.notifications[-1] == (
        "The selected plan has no owning bead design reference",
        "warning",
    )


@pytest.mark.parametrize(
    ("subtab", "expected"),
    [
        (
            "stitches",
            [
                ("%", "SHA"),
                ("@", "@ref"),
                ("l", "link"),
                ("m", "message"),
                ("r", "repo@SHA"),
                ("p", "plan ref"),
                ("J", "JSON"),
                ("!", "agent + @ref"),
                ("s", "snap"),
            ],
        ),
        (
            "ref:plan",
            [
                ("%", "bead id"),
                ("@", "@ref"),
                ("l", "link"),
                ("d", "design"),
                ("p", "path"),
                ("t", "title"),
                ("b", "body"),
                ("J", "JSON"),
                ("!", "agent + @ref"),
                ("s", "snap"),
            ],
        ),
        (
            "files",
            [
                ("%", "contents"),
                ("@", "@ref"),
                ("L", "link"),
                ("p", "path"),
                ("o", "source"),
                ("l", "label"),
                ("j", "JSON"),
                ("!", "agent + @ref"),
                ("s", "snap"),
            ],
        ),
    ],
)
def test_copy_footer_uses_the_active_artifacts_subtab(
    subtab: str,
    expected: list[tuple[str, str]],
) -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))
    footer._update_display = MagicMock()  # type: ignore[method-assign]

    footer.update_copy_bindings("patches", artifacts_pane_key=subtab)

    footer._update_display.assert_called_once_with(expected, mode_label="COPY")


@pytest.mark.parametrize("subtab", ["stitches", "ref:plan", "files"])
def test_reference_keys_dispatch_uniformly_across_artifacts_subtabs(
    subtab: str,
) -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = subtab
    app._run_artifact_reference_action = MagicMock()  # type: ignore[method-assign]

    assert app._handle_copy_key("at") is True
    assert app._handle_copy_key("exclamation_mark") is True

    assert app._run_artifact_reference_action.call_args_list == [
        call(handoff=False),
        call(handoff=True),
    ]


@pytest.mark.parametrize(
    ("subtab", "link_key", "json_key"),
    [
        ("stitches", "l", "J"),
        ("ref:plan", "l", "J"),
        ("files", "L", "j"),
    ],
)
def test_link_and_json_keys_dispatch_uniformly_across_artifacts_subtabs(
    subtab: str,
    link_key: str,
    json_key: str,
) -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = subtab
    app._run_artifact_representation_action = MagicMock()  # type: ignore[method-assign]

    assert app._handle_copy_key(link_key) is True
    assert app._handle_copy_key(json_key) is True

    assert app._run_artifact_representation_action.call_args_list == [
        call("link"),
        call("json"),
    ]


def test_artifacts_footer_surfaces_only_a_nonzero_mark_count() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))
    footer._update_display = MagicMock()  # type: ignore[method-assign]

    footer.show_artifacts_pane(mark_count=3)

    footer._update_display.assert_called_once_with([("u", "unmark (3)")])
