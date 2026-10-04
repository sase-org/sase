"""Location-first flow for snippet target panes."""

from __future__ import annotations

import asyncio
import threading
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import yaml
from textual.pilot import Pilot
from textual.widgets import Input, OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane import (
    PromptBarSnippetPaneMixin,
)
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
from sase.ace.tui.modals.snippet_name_modal import (
    SnippetNameModal,
    SnippetNameResult,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.macro.snippet_targets import SnippetConfigLocation, SnippetSaveTarget
from sase.snippet.catalog import _build_snippet_catalog
from sase.snippet.models import SnippetCatalogContext

from ._prompt_save_macro_helpers import _SaveFlowApp


class _SnippetFlowApp(PromptBarSnippetPaneMixin, _SaveFlowApp):
    """Save-flow app with the snippet location-first handler enabled."""


def _write_snippet_config(path: Path, snippets: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"ace": {"snippets": snippets}}),
        encoding="utf-8",
    )


def _user_location(path: Path) -> SnippetConfigLocation:
    return SnippetConfigLocation(
        label="User sase.yml",
        path=str(path),
        display_path=str(path),
    )


def _project_location(path: Path) -> SnippetConfigLocation:
    return SnippetConfigLocation(
        label="Project sase/sase.yml",
        path=str(path),
        display_path=str(path),
    )


def _target(
    path: Path,
    *,
    source: str = "default",
    fallback_reason: str | None = None,
) -> SnippetSaveTarget:
    return SnippetSaveTarget(
        read_path=path,
        write_path=path,
        apply_target=None,
        via_chezmoi=False,
        display_path=str(path),
        source=source,  # type: ignore[arg-type]
        fallback_reason=fallback_reason,
    )


def _patches(
    *,
    target: SnippetSaveTarget,
    locations: list[SnippetConfigLocation],
    last_used: str | None = None,
    names: dict[str, frozenset[str]] | None = None,
    gate: threading.Event | None = None,
) -> ExitStack:
    stack = ExitStack()
    base = "sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane"
    if gate is not None:
        stack.enter_context(
            patch(
                f"{base}._load_snippet_locations",
                side_effect=_slow_locations(gate, locations),
            )
        )
    else:
        stack.enter_context(
            patch(f"{base}._load_snippet_locations", return_value=locations)
        )
    stack.enter_context(patch(f"{base}._resolve_snippet_target", return_value=target))
    stack.enter_context(
        patch(
            f"{base}._load_snippet_catalog",
            return_value=_build_snippet_catalog(
                SnippetCatalogContext(
                    key=None, name=None, aliases=(), workspace_dir=None
                ),
                macro_entries=(),
                config_contributions=(),
            ),
        )
    )
    stack.enter_context(
        patch(f"{base}._load_snippet_last_used_path", return_value=last_used)
    )
    stack.enter_context(
        patch(
            f"{base}._load_snippet_names_by_path",
            return_value=dict(names or {}),
        )
    )
    return stack


def _slow_locations(
    gate: threading.Event, locations: list[SnippetConfigLocation]
) -> object:
    def _load(project: str | None) -> list[SnippetConfigLocation]:
        del project
        gate.wait(timeout=10)
        return locations

    return _load


async def _wait_snippet_tasks(harness: object) -> None:
    tasks = list(getattr(harness, "_snippet_pane_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def _open_picker(
    pilot: Pilot[None], app: _SnippetFlowApp
) -> SaveLocationPickerModal:
    await wait_for(
        pilot,
        lambda: isinstance(app.screen, SaveLocationPickerModal),
    )
    modal = app.screen
    assert isinstance(modal, SaveLocationPickerModal)
    return modal


async def _wait_name_modal(
    pilot: Pilot[None], app: _SnippetFlowApp
) -> SnippetNameModal:
    await wait_for(
        pilot,
        lambda: isinstance(app.screen, SnippetNameModal),
    )
    modal = app.screen
    assert isinstance(modal, SnippetNameModal)
    await wait_for(
        pilot,
        lambda: bool(modal.query("#snippet-name-trigger")),
    )
    return modal


async def test_gt_opens_picker_before_loaders_finish(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    target = _target(config)
    gate = threading.Event()
    app = _SnippetFlowApp("agent prompt")

    with _patches(target=target, locations=[_user_location(config)], gate=gate):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "t")
            modal = await _open_picker(pilot, app)
            assert modal.loaded is False
            gate.set()
            await wait_for(pilot, lambda: modal.loaded is True)


async def test_ctrl_g_ctrl_t_opens_picker_in_insert_mode(tmp_path: Path) -> None:
    """The ``^G`` prefix wins over INSERT-mode ``Ctrl+T`` completion."""
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    app = _SnippetFlowApp("agent prompt")

    with _patches(target=_target(config), locations=[_user_location(config)]):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            assert bar.active_text_area()._vim_mode == "insert"
            await pilot.press("ctrl+g", "ctrl+t")
            modal = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: modal.loaded is True)
            assert isinstance(app.screen, SaveLocationPickerModal)


