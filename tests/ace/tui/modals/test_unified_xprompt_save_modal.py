"""Behavior of the one-screen xprompt/snippet save panel."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Input, Label, OptionList, Static

from sase.ace.tui.modals.unified_xprompt_save_modal import (
    UnifiedSaveLocation,
    UnifiedXPromptSaveModal,
    UnifiedXPromptSaveResult,
)
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("")


def _row(
    path: Path,
    *,
    names: frozenset[str] = frozenset(),
    location_type: str = "directory",
    label: str = "Test",
    precedence: int = 0,
    disabled_reason: str | None = None,
    namespace: str | None = None,
    is_skill_destination: bool = False,
    skill_project: str | None = None,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=XPromptLocation(label, str(path), location_type),  # type: ignore[arg-type]
        group="Config files" if location_type == "config" else "CWD directories",
        display_path=str(path),
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
        namespace=namespace,
        is_skill_destination=is_skill_destination,
        skill_project=skill_project,
    )


async def test_collision_requires_armed_second_enter(tmp_path: Path) -> None:
    directory = tmp_path / "xprompts"
    directory.mkdir()
    path = directory / "review.md"
    path.write_text("old definition", encoding="utf-8")
    results: list[UnifiedXPromptSaveResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 38)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory, names=frozenset({"review"}))],
                initial_name="review",
                body="new definition",
            ),
            results.append,
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        await pilot.press("enter")
        await pilot.pause()
        assert results == []
        assert modal._armed_identity is not None
        assert (
            "Press Enter again"
            in modal.query_one("#unified-save-verdict", Static).render().plain
        )
        modal._armed_at = 0.0
        await pilot.press("enter")
        await pilot.pause()

    result = results[0]
    assert result is not None
    assert result.exists
    assert result.path == str(path)
    assert result.target_format is SaveTargetFormat.MARKDOWN


async def test_arrow_navigation_keeps_name_focus_and_disarms(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    app = _ModalApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(first, names=frozenset({"review"})), _row(second)],
                initial_name="review",
                body="body",
            )
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        await pilot.press("enter")
        modal._armed_at = 0.0
        await pilot.press("down")
        await pilot.pause()
        assert modal._selected_location_path() == str(second)
        assert modal._armed_identity is None
        assert modal.query_one("#unified-save-name", Input).has_focus


async def test_invalid_name_enter_is_inert(tmp_path: Path) -> None:
    directory = tmp_path / "xprompts"
    directory.mkdir()
    results: list[UnifiedXPromptSaveResult | None] = []
    app = _ModalApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory)], initial_name="#bad name", body="body"
            ),
            results.append,
        )
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        assert (
            "Invalid name"
            in modal.query_one("#unified-save-verdict", Static).render().plain
        )
        assert results == []


async def test_description_and_typed_name_drive_exact_markdown_draft(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "xprompts"
    directory.mkdir()
    app = _ModalApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory)],
                initial_name="ns/foo",
                frontmatter=PromptFrontmatter(name="old", description="old desc"),
                body="review this",
            )
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        modal.query_one("#unified-save-description", Input).value = "new desc"
        await pilot.pause()
        row = modal._selected_row()
        assert row is not None
        assert modal._draft_text(row, "ns/foo") == (
            "---\nname: ns/foo\ndescription: new desc\n---\n\nreview this\n"
        )


async def test_ctrl_x_toggles_in_screen_snippet_mode(tmp_path: Path) -> None:
    directory = tmp_path / "xprompts"
    directory.mkdir()
    config = tmp_path / "sase.yml"
    config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    results: list[UnifiedXPromptSaveResult | None] = []
    app = _ModalApp()
    async with app.run_test(size=(105, 36)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory)],
                snippet_locations=[_row(config, location_type="config")],
                body="all panes",
                snippet_body="active pane",
                pane_count=3,
            ),
            results.append,
        )
        await pilot.pause()
        await pilot.press("ctrl+x", "r", "e", "v", "i", "e", "w", "enter")
        await pilot.pause()

    result = results[0]
    assert result is not None
    assert result.mode == "snippet"
    assert result.name == "review"
    assert result.path == str(config)


async def test_ctrl_x_wins_over_input_cut_and_works_from_every_field(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "xprompts"
    directory.mkdir()
    config = tmp_path / "sase.yml"
    config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    app = _ModalApp()

    async with app.run_test(size=(105, 36)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory)],
                snippet_locations=[_row(config, location_type="config")],
                initial_name="xprompt_name",
                frontmatter=PromptFrontmatter(description="keep this description"),
                body="all panes",
                snippet_body="active pane",
            )
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        name = modal.query_one("#unified-save-name", Input)
        description = modal.query_one("#unified-save-description", Input)

        # The base Input binds Ctrl+X to cut. The modal must intercept it first,
        # preserving selected text as the xprompt-mode name.
        name.select_all()
        await pilot.press("ctrl+x")
        assert modal._mode == "snippet"
        await pilot.press("s", "n", "i", "p")
        assert name.value == "snip"

        # Ctrl+T is retired only in this modal and must not change save mode.
        await pilot.press("ctrl+t")
        assert modal._mode == "snippet"
        assert name.value == "snip"

        await pilot.press("ctrl+x")
        assert modal._mode == "xprompt"
        assert name.value == "xprompt_name"

        # Description input selection is likewise preserved across the toggle.
        description.focus()
        description.select_all()
        await pilot.press("ctrl+x", "ctrl+x")
        assert modal._mode == "xprompt"
        assert description.value == "keep this description"

        # The same screen-level chord works when the destination list has focus.
        modal.query_one("#unified-save-locations", OptionList).focus()
        await pilot.press("ctrl+x")
        assert modal._mode == "snippet"
        assert name.value == "snip"


async def test_config_target_returns_entry_name(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("xprompts: {}\n", encoding="utf-8")
    results: list[UnifiedXPromptSaveResult | None] = []
    app = _ModalApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(config, location_type="config")],
                initial_name="review",
                body="body",
            ),
            results.append,
        )
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    result = results[0]
    assert result is not None
    assert result.target_format is SaveTargetFormat.CONFIG
    assert result.entry_name == "review"


async def test_project_local_target_preserves_full_typed_callable_name(
    tmp_path: Path,
) -> None:
    directory = tmp_path / ".xprompts"
    directory.mkdir()
    results: list[UnifiedXPromptSaveResult | None] = []
    app = _ModalApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory, namespace="project")],
                initial_name="project/ns/foo",
                frontmatter=PromptFrontmatter(name="stale"),
                body="body",
            ),
            results.append,
        )
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    result = results[0]
    assert result is not None
    assert result.name == "project/ns/foo"
    assert result.path == str(directory / "ns_foo.md")
    assert result.frontmatter.name == "ns/foo"


async def test_project_local_target_rejects_missing_namespace(tmp_path: Path) -> None:
    directory = tmp_path / ".xprompts"
    directory.mkdir()
    app = _ModalApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory, namespace="project")],
                initial_name="foo",
                body="body",
            )
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        assert (
            "must start with project/"
            in modal.query_one("#unified-save-verdict", Static).render().plain
        )


async def test_skill_destination_verdict_shows_both_names(tmp_path: Path) -> None:
    directory = tmp_path / "skills"
    directory.mkdir()
    app = _ModalApp()
    async with app.run_test(size=(110, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory, is_skill_destination=True)],
                initial_name="foo",
                frontmatter=PromptFrontmatter(skill=True),
                body="body",
            )
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        verdict = modal.query_one("#unified-save-verdict", Static).render().plain
        title = modal.query_one("#unified-save-title", Label).render().plain

    # The panel never implies a skill answers to ``#foo``.
    assert "#skills/foo · /foo" in verdict
    assert "Save draft as skill" in title


async def test_project_skill_destination_verdict_is_project_qualified(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "skills"
    directory.mkdir()
    app = _ModalApp()
    async with app.run_test(size=(110, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(directory, is_skill_destination=True, skill_project="app")],
                initial_name="foo",
                frontmatter=PromptFrontmatter(skill=True),
                body="body",
            )
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        verdict = modal.query_one("#unified-save-verdict", Static).render().plain

    assert "#app/skills/foo · /foo" in verdict


async def test_shadowed_destination_has_truthful_warning(tmp_path: Path) -> None:
    high = tmp_path / "high"
    low = tmp_path / "low"
    high.mkdir()
    low.mkdir()
    app = _ModalApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [
                    _row(high, names=frozenset({"review"}), precedence=0),
                    _row(low, precedence=10),
                ],
                initial_name="review",
                body="body",
                last_used={"xprompt": str(low)},
            )
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        verdict = modal.query_one("#unified-save-verdict", Static).render().plain
        assert "will be shadowed by" in verdict
        assert str(high) in verdict


async def test_no_writable_locations_state(tmp_path: Path) -> None:
    app = _ModalApp()
    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal(
                [_row(tmp_path, disabled_reason="read-only")],
                initial_name="review",
                body="body",
            )
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        assert (
            "No writable destinations"
            in modal.query_one("#unified-save-verdict", Static).render().plain
        )
