"""Behavior of the snippet trigger-name panel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Input, OptionList, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.snippet_name_modal import (
    SnippetNameModal,
    SnippetNameResult,
)
from sase.xprompt.snippet_targets import (
    SnippetConfigLocation,
    SnippetSaveTarget,
)


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("")


def _write_snippets(path: Path, snippets: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"ace": {"snippets": snippets}}),
        encoding="utf-8",
    )


def _location(
    path: Path,
    *,
    display: str | None = None,
    disabled_reason: str | None = None,
) -> SnippetConfigLocation:
    return SnippetConfigLocation(
        label=path.name,
        path=str(path),
        display_path=display or str(path),
        disabled_reason=disabled_reason,
    )


def _target(
    path: Path,
    *,
    display: str | None = None,
    fallback_reason: str | None = None,
) -> SnippetSaveTarget:
    return SnippetSaveTarget(
        read_path=path,
        write_path=path,
        apply_target=None,
        via_chezmoi=False,
        display_path=display or str(path),
        source="configured",
        fallback_reason=fallback_reason,
    )


def _static_plain(modal: SnippetNameModal, selector: str) -> str | None:
    try:
        return modal.query_one(selector, Static).render().plain
    except NoMatches:
        return None


def _verdict_plain(modal: SnippetNameModal) -> str | None:
    return _static_plain(modal, "#snippet-name-verdict")


def _destination_plain(modal: SnippetNameModal) -> str | None:
    return _static_plain(modal, "#snippet-name-destination")


def _matches_plain(modal: SnippetNameModal) -> str | None:
    try:
        matches = modal.query_one("#snippet-name-matches", OptionList)
    except NoMatches:
        return None
    return "\n".join(
        getattr(option.prompt, "plain", str(option.prompt))
        for option in matches.options
    )


def _contains(text: str | None, needle: str) -> bool:
    return text is not None and needle in text


async def _wait_for_modal(pilot: Any, app: _ModalApp) -> SnippetNameModal:
    def _ready() -> bool:
        screen = app.screen
        if not isinstance(screen, SnippetNameModal):
            return False
        try:
            screen.query_one("#snippet-name-verdict", Static)
        except NoMatches:
            return False
        return True

    await wait_for(pilot, _ready)
    modal = app.screen
    assert isinstance(modal, SnippetNameModal)
    return modal


async def test_invalid_trigger_enter_is_inert(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippets(config, {})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(config),
                [_location(config)],
                initial_trigger="bad-name",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot, lambda: _contains(_verdict_plain(modal), "Invalid trigger")
        )
        await pilot.press("enter")
        await wait_for(
            pilot, lambda: _contains(_verdict_plain(modal), "Invalid trigger")
        )
        assert results == []


async def test_new_trigger_returns_empty_starting_body(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippets(config, {})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(config), [_location(config)], initial_trigger="todo"
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(pilot, lambda: _contains(_verdict_plain(modal), "Create ⇥ todo"))
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert result is not None
    assert result.trigger == "todo"
    assert result.target.write_path == config
    assert result.exists is False
    assert result.existing_body is None


async def test_destination_collision_loads_own_template_off_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippets(config, {"todo": "TODO($1): $0"})
    results: list[SnippetNameResult | None] = []
    inside_to_thread = False
    loader_calls: list[bool] = []

    async def fake_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal inside_to_thread
        inside_to_thread = True
        try:
            return func(*args, **kwargs)
        finally:
            inside_to_thread = False

    def fake_load(path: str | Path, trigger: str) -> str:
        loader_calls.append(inside_to_thread)
        assert Path(path) == config
        assert trigger == "todo"
        return "TODO($1): $0"

    monkeypatch.setattr(
        "sase.ace.tui.modals.snippet_name_modal.asyncio.to_thread",
        fake_to_thread,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.snippet_name_modal.load_snippet_template",
        fake_load,
    )
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(config), [_location(config)], initial_trigger="todo"
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(pilot, lambda: _contains(_verdict_plain(modal), "exists here"))
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert result is not None
    assert result.exists is True
    assert result.existing_body == "TODO($1): $0"
    assert loader_calls and all(loader_calls)


async def test_elsewhere_collision_loads_other_template_but_keeps_destination(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "dest.yml"
    other = tmp_path / "other.yml"
    _write_snippets(dest, {})
    _write_snippets(other, {"todo": "from elsewhere"})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(dest),
                [_location(dest), _location(other)],
                initial_trigger="todo",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot,
            lambda: _contains(_verdict_plain(modal), "saving here will shadow it"),
        )
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert result is not None
    assert result.target.write_path == dest
    assert result.existing_body == "from elsewhere"
    assert result.derived_from is None


async def test_derived_only_collision_returns_composed_template(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippets(config, {})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(config),
                [_location(config)],
                derived_snippets={"todo": "derived $0"},
                derived_sources={"todo": "#project/todo"},
                initial_trigger="todo",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot,
            lambda: _contains(_verdict_plain(modal), "comes from #project/todo"),
        )
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert result is not None
    assert result.exists is True
    assert result.existing_body == "derived $0"
    assert result.derived_from == "#project/todo"


async def test_matches_filter_order_and_tab_completion(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippets(
        config,
        {
            "later": "later body",
            "todo": "TODO($1): $0",
            "todos": "- [ ] $1",
        },
    )
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(_target(config), [_location(config)], initial_trigger="to")
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(pilot, lambda: _contains(_matches_plain(modal), "todo"))
        rendered = _matches_plain(modal)
        assert rendered is not None
        assert "todo" in rendered
        assert "todos" in rendered
        assert "later" not in rendered
        await pilot.press("tab")
        await wait_for(
            pilot,
            lambda: modal.query_one("#snippet-name-trigger", Input).value == "todo",
        )


async def test_destination_line_renders_fallback_and_cycles_selectable_only(
    tmp_path: Path,
) -> None:
    default = tmp_path / "default.yml"
    disabled = tmp_path / "disabled.yml"
    override = tmp_path / "override.yml"
    _write_snippets(default, {})
    _write_snippets(disabled, {})
    _write_snippets(override, {})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(default, display="default.yml", fallback_reason="read-only"),
                [
                    _location(default, display="default.yml"),
                    _location(
                        disabled, display="disabled.yml", disabled_reason="locked"
                    ),
                    _location(override, display="override.yml"),
                ],
                initial_trigger="todo",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot,
            lambda: _contains(
                _destination_plain(modal), "configured path unusable: read-only"
            ),
        )
        await wait_for(pilot, lambda: _contains(_verdict_plain(modal), "Create ⇥ todo"))
        await pilot.press("down")
        await wait_for(
            pilot,
            lambda: _contains(_destination_plain(modal), "override.yml"),
        )
        assert not _contains(_destination_plain(modal), "disabled.yml")
        await wait_for(pilot, lambda: _contains(_verdict_plain(modal), "Create ⇥ todo"))
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert result is not None
    assert result.target.write_path == override


async def test_escape_returns_none(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippets(config, {})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(config), [_location(config)], initial_trigger="todo"
            ),
            results.append,
        )
        await _wait_for_modal(pilot, app)
        await pilot.press("escape")
        await wait_for(pilot, lambda: results == [None])
