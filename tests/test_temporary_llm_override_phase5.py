"""Phase 5 tests: end-to-end coverage and hardening for the temporary LLM override.

Phase 1–2 cover the shared state primitive and the provider/metadata wiring;
Phase 3 covers the modal helpers and basic pilot flows.  This module fills
the gaps Phase 5 calls out:

- keymap / footer / help-modal cross-source sync,
- full Textual pilot flows for set / change / clear / cancel,
- model picker reuse from the override caller,
- agent metadata integration across the launch paths that consume
  ``resolve_effective_default_provider_model()``.
"""

from __future__ import annotations

import json
import os
from typing import cast
from unittest.mock import MagicMock

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList

from sase.ace.tui.keymaps import KeymapRegistry, load_keymap_registry
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
)
from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    ModelPickerModal,
    _build_model_options,
)
from sase.ace.tui.modals.temporary_llm_override_modal import (
    TemporaryLLMOverrideModal,
    TemporaryOverrideResult,
    _DurationPickerModal,
)
from sase.ace.tui.widgets import KeybindingFooter
from sase.llm_provider.temporary_override import (
    clear_temporary_override,
    get_active_temporary_override,
    set_temporary_override,
)


def _full_registry(extra_ace_cfg: dict | None = None) -> KeymapRegistry:
    """Build a registry from the bundled YAML, like the production AceApp does.

    ``load_keymap_registry({})`` only consults the typed mode defaults and
    skips the YAML overrides — not how the app actually boots.  The help
    modal and footer in production receive the merged config, which is
    why we mirror that here.
    """
    import importlib.resources

    import yaml  # type: ignore[import-untyped]

    text = (
        importlib.resources.files("sase")
        .joinpath("default_config.yml")
        .read_text(encoding="utf-8")
    )
    data = yaml.safe_load(text)
    ace_cfg = data["ace"]
    if extra_ace_cfg:
        # Shallow merge under "keymaps" only — enough for our overrides.
        for top, val in extra_ace_cfg.items():
            base = ace_cfg.get(top, {})
            if isinstance(base, dict) and isinstance(val, dict):
                merged = dict(base)
                for k, v in val.items():
                    if (
                        k in merged
                        and isinstance(merged[k], dict)
                        and isinstance(v, dict)
                    ):
                        merged[k] = {**merged[k], **v}
                    else:
                        merged[k] = v
                ace_cfg[top] = merged
            else:
                ace_cfg[top] = val
    return load_keymap_registry(ace_cfg)


# ---------------------------------------------------------------------------
# Test app for pilot tests
# ---------------------------------------------------------------------------


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


# ---------------------------------------------------------------------------
# Cross-source keymap / footer / help sync
# ---------------------------------------------------------------------------


def _flatten_help_keys(sections: list[tuple[str, list[tuple[str, str]]]]) -> set[str]:
    """Collect (key, label) pairs across all sections of a help spec."""
    out: set[str] = set()
    for _, rows in sections:
        for key, label in rows:
            out.add(f"{key}|{label}")
    return out


@pytest.mark.parametrize(
    "build_sections",
    [cls_bindings, agents_bindings],
)
def test_help_modal_includes_temporary_override_on_main_tabs(
    build_sections,
) -> None:
    """``,P`` "Temporary model override" appears in the changespecs and
    agents help-modal sections (the two tabs that show leader-mode
    bindings)."""
    reg = _full_registry()
    sections = build_sections(reg)
    flat = _flatten_help_keys(sections)
    assert ",P|Temporary model override" in flat


def test_help_modal_axe_tab_includes_temporary_override() -> None:
    """The axe tab also surfaces ``,P`` in its leader-mode block."""
    reg = _full_registry()
    sections = axe_bindings(reg)
    flat = _flatten_help_keys(sections)
    assert ",P|Temporary model override" in flat


def test_help_modal_keybinding_uses_configured_leader_prefix() -> None:
    """When the leader prefix is overridden, the help text reflects it."""
    reg = _full_registry(
        {"keymaps": {"modes": {"leader_mode": {"prefix": "semicolon"}}}}
    )
    sections = cls_bindings(reg)
    flat = _flatten_help_keys(sections)
    assert ";P|Temporary model override" in flat