async def test_configured_default_beats_last_used(tmp_path: Path) -> None:
    project = tmp_path / "sase" / "sase.yml"
    user = tmp_path / "user.yml"
    custom = tmp_path / "custom.yml"
    _write_snippet_config(project, {})
    _write_snippet_config(user, {"todo": "TODO($1): $0"})
    _write_snippet_config(custom, {})
    app = _SnippetFlowApp("agent prompt")

    with _patches(
        target=_target(custom, source="configured"),
        locations=[_project_location(project), _user_location(user)],
        last_used=str(user),
        names={str(custom): frozenset(), str(user): frozenset({"todo"})},
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "t")
            modal = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: modal.loaded is True)
            assert modal.highlighted_id == str(custom)
            await pilot.press("c")
            name_modal = await _wait_name_modal(pilot, app)
            assert str(name_modal._target.write_path) == str(custom)


async def test_fast_typeahead_becomes_trigger(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    gate = threading.Event()
    app = _SnippetFlowApp("agent prompt")

    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        names={str(config): frozenset()},
        gate=gate,
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "t")
            modal = await _open_picker(pilot, app)
            assert modal.loaded is False
            await pilot.press("h", "t", "o", "d", "o")
            gate.set()
            name_modal = await _wait_name_modal(pilot, app)
            field = name_modal.query_one("#snippet-name-trigger", Input)
            assert field.value == "todo"


async def test_shift_tab_round_trip_preserves_trigger(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "TODO($1): $0"})
    app = _SnippetFlowApp("agent prompt")

    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        names={str(config): frozenset({"todo"})},
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "t")
            modal = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: modal.loaded is True)
            await pilot.press("h")
            name_modal = await _wait_name_modal(pilot, app)
            field = name_modal.query_one("#snippet-name-trigger", Input)
            field.value = "todo"
            await pilot.pause()
            await pilot.press("shift+tab")
            reopened = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: reopened.loaded is True)
            assert reopened.highlighted_id == str(config)
            option_list = reopened.query_one("#save-location-picker-list", OptionList)
            rendered = "\n".join(
                getattr(option.prompt, "plain", str(option.prompt))
                for option in option_list.options
            )
            assert "has ⇥ todo" in rendered
            await pilot.press("h")
            again = await _wait_name_modal(pilot, app)
            assert again.query_one("#snippet-name-trigger", Input).value == "todo"


