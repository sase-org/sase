"""Integration tests for the XPrompts tab ``Ctrl+I`` inline-load keymap.

The Admin Center XPrompts tab loads a non-YAML xprompt into the main prompt
input bar when explicit ``Ctrl+I`` is pressed on a loadable row. YAML-backed
rows -- workflow ``.yml`` files and config-backed xprompts -- are ineligible,
so the keymap is a no-op and the Admin Center stays open. Bare ``Tab`` always
switches the Admin Center's main tab. The expansion reuses
``expand_inline_xprompt`` and stages declared inputs into prompt frontmatter
for parity with the Select XPrompt ``Ctrl+I`` path.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from threading import Event

import pytest

from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.xprompt_browser_filter_input import BrowserFilterInput
from sase.ace.tui.modals.xprompt_browser_pane import XPromptBrowserPane
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.workflow_models import Workflow, WorkflowStep

from tests.ace.tui._plugins_browser_pane_helpers import _core_versions


def _md_xprompt(
    name: str,
    content: str,
    *,
    source_path: str,
    inputs: list[InputArg] | None = None,
) -> Workflow:
    """Build a simple prompt-part xprompt backed by *source_path*."""
    return Workflow(
        name=name,
        inputs=inputs or [],
        steps=[WorkflowStep(name="main", prompt_part=content)],
        source_path=source_path,
    )


def _patch_panes(monkeypatch: pytest.MonkeyPatch, prompts: dict[str, Workflow]) -> None:
    """Stub every Admin Center pane loader and seed the XPrompts tab."""
    config_result = cp._LoadResult(view=None, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: config_result)
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: dict(prompts),
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )
    plugins_result = pbp._PluginsLoadResult(
        catalog=None, error="stub", now=0.0, core_versions=_core_versions()
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: plugins_result)
    monkeypatch.setattr(pbp, "_collect_installed_core_versions", _core_versions)


async def _open_xprompts_tab(
    page: AcePage,
    monkeypatch: pytest.MonkeyPatch,
    prompts: dict[str, Workflow],
) -> tuple[ConfigCenterModal, XPromptBrowserPane]:
    """Open the Admin Center on the XPrompts tab with *prompts* seeded."""
    _patch_panes(monkeypatch, prompts)
    modal = ConfigCenterModal(initial_tab="xprompts")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#xprompts")))
    pane = modal.query_one("#xprompts", XPromptBrowserPane)
    await page.wait_for(lambda _s: pane._get_highlighted_item() is not None)
    return modal, pane


def _hint_text(pane: XPromptBrowserPane) -> str:
    """Return the current rendered hint line for the XPrompts pane."""
    return str(pane.query_one("#browser-hints", Static).render())


def test_xprompt_edit_and_forward_handlers_are_synchronous() -> None:
    assert not inspect.iscoroutinefunction(XPromptBrowserPane.action_edit_xprompt)
    assert not inspect.iscoroutinefunction(BrowserFilterInput.action_forward)


async def test_enter_returns_while_xprompt_file_read_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "slow.md"
    source.write_text("Slow definition body.", encoding="utf-8")
    prompts = {
        "slow": _md_xprompt(
            "slow",
            "Slow definition body.",
            source_path=str(source),
        )
    }
    started = Event()
    release = Event()
    original_read_text = Path.read_text

    def slow_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == source:
            started.set()
            release.wait()
        return original_read_text(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", slow_read_text)

    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        try:
            assert pane.action_edit_xprompt() is None
            assert await asyncio.wait_for(
                asyncio.to_thread(started.wait, 10.0), timeout=11.0
            )
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), timeout=2.0)
        finally:
            release.set()
            await page.wait_for(
                lambda _s: bool(page.app.query("#prompt-input-bar")),
                timeout=10.0,
            )

        await page.expect_no_modal()


async def test_ctrl_i_loads_non_yaml_xprompt_into_prompt_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = {"note": _md_xprompt("note", "Just a plain note.", source_path="n.md")}
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        assert pane.highlighted_row_is_loadable() is True
        # The conditional hint advertises ``^i: load`` for the loadable row.
        assert "^i: load" in _hint_text(pane)

        await page.press("ctrl+i")

        # The Admin Center closes and a prompt input bar opens with the body.
        await page.expect_no_modal()
        await page.wait_for(lambda _s: bool(page.app.query("#prompt-input-bar")))
        bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
        assert "Just a plain note." in bar.active_text()


async def test_enter_loads_raw_definition_and_binds_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "review.md"
    source.write_text(
        "---\ndescription: Review carefully\n---\n\nRaw {{ target }} body.\n",
        encoding="utf-8",
    )
    prompts = {
        "review": _md_xprompt(
            "review", "Raw {{ target }} body.", source_path=str(source)
        )
    }
    async with AcePage() as page:
        await _open_xprompts_tab(page, monkeypatch, prompts)
        await page.press("enter")

        await page.expect_no_modal()
        await page.wait_for(lambda _s: bool(page.app.query("#prompt-input-bar")))
        bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
        assert bar._stack.binding is not None
        assert bar._stack.binding.path == str(source)
        assert bar._stack.frontmatter_model.description == "Review carefully"
        assert "Raw {{ target }} body." in bar.active_text()


async def test_ctrl_i_stages_declared_inputs_into_frontmatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    who = InputArg(name="who", type=InputType.LINE)
    prompts = {
        "greet": _md_xprompt("greet", "Hi {{ who }}", source_path="g.md", inputs=[who])
    }
    async with AcePage() as page:
        await _open_xprompts_tab(page, monkeypatch, prompts)

        await page.press("ctrl+i")

        await page.expect_no_modal()
        await page.wait_for(lambda _s: bool(page.app.query("#prompt-input-bar")))
        bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
        # The placeholder body is preserved and the declared input is staged.
        assert "{{ who }}" in bar.active_text()
        model = PromptFrontmatter.parse(bar._stack.frontmatter)
        assert model.get_input("who") is not None


async def test_ctrl_i_is_inert_for_yaml_backed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A simple xprompt that lives inside the user's sase.yml (config-backed).
    prompts = {"cfg": _md_xprompt("cfg", "from config", source_path="config")}
    async with AcePage() as page:
        _modal, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        assert pane.highlighted_row_is_loadable() is False
        # The hint hides ``^i: load`` for an ineligible (YAML-backed) row.
        assert "^i: load" not in _hint_text(pane)

        await page.press("ctrl+i")
        await page.pause()

        # No prompt bar opens and the Admin Center stays in front.
        assert not page.app.query("#prompt-input-bar")
        await page.expect_modal("ConfigCenterModal")


async def test_tab_switches_admin_center_tab_on_eligible_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = {"note": _md_xprompt("note", "Body.", source_path="n.md")}
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)
        await page.wait_for(lambda _s: filter_input.has_focus)
        assert pane.highlighted_row_is_loadable() is True

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "config")

        assert not page.app.query("#prompt-input-bar")
        await page.expect_modal("ConfigCenterModal")
        assert page.app.current_tab == "changespecs"


async def test_shift_tab_switches_admin_center_tab_on_yaml_backed_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = {"cfg": _md_xprompt("cfg", "from config", source_path="config")}
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        assert pane.highlighted_row_is_loadable() is False

        await page.press("shift+tab")
        await page.wait_for(lambda _s: modal._active_tab == "updates")

        assert not page.app.query("#prompt-input-bar")
        await page.expect_modal("ConfigCenterModal")
        assert page.app.current_tab == "changespecs"


async def test_empty_filter_reserves_numeric_tab_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Activating XPrompts via its numbered tab key focuses an empty filter; a
    # following digit must jump tabs rather than be typed into the filter.
    prompts = {"note": _md_xprompt("note", "Body.", source_path="n.md")}
    async with AcePage() as page:
        _patch_panes(monkeypatch, prompts)
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")

        await page.press("6")
        await page.wait_for(lambda _s: modal._active_tab == "xprompts")
        pane = modal.query_one("#xprompts", XPromptBrowserPane)
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)
        await page.wait_for(lambda _s: filter_input.has_focus)

        await page.press("1")
        await page.wait_for(lambda _s: modal._active_tab == "config")
        assert filter_input.value == ""


async def test_empty_filter_swallows_reserved_numeric_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Out-of-range digits route through the modal's reserved no-op action, so
    # the active tab and the empty filter are both left untouched.
    prompts = {"note": _md_xprompt("note", "Body.", source_path="n.md")}
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)
        await page.wait_for(lambda _s: filter_input.has_focus)

        for digit in ("7", "9", "0"):
            await page.press(digit)
            await page.pause()

        assert modal._active_tab == "xprompts"
        assert filter_input.value == ""


async def test_digits_allowed_after_filter_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Once the filter holds text, digits fall through to normal Input editing.
    prompts = {"note": _md_xprompt("note", "Body.", source_path="n.md")}
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)
        await page.wait_for(lambda _s: filter_input.has_focus)

        await page.press("n")
        await page.press("1")
        await page.wait_for(lambda _s: filter_input.value == "n1")
        assert modal._active_tab == "xprompts"


async def test_brackets_are_ordinary_xprompt_filter_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = {"note": _md_xprompt("note", "Body.", source_path="n.md")}
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)
        await page.wait_for(lambda _s: filter_input.has_focus)

        await page.press("left_square_bracket", "right_square_bracket")
        await page.wait_for(lambda _s: filter_input.value == "[]")

        assert modal._active_tab == "xprompts"


async def test_tab_switches_main_tab_after_typed_filter_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = {"note": _md_xprompt("note", "Tab body.", source_path="n.md")}
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)
        await page.wait_for(lambda _s: filter_input.has_focus)
        assert pane.highlighted_row_is_loadable() is True

        await page.press("n")
        await page.wait_for(lambda _s: filter_input.value == "n")

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "config")

        assert not page.app.query("#prompt-input-bar")
        await page.expect_modal("ConfigCenterModal")
        assert filter_input.value == "n"
        assert page.app.current_tab == "changespecs"