def test_help_modal_keybinding_uses_configured_temporary_key() -> None:
    """When the chord key is overridden, the help text reflects it."""
    reg = _full_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {"keys": {"temporary_llm_override": "T"}},
                },
            },
        }
    )
    sections = cls_bindings(reg)
    flat = _flatten_help_keys(sections)
    assert ",T|Temporary model override" in flat


def test_footer_leader_bindings_include_temporary_override() -> None:
    """``update_leader_bindings`` puts ``P temporary model`` in the footer."""
    footer = KeybindingFooter()
    captured: list[object] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda text: captured.append(text)
    )

    footer.update_leader_bindings(current_tab="changespecs")

    assert captured, "footer never updated"
    rendered = str(captured[-1])
    assert "P" in rendered
    assert "temporary model" in rendered


@pytest.mark.parametrize("tab", ["changespecs", "agents", "axe"])
def test_footer_leader_bindings_present_on_every_tab(tab: str) -> None:
    """The leader chord is universally available — every tab's footer
    surfaces it once leader mode is engaged."""
    footer = KeybindingFooter()
    captured: list[object] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda text: captured.append(text)
    )

    footer.update_leader_bindings(current_tab=tab)

    rendered = str(captured[-1])
    assert "temporary model" in rendered


# ---------------------------------------------------------------------------
# Modal — model picker reuse
# ---------------------------------------------------------------------------


def test_override_modal_picker_options_omit_same_as_planner() -> None:
    """The option list built for the override flow does not include the
    ``__default__`` (Same as planner) option id."""
    items = _build_model_options(include_default_option=False)
    ids = {opt.id for opt in items if opt is not None}
    assert "__default__" not in ids
    # Custom… still present so the freeform path remains reachable.
    assert CUSTOM_SENTINEL in ids


def test_override_modal_picker_options_include_known_models() -> None:
    """Even without the default option, common models are still listed."""
    items = _build_model_options(include_default_option=False)
    ids = {opt.id for opt in items if opt is not None}
    assert "opus" in ids
    assert "o3" in ids


# ---------------------------------------------------------------------------
# Modal — pilot flows
# ---------------------------------------------------------------------------


async def test_top_modal_q_cancels_when_inactive() -> None:
    """Pressing ``q`` from the inactive state dismisses with cancelled."""
    result: TemporaryOverrideResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(TemporaryLLMOverrideModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()

    assert result is not None
    assert result.action == "cancelled"


async def test_top_modal_x_with_no_active_dismisses_cancelled() -> None:
    """Pressing ``x`` with no active override dismisses without writing
    state — the action is a no-op rather than an error."""
    assert get_active_temporary_override() is None
    result: TemporaryOverrideResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(TemporaryLLMOverrideModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()

    assert result is not None
    assert result.action == "cancelled"
    assert get_active_temporary_override() is None


async def test_top_modal_s_pushes_model_picker_when_inactive() -> None:
    """Pressing ``s`` from the inactive state pushes the model picker."""
    async with _TestApp().run_test() as pilot:
        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()

        # Top of the screen stack is now the model picker.
        top = pilot.app.screen
        assert isinstance(top, ModelPickerModal)
        assert top._include_default_option is False


async def test_top_modal_c_pushes_model_picker_when_active() -> None:
    """Pressing ``c`` (Change override) from the active state pushes
    the model picker — same as the inactive ``s`` flow."""
    set_temporary_override("codex/o3", 3600.0, source="test")
    async with _TestApp().run_test() as pilot:
        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        top = pilot.app.screen
        assert isinstance(top, ModelPickerModal)


async def test_full_set_flow_writes_state_and_dismisses_with_set() -> None:
    """Full E2E: open modal → press s → pick a known model → preset
    duration → state written, modal dismissed with ``"set"``."""
    assert get_active_temporary_override() is None
    result: TemporaryOverrideResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Open model picker.
        await pilot.press("s")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        option_list = picker.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("o3")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # Duration picker is now on top — choose 1h preset.
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        await pilot.press("3")
        await pilot.pause()

    assert result is not None
    assert result.action == "set"
    assert result.override is not None
    assert result.override.provider == "codex"
    assert result.override.model == "o3"

    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"
    assert fetched.expires_at is not None


async def test_full_change_flow_overwrites_existing_state() -> None:
    """When an override is already active, the change flow replaces it."""
    set_temporary_override("opus", 60.0, source="seed")
    result: TemporaryOverrideResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        option_list = picker.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("o3")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # ``Until cleared`` (preset 6) — exercises the no-expiry branch.
        await pilot.press("6")
        await pilot.pause()

    assert result is not None
    assert result.action == "set"
    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"
    assert fetched.expires_at is None


async def test_set_flow_picker_cancel_keeps_modal_open() -> None:
    """Cancelling the model picker leaves the override modal open and
    the existing state untouched."""
    async with _TestApp().run_test() as pilot:
        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)

        # Cancel the picker — overlay should pop, override modal should
        # remain on top.
        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(pilot.app.screen, TemporaryLLMOverrideModal)
        assert get_active_temporary_override() is None

        # Tear down cleanly.
        await pilot.press("escape")
        await pilot.pause()


# ---------------------------------------------------------------------------
# Duration picker — custom input validation
# ---------------------------------------------------------------------------


async def test_duration_modal_invalid_custom_shows_error_keeps_open() -> None:
    """An invalid custom duration surfaces an error label and does not
    dismiss the modal."""
    dismissed: list[object] = []

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            dismissed.append(value)

        pilot.app.push_screen(_DurationPickerModal(), callback=on_dismiss)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        custom_input = pilot.app.screen.query_one(
            "#override-duration-custom-input", Input
        )
        custom_input.value = "not-a-duration"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        # Still open — no dismissal.
        assert dismissed == []
        # Error label is no longer hidden.
        from textual.widgets import Label

        error = pilot.app.screen.query_one("#override-duration-custom-error", Label)
        assert not error.has_class("hidden")


async def test_duration_modal_valid_custom_dismisses_with_seconds() -> None:
    """A valid custom duration dismisses with the parsed seconds."""
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_DurationPickerModal(), callback=on_dismiss)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        custom_input = pilot.app.screen.query_one(
            "#override-duration-custom-input", Input
        )
        custom_input.value = "1h30m"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert result == 5400.0