async def test_rename_defaults_to_current_location(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    target = _target(config)
    app = _SnippetFlowApp("agent prompt")

    with _patches(target=target, locations=[_user_location(config)]):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            assert bar.open_snippet_target_pane(
                SnippetNameResult(
                    trigger="todo",
                    target=target,
                    exists=False,
                    existing_body=None,
                    derived_from=None,
                ),
                origin_pane_id=bar.active_text_area().id or "",
                destination_exists=False,
                loaded_fingerprint=None,
            )
            await pilot.pause()
            await pilot.press("escape")
            await pilot.press("g", "t")
            modal = await _open_picker(pilot, app)
            await wait_for(pilot, lambda: modal.loaded is True)
            assert modal.highlighted_id == str(config)


async def test_escape_in_picker_restores_origin(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    app = _SnippetFlowApp("agent prompt")

    with _patches(target=_target(config), locations=[_user_location(config)]):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            await _open_picker(pilot, app)
            await pilot.press("escape")
            await wait_for(
                pilot,
                lambda: not isinstance(app.screen, SaveLocationPickerModal),
            )
            assert bar.active_text_area().has_focus


async def test_origin_vanished_closes_picker_with_warning(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    gate = threading.Event()
    app = _SnippetFlowApp("agent prompt")

    with _patches(
        target=_target(config), locations=[_user_location(config)], gate=gate
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            await pilot.press("g", "t")
            await _open_picker(pilot, app)
            bar.snippet_target_origin_available = (  # type: ignore[method-assign]
                lambda pane_id: False
            )
            gate.set()
            await _wait_snippet_tasks(app)
            await wait_for(
                pilot,
                lambda: not isinstance(app.screen, SaveLocationPickerModal),
            )
            assert any(
                "no longer available" in message
                for message, _severity in app.notifications
            )


async def test_origin_lost_during_choice_build_closes_picker(tmp_path: Path) -> None:
    """Origin loss inside the off-thread choice build must not orphan a picker."""
    import sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane as pane_mod

    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    gate = threading.Event()
    entered = threading.Event()
    real_build = pane_mod._build_snippet_picker_tables

    def _gated_build(*args: object, **kwargs: object) -> object:
        entered.set()
        assert gate.wait(timeout=10)
        return real_build(*args, **kwargs)  # type: ignore[arg-type]

    app = _SnippetFlowApp("agent prompt")
    base = "sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane"
    with _patches(target=_target(config), locations=[_user_location(config)]):
        with patch(f"{base}._build_snippet_picker_tables", side_effect=_gated_build):
            async with app.run_test(size=(110, 34)) as pilot:
                await pilot.pause()
                bar = app.query_one(PromptInputBar)
                await pilot.press("escape")
                await pilot.press("g", "t")
                await _open_picker(pilot, app)
                await wait_for(pilot, lambda: entered.is_set())
                bar.snippet_target_origin_available = (  # type: ignore[method-assign]
                    lambda pane_id: False
                )
                gate.set()
                await _wait_snippet_tasks(app)
                await wait_for(
                    pilot,
                    lambda: not isinstance(app.screen, SaveLocationPickerModal),
                )
                assert not isinstance(app.screen, SnippetNameModal)
                warnings = [
                    message
                    for message, _severity in app.notifications
                    if "no longer available" in message
                ]
                assert len(warnings) == 1


async def test_shift_tab_reload_error_shows_error(tmp_path: Path) -> None:
    """A Shift+Tab rebuild failure must surface, not hang on loading."""
    import sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane as pane_mod

    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "TODO($1): $0"})
    real_build = pane_mod._build_snippet_picker_tables
    calls = 0

    def _fail_on_reload(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("reload boom")
        return real_build(*args, **kwargs)  # type: ignore[arg-type]

    app = _SnippetFlowApp("agent prompt")
    base = "sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane"
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        names={str(config): frozenset({"todo"})},
    ):
        with patch(f"{base}._build_snippet_picker_tables", side_effect=_fail_on_reload):
            async with app.run_test(size=(110, 34)) as pilot:
                await pilot.pause()
                await pilot.press("escape")
                await pilot.press("g", "t")
                modal = await _open_picker(pilot, app)
                await wait_for(pilot, lambda: modal.loaded is True)
                await pilot.press("h")
                name_modal = await _wait_name_modal(pilot, app)
                name_modal.query_one("#snippet-name-trigger", Input).value = "todo"
                await pilot.pause()
                await pilot.press("shift+tab")
                reopened = await _open_picker(pilot, app)
                await wait_for(
                    pilot,
                    lambda: reopened._load_error is not None,
                )
                assert isinstance(app.screen, SaveLocationPickerModal)
                assert not isinstance(app.screen, SnippetNameModal)
                assert "reload boom" in (reopened._load_error or "")
                assert any(
                    "Failed to prepare snippet pane" in message
                    for message, _severity in app.notifications
                )


async def test_shift_tab_origin_lost_closes_picker(tmp_path: Path) -> None:
    """Origin loss during a Shift+Tab rebuild closes the picker with a warning."""
    import sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane as pane_mod

    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "TODO($1): $0"})
    real_build = pane_mod._build_snippet_picker_tables
    gate = threading.Event()
    entered = threading.Event()
    calls = 0

    def _gate_reload(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls > 1:
            entered.set()
            assert gate.wait(timeout=10)
        return real_build(*args, **kwargs)  # type: ignore[arg-type]

    app = _SnippetFlowApp("agent prompt")
    base = "sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane"
    with _patches(
        target=_target(config),
        locations=[_user_location(config)],
        names={str(config): frozenset({"todo"})},
    ):
        with patch(f"{base}._build_snippet_picker_tables", side_effect=_gate_reload):
            async with app.run_test(size=(110, 34)) as pilot:
                await pilot.pause()
                bar = app.query_one(PromptInputBar)
                await pilot.press("escape")
                await pilot.press("g", "t")
                modal = await _open_picker(pilot, app)
                await wait_for(pilot, lambda: modal.loaded is True)
                await pilot.press("h")
                name_modal = await _wait_name_modal(pilot, app)
                name_modal.query_one("#snippet-name-trigger", Input).value = "todo"
                await pilot.pause()
                await pilot.press("shift+tab")
                await _open_picker(pilot, app)
                await wait_for(pilot, lambda: entered.is_set())
                bar.snippet_target_origin_available = (  # type: ignore[method-assign]
                    lambda pane_id: False
                )
                gate.set()
                await _wait_snippet_tasks(app)
                await wait_for(
                    pilot,
                    lambda: not isinstance(app.screen, SaveLocationPickerModal),
                )
                assert not isinstance(app.screen, SnippetNameModal)
                warnings = [
                    message
                    for message, _severity in app.notifications
                    if "no longer available" in message
                ]
                assert len(warnings) == 1
