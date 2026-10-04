"""Existing-definition path for the snippet location-first flow."""

from __future__ import annotations

import threading
from pathlib import Path

from textual.widgets import Input

from sase.ace.testing import wait_for
from sase.ace.tui.modals import ConfirmActionModal
from sase.ace.tui.modals.existing_definition_finder_modal import (
    ExistingDefinitionFinderModal,
)
from sase.ace.tui.modals.save_location_choices import EXISTING_CHOICE_ID
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.macro.snippet_bridge import MacroSnippetEntry
from sase.snippet.catalog import _build_snippet_catalog
from sase.snippet.models import (
    SnippetCatalog,
    SnippetCatalogContext,
    SnippetSourceContribution,
)
from tests.ace.tui.actions.test_prompt_snippet_location_flow import (
    _SnippetFlowApp,
    _open_picker,
    _patches,
    _project_location,
    _target,
    _user_location,
    _wait_name_modal,
    _wait_snippet_tasks,
    _write_snippet_config,
)


def _contribution(
    trigger: str,
    template: str,
    *,
    kind: str,
    path: str | None,
    layer: str | None,
    writable: bool = True,
    macro_name: str | None = None,
) -> SnippetSourceContribution:
    return SnippetSourceContribution(
        trigger=trigger,
        template=template,
        kind=kind,  # type: ignore[arg-type]
        path=path,
        display_path=path,
        writable=writable,
        macro_name=macro_name,
        layer=layer,
    )


def _catalog(
    contributions: list[SnippetSourceContribution],
    *,
    layer_names: tuple[str, ...] = (),
    layer_paths: tuple[str | None, ...] = (),
    macros: tuple[MacroSnippetEntry, ...] = (),
) -> SnippetCatalog:
    return _build_snippet_catalog(
        SnippetCatalogContext(key=None, name="demo", aliases=(), workspace_dir=None),
        macro_entries=macros,
        config_contributions=contributions,
        layer_paths=layer_paths,
        layer_names=layer_names,
    )


async def _wait_finder(
    pilot: object, app: _SnippetFlowApp
) -> ExistingDefinitionFinderModal:
    await wait_for(pilot, lambda: isinstance(app.screen, ExistingDefinitionFinderModal))
    screen = app.screen
    assert isinstance(screen, ExistingDefinitionFinderModal)

    def _query_ready() -> bool:
        try:
            screen.query_one("#existing-finder-query", Input)
            return True
        except Exception:
            return False

    await wait_for(pilot, _query_ready)
    await wait_for(pilot, lambda: screen._selected_entry() is not None)
    return screen


async def _wait_snippet_pane(pilot: object, bar: PromptInputBar) -> None:
    await wait_for(pilot, lambda: bar._stack.snippet_item is not None)