# ---------------------------------------------------------------------------
# Active-state rendering
# ---------------------------------------------------------------------------


def test_render_state_line_until_cleared_shows_no_expiry() -> None:
    """An override with no expiry renders ``no expiry`` rather than a
    countdown."""
    set_temporary_override("opus", None, source="test")
    modal = TemporaryLLMOverrideModal()
    line = modal._render_state_line()
    assert "Active" in line
    assert "no expiry" in line


def test_render_state_line_inactive_uses_resolved_default() -> None:
    """Without any override active, the modal shows the *resolved*
    default — i.e. provider+model, not just provider."""
    assert get_active_temporary_override() is None
    modal = TemporaryLLMOverrideModal()
    line = modal._render_state_line()
    assert "Default" in line
    # format_provider_model_label produces "PROVIDER(model)"; the
    # parentheses are the giveaway that we resolved the model too.
    assert "(" in line and ")" in line


# ---------------------------------------------------------------------------
# Agent metadata integration — running agents are unaffected by later changes
# ---------------------------------------------------------------------------


def test_agent_meta_frozen_after_later_override_change(tmp_path) -> None:
    """``agent_meta.json`` is written once at launch.  Changing the
    override afterward must not retroactively rewrite the meta of an
    already-launched agent."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    set_temporary_override("codex/o3", 3600.0, source="test")
    extract_directives_and_write_meta(
        prompt="just a plain prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta_path = tmp_path / "artifacts" / "agent_meta.json"
    original = json.loads(meta_path.read_text(encoding="utf-8"))
    assert original["llm_provider"] == "codex"
    assert original["model"] == "o3"
    original_mtime = meta_path.stat().st_mtime_ns

    # Now change (and later clear) the override — agent's meta file
    # must not move.
    set_temporary_override("opus", 60.0, source="test")
    clear_temporary_override()

    after = json.loads(meta_path.read_text(encoding="utf-8"))
    assert after == original
    assert meta_path.stat().st_mtime_ns == original_mtime


def test_agent_meta_after_clear_uses_default_provider(tmp_path) -> None:
    """Clearing the override mid-session: the *next* launch resolves
    against the configured default, not the cleared override."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_a = tmp_path / "a"
    artifacts_b = tmp_path / "b"
    os.makedirs(workspace_dir, exist_ok=True)
    artifacts_a.mkdir()
    artifacts_b.mkdir()

    set_temporary_override("codex/o3", 3600.0, source="test")
    extract_directives_and_write_meta(
        prompt="a", workspace_dir=workspace_dir, artifacts_dir=str(artifacts_a)
    )
    clear_temporary_override()
    extract_directives_and_write_meta(
        prompt="b", workspace_dir=workspace_dir, artifacts_dir=str(artifacts_b)
    )

    meta_a = json.loads((artifacts_a / "agent_meta.json").read_text(encoding="utf-8"))
    meta_b = json.loads((artifacts_b / "agent_meta.json").read_text(encoding="utf-8"))

    assert (meta_a["llm_provider"], meta_a["model"]) == ("codex", "o3")
    # Default in the test environment is "claude" (autodetect priority).
    assert meta_b["llm_provider"] == "claude"
    assert (meta_b["llm_provider"], meta_b["model"]) != ("codex", "o3")


