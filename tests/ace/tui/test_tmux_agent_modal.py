"""Tests for the Launch Control tmux Agent panel."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess

from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

import sase.ace.tui.modals.models_panel_providers as providers
import sase.ace.tui.modals.models_panel_tmux_agent as models_panel_tmux_agent_module
import sase.ace.tui.modals.tmux_agent_modal as tmux_agent_modal_module
from sase.ace.testing import wait_for
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.tmux_agent_modal import TmuxAgentModal, _entry_row_text
from sase.config.tmux_agent import TmuxAgentConfig
from sase.llm_provider import TemporaryProviderDisable
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_MODE_SOFT
from sase.tmux_agent import (
    TmuxAgentCatalog,
    TmuxAgentEntry,
    TmuxAgentLaunch,
    TmuxAgentLaunchError,
    TmuxRunner,
)
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    patch_alias_views,
)
from tests._models_panel_provider_routing_helpers import snapshot as _provider_snapshot


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _entry(
    provider: str,
    *,
    installed: bool = True,
    key: str = "",
    display_name: str = "",
    vendor: str = "",
    color: str = "#7aa2f7",
    argv: tuple[str, ...] = (),
    bypass: bool = True,
    routing_disabled: TemporaryProviderDisable | None = None,
    effort: str | None = None,
    effort_skipped: str | None = None,
    install_hint: str = "",
) -> TmuxAgentEntry:
    return TmuxAgentEntry(
        provider=provider,
        display_name=display_name or provider.title(),
        vendor=vendor,
        color=color,
        key=key,
        binary=provider,
        executable=f"/usr/bin/{provider}" if installed else None,
        installed=installed,
        install_hint=install_hint or f"install {provider} first",
        routing_disabled=routing_disabled,
        argv=argv or (provider,),
        env=(),
        effort=effort,
        effort_skipped=effort_skipped,
        bypass=bypass,
    )


def _catalog(
    entries: Sequence[TmuxAgentEntry], *, directory: str = "/proj"
) -> TmuxAgentCatalog:
    default = next((entry.provider for entry in entries if entry.installed), None)
    return TmuxAgentCatalog(
        entries=tuple(entries), default_provider=default, directory=directory
    )


def _make_runner(
    *, windows: Sequence[tuple[int, str]] = (), pane_dir: str = "/proj"
) -> TmuxRunner:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in args]
        sub = argv[1] if len(argv) > 1 else ""
        if sub == "list-windows":
            stdout = "".join(f"{index}:{name}\n" for index, name in windows)
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        if sub == "display-message":
            return subprocess.CompletedProcess(argv, 0, pane_dir + "\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return TmuxRunner(run=run)


def _make_modal(
    entries: Sequence[TmuxAgentEntry],
    *,
    directory: str = "/proj",
    windows: Sequence[tuple[int, str]] = (),
) -> TmuxAgentModal:
    catalog = _catalog(entries, directory=directory)
    return TmuxAgentModal(
        catalog,
        load_catalog=lambda: catalog,
        config=TmuxAgentConfig(),
        runner=_make_runner(windows=windows),
    )


# ---------------------------------------------------------------------------
# Row rendering
# ---------------------------------------------------------------------------


def test_row_text_marks_ready_not_installed_and_routing_disabled() -> None:
    ready = _entry("claude", key="c")
    missing = _entry("codex", key="x", installed=False)
    disable = TemporaryProviderDisable(
        version=2,
        provider="grok",
        created_at=700.0,
        expires_at=1300.0,
        source="manual",
    )
    disabled = _entry("grok", key="g", routing_disabled=disable)

    assert "ready" in _entry_row_text(ready, now=1000.0).plain
    assert "not installed" in _entry_row_text(missing, now=1000.0).plain
    disabled_text = _entry_row_text(disabled, now=1000.0).plain
    assert "routing disabled" in disabled_text
    assert "5m left" in disabled_text


def test_row_text_marks_soft_disable_without_routing_disabled_label() -> None:
    disable = TemporaryProviderDisable(
        version=2,
        provider="grok",
        created_at=700.0,
        expires_at=1300.0,
        source="manual",
        mode=PROVIDER_DISABLE_MODE_SOFT,
    )
    soft = _entry("grok", key="g", routing_disabled=disable)

    soft_text = _entry_row_text(soft, now=1000.0).plain
    assert "soft" in soft_text
    assert "5m left" in soft_text
    assert "routing disabled" not in soft_text


def test_description_strip_shows_exact_command() -> None:
    entry = _entry("claude", key="c", argv=("claude", "--dangerously-skip-permissions"))
    modal = _make_modal([entry])

    text = modal._description_text(entry).plain

    assert "claude --dangerously-skip-permissions" in text


def test_description_strip_shows_install_hint_when_not_installed() -> None:
    entry = _entry("codex", key="x", installed=False, install_hint="brew install codex")
    modal = _make_modal([entry])

    text = modal._description_text(entry).plain

    assert "brew install codex" in text


# ---------------------------------------------------------------------------
# Navigation and launching
# ---------------------------------------------------------------------------


async def test_navigation_skips_not_installed_rows() -> None:
    entries = [
        _entry("claude", key="c"),
        _entry("codex", key="x", installed=False),
        _entry("agy", key="a"),
    ]
    modal = _make_modal(entries)

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one(f"#{modal._option_list_id}", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("j")
        await pilot.pause()

        assert option_list.highlighted == 2


async def test_enter_launches_highlighted_provider(monkeypatch) -> None:
    entry = _entry("claude", key="c", argv=("claude",))
    modal = _make_modal([entry])
    launched: list[TmuxAgentEntry] = []

    def fake_launch(launch_entry, **_kwargs):
        launched.append(launch_entry)
        return TmuxAgentLaunch(
            window_name="ai", channel="chan", argv=launch_entry.argv, directory="/proj"
        )

    monkeypatch.setattr(tmux_agent_modal_module, "launch_agent_window", fake_launch)

    result: object | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await wait_for(pilot, lambda: result != "sentinel")

    assert result is True
    assert launched and launched[0].provider == "claude"


async def test_selector_key_launches_provider(monkeypatch) -> None:
    entries = [_entry("claude", key="c"), _entry("agy", key="a")]
    modal = _make_modal(entries)
    launched: list[str] = []

    def fake_launch(launch_entry, **_kwargs):
        launched.append(launch_entry.provider)
        return TmuxAgentLaunch(
            window_name="ai", channel="chan", argv=launch_entry.argv, directory="/proj"
        )

    monkeypatch.setattr(tmux_agent_modal_module, "launch_agent_window", fake_launch)

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("a")
        await wait_for(pilot, lambda: bool(launched))

    assert launched == ["agy"]


async def test_safe_launch_strips_bypass_args(monkeypatch) -> None:
    entry = _entry(
        "claude",
        key="c",
        argv=("claude", "--dangerously-skip-permissions"),
        bypass=True,
    )
    modal = _make_modal([entry])
    monkeypatch.setattr(
        tmux_agent_modal_module.llm_registry,
        "provider_interactive_cli_map",
        lambda: {"claude": {"bypass_args": ("--dangerously-skip-permissions",)}},
    )
    launched: list[TmuxAgentEntry] = []

    def fake_launch(launch_entry, **_kwargs):
        launched.append(launch_entry)
        return TmuxAgentLaunch(
            window_name="ai", channel="chan", argv=launch_entry.argv, directory="/proj"
        )

    monkeypatch.setattr(tmux_agent_modal_module, "launch_agent_window", fake_launch)

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("s")
        await wait_for(pilot, lambda: bool(launched))

    assert launched[0].bypass is False
    assert "--dangerously-skip-permissions" not in launched[0].argv


async def test_launch_failure_keeps_modal_open_and_notifies_error(monkeypatch) -> None:
    entry = _entry("claude", key="c")
    modal = _make_modal([entry])
    notices: list[tuple[str, str]] = []

    def notify(
        _self: TmuxAgentModal, message: str, *, severity: str = "information", **_kwargs
    ) -> None:
        notices.append((message, severity))

    monkeypatch.setattr(TmuxAgentModal, "notify", notify)
    monkeypatch.setattr(
        tmux_agent_modal_module,
        "launch_agent_window",
        lambda *_a, **_k: TmuxAgentLaunchError("not_installed", "install claude first"),
    )

    result: object | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(notices))

    assert result == "sentinel"  # modal never dismissed
    assert notices == [("install claude first", "error")]


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------


def test_on_unmount_cancels_running_workers() -> None:
    modal = _make_modal([_entry("claude", key="c")])

    class _FakeWorker:
        def __init__(self) -> None:
            self.is_finished = False
            self.cancel_calls = 0

        def cancel(self) -> None:
            self.cancel_calls += 1

    catalog_worker = _FakeWorker()
    launch_worker = _FakeWorker()
    modal._catalog_worker = catalog_worker  # type: ignore[assignment]
    modal._launch_worker = launch_worker  # type: ignore[assignment]

    modal.on_unmount()

    assert catalog_worker.cancel_calls == 1
    assert launch_worker.cancel_calls == 1


# ---------------------------------------------------------------------------
# Launch Control wiring
# ---------------------------------------------------------------------------


async def test_panel_t_opens_tmux_agent_modal(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium", "role")])
    monkeypatch.setattr(
        providers,
        "load_provider_routing_snapshot",
        lambda _now=None: _provider_snapshot(),
    )
    monkeypatch.setattr(models_panel_tmux_agent_module, "inside_tmux", lambda: True)
    entry = _entry("claude", key="c")
    catalog = _catalog([entry])
    monkeypatch.setattr(ModelsPanel, "_load_tmux_agent_catalog", lambda self: catalog)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        footer = panel.query_one("#models-panel-footer", Static)
        assert "tmux Agent" in str(footer.content)

        await pilot.press("t")
        await pilot.pause()

        assert isinstance(pilot.app.screen, TmuxAgentModal)


async def test_panel_t_outside_tmux_warns_instead_of_opening(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium", "role")])
    monkeypatch.setattr(
        providers,
        "load_provider_routing_snapshot",
        lambda _now=None: _provider_snapshot(),
    )
    monkeypatch.setattr(models_panel_tmux_agent_module, "inside_tmux", lambda: False)
    notices: list[tuple[str, str]] = []

    def notify(
        _self: ModelsPanel, message: str, *, severity: str = "information", **_kwargs
    ) -> None:
        notices.append((message, severity))

    monkeypatch.setattr(ModelsPanel, "notify", notify)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        await pilot.press("t")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)

    assert notices
    message, severity = notices[-1]
    assert severity == "warning"
    assert "not running inside tmux" in message