async def test_existing_row_is_present_and_disabled_when_empty(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    app = _SnippetFlowApp("agent prompt")
    with _patches(target=_target(config), locations=[_user_location(config)]):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.disabled_reason == "no snippets yet"
            assert existing.is_default is False


async def test_existing_editable_opens_pane_with_loaded_body(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "user body"})
    catalog = _catalog(
        [
            _contribution(
                "todo", "user body", kind="user", path=str(config), layer="user"
            )
        ],
        layer_names=("user",),
        layer_paths=(str(config),),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        names={str(config): frozenset({"todo"})},
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.disabled_reason is None
            assert "1 snippets" in existing.badges
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await _wait_snippet_pane(pilot, bar)
            snippet = bar._stack.snippet_item
            assert snippet is not None
            assert snippet.snippet_target is not None
            assert bar.active_text() == "user body"
            assert snippet.snippet_target.trigger == "todo"
            assert snippet.snippet_target.save_warning is None


async def test_existing_shadowed_edit_carries_warning(tmp_path: Path) -> None:
    project = tmp_path / "sase" / "sase.yml"
    user = tmp_path / "user.yml"
    _write_snippet_config(project, {"todo": "project body"})
    _write_snippet_config(user, {"todo": "user body"})
    catalog = _catalog(
        [
            _contribution(
                "todo", "user body", kind="user", path=str(user), layer="user"
            ),
            _contribution(
                "todo",
                "project body",
                kind="project",
                path=str(project),
                layer="local",
            ),
        ],
        layer_names=("user", "local"),
        layer_paths=(str(user), str(project)),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(user),
        locations=[_project_location(project), _user_location(user)],
        names={
            str(project): frozenset({"todo"}),
            str(user): frozenset({"todo"}),
        },
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await _wait_snippet_tasks(app)
            await _wait_snippet_pane(pilot, bar)
            snippet = bar._stack.snippet_item
            assert snippet is not None
            assert snippet.snippet_target is not None
            assert bar.active_text() == "user body"
            assert snippet.snippet_target.save_warning is not None
            assert "shadowed" in snippet.snippet_target.save_warning


async def test_existing_read_only_override_picker_to_pane(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    catalog = _catalog(
        [
            _contribution(
                "todo",
                "built-in body",
                kind="default",
                path=None,
                layer="default",
                writable=False,
            )
        ],
        layer_names=("default", "user"),
        layer_paths=(None, str(config)),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        names={str(config): frozenset()},
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            assert picker._title.startswith("Override ⇥ todo")
            assert all(
                choice.choice_id != EXISTING_CHOICE_ID for choice in picker._choices
            )
            await pilot.press("h")
            modal = await _wait_name_modal(pilot, app)
            await pilot.pause()
            assert modal.query_one("#snippet-name-trigger", Input).value == "todo"
            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await _wait_snippet_pane(pilot, bar)
            assert "built-in body" in bar.active_text()
            snippet = bar._stack.snippet_item
            assert snippet is not None
            assert snippet.snippet_target is not None
            assert snippet.snippet_target.trigger == "todo"


async def test_existing_plugin_override_opens_name_step(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    catalog = _catalog(
        [
            _contribution(
                "help",
                "plugin template",
                kind="plugin",
                path=None,
                layer="plugin:sase_help",
                writable=False,
            )
        ],
        layer_names=("plugin:sase_help", "user"),
        layer_paths=(None, str(config)),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            assert "Override ⇥ help" in picker._title
            await pilot.press("h")
            await _wait_name_modal(pilot, app)
            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await _wait_snippet_pane(pilot, bar)
            assert bar.active_text() == "plugin template"


async def test_existing_macro_derived_override_opens_name_step(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    catalog = _catalog(
        [],
        macros=(
            MacroSnippetEntry(
                trigger="review",
                template="from #review",
                macro_name="review",
            ),
        ),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            assert "Override ⇥ review" in picker._title
            await pilot.press("h")
            await _wait_name_modal(pilot, app)
            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await _wait_snippet_pane(pilot, bar)
            assert "from #review" in bar.active_text()
            snippet = bar._stack.snippet_item
            assert snippet is not None
            assert snippet.snippet_target is not None
            assert snippet.snippet_target.derived_from == "#review"


async def test_existing_finder_back_remembers_query_and_cancel_refocuses(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "body"})
    catalog = _catalog(
        [_contribution("todo", "body", kind="user", path=str(config), layer="user")],
        layer_names=("user",),
        layer_paths=(str(config),),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            origin = bar.active_text_area()
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            finder = await _wait_finder(pilot, app)
            await pilot.press("t", "o")
            await pilot.pause()
            await pilot.press("shift+tab")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            assert picker.highlighted_id == EXISTING_CHOICE_ID
            await pilot.press("e")
            finder = await _wait_finder(pilot, app)
            assert finder.query_one("#existing-finder-query", Input).value == "to"
            await pilot.press("escape")
            await wait_for(
                pilot,
                lambda: not isinstance(app.screen, ExistingDefinitionFinderModal),
            )
            await pilot.pause()
            assert bar.active_text_area() is origin
            assert origin.has_focus


async def test_existing_typeahead_seeds_finder_query(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "body"})
    catalog = _catalog(
        [_contribution("todo", "body", kind="user", path=str(config), layer="user")],
        layer_names=("user",),
        layer_paths=(str(config),),
    )
    gate = threading.Event()
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        catalog=catalog,
        gate=gate,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "t")
            await _open_picker(pilot, app)
            await pilot.press("e", "t", "o", "d", "o")
            gate.set()
            finder = await _wait_finder(pilot, app)

            def _query_value() -> str | None:
                try:
                    return finder.query_one("#existing-finder-query", Input).value
                except Exception:
                    return None

            await wait_for(pilot, lambda: _query_value() == "todo")


async def test_existing_finder_origin_lost_warns(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "body"})
    catalog = _catalog(
        [_contribution("todo", "body", kind="user", path=str(config), layer="user")],
        layer_names=("user",),
        layer_paths=(str(config),),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            bar.snippet_target_origin_available = (  # type: ignore[method-assign]
                lambda pane_id: False
            )
            await pilot.press("enter")
            await wait_for(
                pilot,
                lambda: not isinstance(app.screen, ExistingDefinitionFinderModal),
            )
            assert (
                "Prompt pane is no longer available - snippet discarded",
                "warning",
            ) in app.notifications
            assert bar._stack.snippet_item is None


async def test_existing_same_target_focuses_and_notifies(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "loaded body"})
    catalog = _catalog(
        [
            _contribution(
                "todo", "loaded body", kind="user", path=str(config), layer="user"
            )
        ],
        layer_names=("user",),
        layer_paths=(str(config),),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        names={str(config): frozenset({"todo"})},
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await _wait_snippet_pane(pilot, bar)
            bar.active_text_area().text = "user draft"
            bar._sync_state_from_widgets()

            bar.request_snippet_target_pane()
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            existing = next(
                choice
                for choice in picker._choices
                if choice.choice_id == EXISTING_CHOICE_ID
            )
            assert existing.label.startswith("Switch to existing")
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await wait_for(
                pilot,
                lambda: any(
                    message == "Already editing ⇥ todo"
                    for message, _sev in app.notifications
                ),
            )
            assert bar.active_text() == "user draft"


async def test_existing_replaces_clean_open_pane(tmp_path: Path) -> None:
    first = tmp_path / "user.yml"
    second = tmp_path / "sase" / "sase.yml"
    _write_snippet_config(first, {"alpha": "first body"})
    _write_snippet_config(second, {"beta": "second body"})
    catalog = _catalog(
        [
            _contribution(
                "alpha", "first body", kind="user", path=str(first), layer="user"
            ),
            _contribution(
                "beta",
                "second body",
                kind="project",
                path=str(second),
                layer="local",
            ),
        ],
        layer_names=("user", "local"),
        layer_paths=(str(first), str(second)),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(first),
        locations=[_project_location(second), _user_location(first)],
        names={
            str(first): frozenset({"alpha"}),
            str(second): frozenset({"beta"}),
        },
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await _wait_snippet_pane(pilot, bar)
            assert "first body" in bar.active_text()
            restore = bar._snippet_focus_restore

            bar.request_snippet_target_pane()
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await _wait_snippet_tasks(app)
            await wait_for(pilot, lambda: "second body" in bar.active_text())
            snippet = bar._stack.snippet_item
            assert snippet is not None
            assert snippet.snippet_target is not None
            assert snippet.snippet_target.trigger == "beta"
            assert bar._snippet_focus_restore is restore
            assert bar.active_text_area()._vim_mode == "insert"


async def test_existing_dirty_open_pane_confirms_before_replace(
    tmp_path: Path,
) -> None:
    first = tmp_path / "user.yml"
    second = tmp_path / "sase" / "sase.yml"
    _write_snippet_config(first, {"alpha": "first body"})
    _write_snippet_config(second, {"beta": "second body"})
    catalog = _catalog(
        [
            _contribution(
                "alpha", "first body", kind="user", path=str(first), layer="user"
            ),
            _contribution(
                "beta",
                "second body",
                kind="project",
                path=str(second),
                layer="local",
            ),
        ],
        layer_names=("user", "local"),
        layer_paths=(str(first), str(second)),
    )
    app = _SnippetFlowApp("agent prompt")
    with _patches(
        target=_target(first),
        locations=[_project_location(second), _user_location(first)],
        names={
            str(first): frozenset({"alpha"}),
            str(second): frozenset({"beta"}),
        },
        catalog=catalog,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await _wait_snippet_pane(pilot, bar)
            bar.active_text_area().text = "dirty draft"
            bar._sync_state_from_widgets()
            assert bar._stack.snippet_is_dirty

            bar.request_snippet_target_pane()
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
            await pilot.press("n")
            await pilot.pause()
            assert bar.active_text() == "dirty draft"

            bar.request_snippet_target_pane()
            picker = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: picker.loaded is True)
            await pilot.press("e")
            await _wait_finder(pilot, app)
            await pilot.press("down", "enter")
            await wait_for(pilot, lambda: isinstance(app.screen, ConfirmActionModal))
            await pilot.press("y")
            await _wait_snippet_tasks(app)
            await wait_for(pilot, lambda: "second body" in bar.active_text())