def test_agent_meta_until_cleared_override_records_provider(tmp_path) -> None:
    """An ``until cleared`` override (no expiry) is treated like any
    other active override at metadata-resolution time."""
    from sase.axe.run_agent_phases import extract_directives_and_write_meta

    workspace_dir = str(tmp_path / "workspace")
    artifacts_dir = str(tmp_path / "artifacts")
    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(artifacts_dir, exist_ok=True)

    set_temporary_override("codex/o3", None, source="test")
    extract_directives_and_write_meta(
        prompt="prompt",
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
    )

    meta = json.loads(
        (tmp_path / "artifacts" / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert meta["llm_provider"] == "codex"
    assert meta["model"] == "o3"


# ---------------------------------------------------------------------------
# Leader-mode dispatch
# ---------------------------------------------------------------------------


def test_leader_handler_dispatches_temporary_llm_override() -> None:
    """The ``LeaderModeMixin._handle_leader_key`` routes the configured
    chord to ``_open_temporary_llm_override_modal``.

    Guards against a future refactor where the dispatch table forgets
    to wire the chord; nothing else in the suite would catch that
    silently — pressing ``,P`` would just be a no-op.
    """
    from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin

    # Plain MagicMock — we want unrestricted attribute access for the
    # many helpers the dispatcher might consult before reaching ours.
    mixin = MagicMock()
    mixin._keymap_registry = _full_registry()
    mixin.current_tab = "changespecs"
    mixin.marked_indices = []
    mixin._leader_mode_active = True

    handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "P")

    assert handled is True
    mixin._open_temporary_llm_override_modal.assert_called_once()


def test_temporary_override_dismiss_set_refreshes_top_bar_indicator() -> None:
    """A successful set result refreshes the persistent top-bar badge."""
    from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
    from sase.ace.tui.widgets import LLMOverrideIndicator

    mixin = MagicMock()
    indicator = MagicMock(spec=LLMOverrideIndicator)
    mixin.query_one.return_value = indicator

    LeaderModeMixin._open_temporary_llm_override_modal(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(TemporaryOverrideResult(action="set"))

    mixin.query_one.assert_called_once_with(
        "#llm-override-indicator", LLMOverrideIndicator
    )
    indicator.refresh.assert_called_once()
    mixin.notify.assert_not_called()


def test_temporary_override_dismiss_clear_refreshes_top_bar_indicator() -> None:
    """A clear result refreshes the badge and keeps the existing clear toast."""
    from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
    from sase.ace.tui.widgets import LLMOverrideIndicator

    mixin = MagicMock()
    indicator = MagicMock(spec=LLMOverrideIndicator)
    mixin.query_one.return_value = indicator

    LeaderModeMixin._open_temporary_llm_override_modal(cast(LeaderModeMixin, mixin))

    callback = mixin.push_screen.call_args.kwargs["callback"]
    callback(TemporaryOverrideResult(action="cleared"))

    mixin.query_one.assert_called_once_with(
        "#llm-override-indicator", LLMOverrideIndicator
    )
    indicator.refresh.assert_called_once()
    mixin.notify.assert_called_once_with("Cleared temporary LLM override")
