"""Behavior of the mini-xprompt target name panel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals import mini_xprompt_name_modal as modal_mod
from sase.ace.tui.modals.mini_xprompt_name_modal import (
    MiniXPromptNameModal,
    MiniXPromptNameResult,
)
from sase.ace.tui.modals.mini_xprompt_target_catalog import (
    MiniXPromptDefinition,
    MiniXPromptTargetCatalog,
)
from sase.ace.tui.modals.unified_xprompt_save_modal import UnifiedSaveLocation
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
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
    group: str = "Project",
    precedence: int = 0,
    disabled_reason: str | None = None,
    namespace: str | None = None,
) -> UnifiedSaveLocation:
    return UnifiedSaveLocation(
        location=XPromptLocation(label, str(path), location_type),  # type: ignore[arg-type]
        group=group,
        display_path=str(path),
        names=names,
        precedence=precedence,
        disabled_reason=disabled_reason,
        namespace=namespace,
    )


def _definition(
    name: str,
    path: Path,
    *,
    compatibility: str = "editable",
    workflow_kind: str = "xprompt",
    effective: bool = True,
    location_path: str | None = None,
    precedence: int = 0,
    reason: str | None = None,
) -> MiniXPromptDefinition:
    return MiniXPromptDefinition(
        name=name,
        workflow_kind=workflow_kind,  # type: ignore[arg-type]
        source_path=str(path),
        display_path=str(path),
        storage_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        location_path=location_path or str(path.parent),
        precedence=precedence,
        compatibility=compatibility,  # type: ignore[arg-type]
        incompatible_reason=reason,
        effective=effective,
        read_path=str(path),
        write_path=str(path),
    )


async def _open_modal(
    modal: MiniXPromptNameModal,
    *,
    size: tuple[int, int] = (110, 30),
) -> tuple[_ModalApp, Any]:
    app = _ModalApp()
    pilot_cm = app.run_test(size=size)
    pilot = await pilot_cm.__aenter__()
    app.push_screen(modal)
    await pilot.pause(0.25)
    return app, (pilot_cm, pilot)


async def test_invalid_name_enter_is_inert(tmp_path: Path) -> None:
    row = _row(tmp_path / "xprompts")
    results: list[MiniXPromptNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniXPromptNameModal(
                MiniXPromptTargetCatalog(definitions=(), destinations=(row,)),
                initial_name="#bad name",
            ),
            results.append,
        )
        await pilot.pause(0.25)
        await pilot.press("enter")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, MiniXPromptNameModal)
        assert (
            "Invalid name"
            in modal.query_one("#mini-xprompt-name-verdict", Static).render().plain
        )
        assert results == []


async def test_new_name_returns_create_target(tmp_path: Path) -> None:
    row = _row(tmp_path / "xprompts")
    results: list[MiniXPromptNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniXPromptNameModal(
                MiniXPromptTargetCatalog(definitions=(), destinations=(row,)),
                initial_name="review",
            ),
            results.append,
        )
        await pilot.pause(0.25)
        modal = app.screen
        assert isinstance(modal, MiniXPromptNameModal)
        assert (
            "Create #review"
            in modal.query_one("#mini-xprompt-name-verdict", Static).render().plain
        )
        await pilot.press("enter")
        await pilot.pause()

    result = results[0]
    assert result is not None
    assert result.action == "create"
    assert result.destination.path == str(tmp_path / "xprompts" / "review.md")


async def test_exact_editable_match_returns_edit_action(tmp_path: Path) -> None:
    directory = tmp_path / "xprompts"
    row = _row(directory, names=frozenset({"review"}))
    definition = _definition("review", directory / "review.md")
    results: list[MiniXPromptNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniXPromptNameModal(
                MiniXPromptTargetCatalog(
                    definitions=(definition,),
                    destinations=(row,),
                ),
                initial_name="review",
            ),
            results.append,
        )
        await pilot.pause(0.25)
        await pilot.press("enter")
        await pilot.pause()

    result = results[0]
    assert result is not None
    assert result.action == "edit"
    assert result.definition == definition
    assert result.existing_definition == definition


async def test_read_only_match_returns_override_action(tmp_path: Path) -> None:
    readonly_dir = tmp_path / "readonly"
    writable_dir = tmp_path / "writable"
    readonly_row = _row(
        readonly_dir,
        names=frozenset({"review"}),
        disabled_reason="read-only",
        precedence=0,
    )
    writable_row = _row(writable_dir, precedence=1)
    definition = _definition(
        "review",
        readonly_dir / "review.md",
        compatibility="read_only",
        location_path=str(readonly_dir),
    )
    results: list[MiniXPromptNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniXPromptNameModal(
                MiniXPromptTargetCatalog(
                    definitions=(definition,),
                    destinations=(readonly_row, writable_row),
                ),
                initial_name="review",
            ),
            results.append,
        )
        await pilot.pause(0.25)
        modal = app.screen
        assert isinstance(modal, MiniXPromptNameModal)
        assert (
            str(writable_dir)
            in modal.query_one("#mini-xprompt-name-destination", Static).render().plain
        )
        await pilot.press("enter")
        await pilot.pause()

    result = results[0]
    assert result is not None
    assert result.action == "override"
    assert result.existing_definition == definition
    assert result.save_warning is not None


async def test_incompatible_exact_match_refuses_open(tmp_path: Path) -> None:
    row = _row(tmp_path / "xprompts")
    definition = _definition(
        "review",
        tmp_path / "workflow.yml",
        compatibility="incompatible",
        workflow_kind="workflow",
        reason="workflow graphs must be edited elsewhere",
    )
    results: list[MiniXPromptNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniXPromptNameModal(
                MiniXPromptTargetCatalog(
                    definitions=(definition,),
                    destinations=(row,),
                ),
                initial_name="review",
            ),
            results.append,
        )
        await pilot.pause(0.25)
        modal = app.screen
        assert isinstance(modal, MiniXPromptNameModal)
        assert (
            "Cannot open #review"
            in modal.query_one("#mini-xprompt-name-verdict", Static).render().plain
        )
        await pilot.press("enter")
        await pilot.pause()

    assert results == []


async def test_prefix_order_tab_completion_and_match_navigation_keep_input_focus(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row = _row(tmp_path / "xprompts")
    definitions = (
        _definition("review", tmp_path / "xprompts" / "review.md"),
        _definition("review_long", tmp_path / "xprompts" / "review_long.md"),
        _definition("revise", tmp_path / "xprompts" / "revise.md"),
    )

    def fail_read_text(self: Path, *args, **kwargs) -> str:  # type: ignore[no-untyped-def]
        raise AssertionError("modal navigation should not read files")

    app = _ModalApp()
    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniXPromptNameModal(
                MiniXPromptTargetCatalog(definitions=definitions, destinations=(row,)),
                initial_name="rev",
            )
        )
        await pilot.pause(0.25)
        monkeypatch.setattr(Path, "read_text", fail_read_text)
        modal = app.screen
        assert isinstance(modal, MiniXPromptNameModal)
        matches = modal.query_one("#mini-xprompt-name-matches", OptionList)
        rendered = "\n".join(
            getattr(option.prompt, "plain", str(option.prompt))
            for option in matches.options
        )
        assert "#review" in rendered
        assert "#review_long" in rendered
        input_field = modal.query_one("#mini-xprompt-name-input", Input)
        input_field.cursor_position = len(input_field.value)
        await pilot.press("down")
        await pilot.pause()
        assert input_field.has_focus
        assert input_field.cursor_position == len("rev")
        await pilot.press("tab")
        await pilot.pause()
        assert input_field.value == "review_long"


async def test_ctrl_n_cycles_destinations_without_stealing_focus(
    tmp_path: Path,
) -> None:
    first = _row(tmp_path / "first")
    second = _row(tmp_path / "second")
    app = _ModalApp()

    async with app.run_test(size=(110, 30)) as pilot:
        app.push_screen(
            MiniXPromptNameModal(
                MiniXPromptTargetCatalog(definitions=(), destinations=(first, second)),
                initial_name="review",
            )
        )
        await pilot.pause(0.25)
        modal = app.screen
        assert isinstance(modal, MiniXPromptNameModal)
        await pilot.press("ctrl+n")
        await pilot.pause(0.25)
        assert (
            str(tmp_path / "second")
            in modal.query_one("#mini-xprompt-name-destination", Static).render().plain
        )
        assert modal.query_one("#mini-xprompt-name-input", Input).has_focus


async def test_stale_async_analysis_is_not_cached(tmp_path: Path) -> None:
    row = _row(tmp_path / "xprompts")
    app, handles = await _open_modal(
        MiniXPromptNameModal(
            MiniXPromptTargetCatalog(definitions=(), destinations=(row,)),
            initial_name="review",
        )
    )
    pilot_cm, _pilot = handles
    try:
        modal = app.screen
        assert isinstance(modal, MiniXPromptNameModal)
        modal._analysis_cache.clear()
        modal.query_one("#mini-xprompt-name-input", Input).value = "fresh"
        await modal._load_analysis(("review", str(tmp_path / "xprompts")))
        assert ("review", str(tmp_path / "xprompts")) not in modal._analysis_cache
    finally:
        await pilot_cm.__aexit__(None, None, None)


def test_build_verdict_describes_shadowed_create(tmp_path: Path) -> None:
    high = _row(tmp_path / "high", names=frozenset({"review"}), precedence=0)
    low = _row(tmp_path / "low", precedence=10)
    target = modal_mod.destination_target_for_name(
        low,
        "review",
        destinations=(high, low),
    )

    verdict = modal_mod._build_mini_xprompt_verdict(
        "review",
        target,
        exact_definition=None,
        destination_definition=None,
    )

    assert verdict.action == "create"
    assert verdict.kind == "warning"
    assert "will be shadowed" in verdict.message
