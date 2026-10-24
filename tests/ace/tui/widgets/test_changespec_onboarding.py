"""Tests for the Artifacts-tab onboarding widget."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui import artifact_tabs
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets.patch_onboarding import PatchOnboarding


def _section_plain(sections: dict[str, Text], selector: str) -> str:
    return sections[selector].plain


def test_patch_onboarding_content_includes_docs_lifecycle_and_storage() -> None:
    artifact_tabs.reset_artifacts_subtabs_cache()
    try:
        sections = PatchOnboarding.render_content(load_keymap_registry({}))
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()
    rendered = "\n".join(text.plain for text in sections.values())

    assert "Everything your agents produce, in one place" in rendered
    assert "Browse commits, patches, and beads in Artifacts" in rendered
    # The retired Agent pane drops out of the live strip by default.
    assert "Browse durable agent runs and open their artifacts." not in rendered
    assert "Trace committed work across projects." in rendered
    assert "Browse logical artifact files and their versions." not in rendered
    assert "https://sase.sh/concepts/work-units/" in rendered
    assert "https://sase.sh/concepts/landing/" in rendered
    assert "~/.sase/projects/" in rendered
    for status in ("WIP", "Draft", "Ready", "Mailed", "Submitted"):
        assert status in rendered


def test_patch_onboarding_uses_active_keymap_registry(
    files_pane_enabled: None,
) -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "show_help": "f1",
                    "prev_tab": "f2",
                    "cycle_artifacts_subtab_reverse": "f3",
                    "cycle_artifacts_subtab": "f4",
                    "pick_artifacts_project": "f5",
                },
            }
        }
    )

    artifact_tabs.reset_artifacts_subtabs_cache()
    try:
        sections = PatchOnboarding.render_content(registry)
    finally:
        artifact_tabs.reset_artifacts_subtabs_cache()
    tabs_text = _section_plain(sections, "#patch-onboarding-tabs")
    how_text = _section_plain(sections, "#patch-onboarding-how")
    learn_text = _section_plain(sections, "#patch-onboarding-learn")

    # The retired strip reads Commits first with no Agent row.
    assert "Agent" not in tabs_text
    positions = {
        label: tabs_text.index(label)
        for label in (
            "Commits",
            "Patches",
            "Beads",
            "Files",
        )
    }
    assert (
        positions["Commits"]
        < positions["Patches"]
        < positions["Beads"]
        < positions["Files"]
    )
    for key in ("f3", "f4", "f5"):
        assert key in tabs_text
    assert "cycle top-level views" in tabs_text
    assert "pick project scope" in tabs_text
    assert "f2" in how_text
    assert "shift+tab" not in how_text
    assert "f1" in learn_text
    assert "full keybinding reference" in learn_text


def test_patch_onboarding_queue_card_uses_active_keymap_registry() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "next_patch": "f1",
                    "prev_patch": "f2",
                    "show_diff": "f3",
                    "change_status": "f4",
                    "mail": "f5",
                    "edit_spec": "f6",
                    "edit_query": "f7",
                },
            }
        }
    )

    sections = PatchOnboarding.render_content(registry)
    queue_text = _section_plain(sections, "#patch-onboarding-queue")

    for key in ("f1", "f2", "f3", "f4", "f5", "f6", "f7"):
        assert key in queue_text
    assert "show the diff" in queue_text
    assert "change status" in queue_text
    assert "mail for review" in queue_text
    assert "open the spec in $EDITOR" in queue_text
    assert "filter with a query" in queue_text


def test_patch_onboarding_omits_modal_footer() -> None:
    registry = load_keymap_registry({})

    sections = PatchOnboarding.render_content(registry)

    assert "#patch-onboarding-footer" not in sections
