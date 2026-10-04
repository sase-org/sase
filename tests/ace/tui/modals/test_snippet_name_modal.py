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
from sase.macro.snippet_bridge import MacroSnippetEntry
from sase.macro.snippet_targets import (
    SnippetConfigLocation,
    SnippetSaveTarget,
)
from sase.snippet.catalog import _build_snippet_catalog
from sase.snippet.models import (
    SnippetCatalog,
    SnippetCatalogContext,
    SnippetSourceContribution,
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


def _catalog_for(
    path: Path,
    snippets: dict[str, str],
    *,
    kind: str = "user",
    layer: str = "user",
    extra: list[SnippetSourceContribution] | None = None,
    macros: tuple[MacroSnippetEntry, ...] = (),
    extra_layers: tuple[tuple[str, str | None], ...] = (),
) -> SnippetCatalog:
    contributions = [
        SnippetSourceContribution(
            trigger=trigger,
            template=template,
            kind=kind,  # type: ignore[arg-type]
            path=str(path),
            display_path=str(path),
            writable=True,
            layer=layer,
        )
        for trigger, template in snippets.items()
    ]
    if extra:
        contributions.extend(extra)
    layer_names = (layer, *(name for name, _path in extra_layers))
    layer_paths: tuple[str | None, ...] = (
        str(path),
        *(p for _name, p in extra_layers),
    )
    return _build_snippet_catalog(
        SnippetCatalogContext(key=None, name=None, aliases=(), workspace_dir=None),
        macro_entries=macros,
        config_contributions=tuple(contributions),
        layer_paths=layer_paths,
        layer_names=layer_names,
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


async def test_unused_prefix_of_destination_match_creates_new_snippet(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippets(config, {"rchat": "Review chat transcript"})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(config),
                [_location(config)],
                catalog=_catalog_for(config, {"rchat": "Review chat transcript"}),
                initial_trigger="r",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(pilot, lambda: _contains(_matches_plain(modal), "rchat"))
        await wait_for(pilot, lambda: _contains(_verdict_plain(modal), "Create ⇥ r"))
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert result is not None
    assert result.trigger == "r"
    assert result.target.write_path == config
    assert result.exists is False
    assert result.existing_body is None


async def test_destination_collision_loads_own_template_from_catalog(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippets(config, {"todo": "TODO($1): $0"})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(config, display=str(config)),
                [_location(config)],
                catalog=_catalog_for(config, {"todo": "TODO($1): $0"}),
                initial_trigger="todo",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot, lambda: _contains(_verdict_plain(modal), "Edit ⇥ todo in place")
        )
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert result is not None
    assert result.exists is True
    assert result.existing_body == "TODO($1): $0"
    assert result.save_warning is None


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
                _target(dest, display=str(dest)),
                [_location(dest), _location(other)],
                catalog=_catalog_for(
                    dest,
                    {},
                    extra=[
                        SnippetSourceContribution(
                            trigger="todo",
                            template="from elsewhere",
                            kind="project",
                            path=str(other),
                            display_path=str(other),
                            writable=True,
                            layer="local",
                        )
                    ],
                    extra_layers=(("local", str(other)),),
                ),
                initial_trigger="todo",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot,
            lambda: _contains(_verdict_plain(modal), "won't take effect"),
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
                _target(config, display=str(config)),
                [_location(config)],
                catalog=_catalog_for(
                    config,
                    {},
                    macros=(
                        MacroSnippetEntry(
                            trigger="todo",
                            template="derived $0",
                            macro_name="project/todo",
                            source_path_display="xprompts/todo.md",
                        ),
                    ),
                ),
                initial_trigger="todo",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot,
            lambda: _contains(_verdict_plain(modal), "#project/todo (macro snippet)"),
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
            SnippetNameModal(
                _target(config),
                [_location(config)],
                catalog=_catalog_for(
                    config,
                    {
                        "later": "later body",
                        "todo": "TODO($1): $0",
                        "todos": "- [ ] $1",
                    },
                ),
                initial_trigger="to",
            )
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


async def test_destination_is_locked_and_arrows_move_matches(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "dest.yml"
    other = tmp_path / "other.yml"
    _write_snippets(dest, {"todo": "TODO($1): $0", "todos": "- [ ] $1"})
    _write_snippets(other, {})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(dest, display="dest.yml"),
                [
                    _location(dest, display="dest.yml"),
                    _location(other, display="other.yml"),
                ],
                catalog=_catalog_for(
                    dest,
                    {"todo": "TODO($1): $0", "todos": "- [ ] $1"},
                ),
                initial_trigger="to",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(pilot, lambda: _contains(_matches_plain(modal), "todos"))
        before = _destination_plain(modal)
        assert before is not None and "dest.yml" in before
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert _destination_plain(modal) == before
        assert not _contains(_destination_plain(modal), "other.yml")


async def test_destination_line_renders_fallback_note(tmp_path: Path) -> None:
    default = tmp_path / "default.yml"
    _write_snippets(default, {})
    app = _ModalApp()

    async with app.run_test(size=(110, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(default, display="default.yml", fallback_reason="read-only"),
                [_location(default, display="default.yml")],
                initial_trigger="todo",
            ),
            None,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot,
            lambda: _contains(
                _destination_plain(modal), "configured path unusable: read-only"
            ),
        )


async def test_shift_tab_requests_location_change(tmp_path: Path) -> None:
    from sase.ace.tui.modals.save_location_choices import ChangeSaveLocationRequest

    config = tmp_path / "sase.yml"
    _write_snippets(config, {})
    results: list[object] = []
    app = _ModalApp()

    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(config), [_location(config)], initial_trigger="tod"
            ),
            results.append,
        )
        await _wait_for_modal(pilot, app)
        await pilot.press("shift+tab")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert isinstance(result, ChangeSaveLocationRequest)
    assert result.text == "tod"


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


async def test_user_destination_warns_when_project_wins(tmp_path: Path) -> None:
    user = tmp_path / "user.yml"
    project = tmp_path / "project.yml"
    _write_snippets(user, {"todo": "user"})
    _write_snippets(project, {"todo": "project"})
    app = _ModalApp()

    async with app.run_test(size=(110, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(user, display="user.yml"),
                [_location(user, display="user.yml"), _location(project)],
                catalog=_catalog_for(
                    user,
                    {"todo": "user"},
                    extra=[
                        SnippetSourceContribution(
                            trigger="todo",
                            template="project",
                            kind="project",
                            path=str(project),
                            display_path=str(project),
                            writable=True,
                            layer="local",
                        )
                    ],
                    extra_layers=(("local", str(project)),),
                ),
                initial_trigger="todo",
            )
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot,
            lambda: _contains(_verdict_plain(modal), "edits here won't take effect"),
        )


async def test_project_destination_warns_it_will_override_user(
    tmp_path: Path,
) -> None:
    user = tmp_path / "user.yml"
    project = tmp_path / "project.yml"
    _write_snippets(user, {"todo": "user"})
    _write_snippets(project, {})
    results: list[SnippetNameResult | None] = []
    app = _ModalApp()

    async with app.run_test(size=(110, 28)) as pilot:
        app.push_screen(
            SnippetNameModal(
                _target(project, display="project.yml"),
                [_location(user), _location(project, display="project.yml")],
                catalog=_catalog_for(
                    user,
                    {"todo": "user"},
                    extra_layers=(("local", str(project)),),
                ),
                initial_trigger="todo",
            ),
            results.append,
        )
        modal = await _wait_for_modal(pilot, app)
        await wait_for(
            pilot,
            lambda: _contains(_verdict_plain(modal), "will override it"),
        )
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(results))

    result = results[0]
    assert result is not None
    assert result.existing_body == "user"
    assert result.save_warning is not None
    assert "will override it" in result.save_warning
