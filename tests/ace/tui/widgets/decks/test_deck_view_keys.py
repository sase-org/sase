"""Deck-view keys: defaults, gating, footer, palette, help and search."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui._artifact_tab_actions import keymap_actions_by_key
from sase.ace.tui.actions.agents._deck_search_host import deck_structural_exit_keys
from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.commands._availability_agents import agents_available
from sase.ace.tui.commands.context import extract_command_context
from sase.ace.tui.commands.types import CommandContext, CommandSpec
from sase.ace.tui.keymaps import (
    build_app_bindings,
    load_keymap_registry,
)
from sase.ace.tui.modals.help_modal.bindings import agents_bindings
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.models.agent import Agent, AgentType
from tests._keymaps_helpers import default_app_keymaps


def _agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="test",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
    )


def _gating_app(
    *,
    tab: str = "agents",
    available: bool = False,
    lock_available: bool = False,
    prompt: bool = False,
    modal: bool = False,
):
    panel = SimpleNamespace(
        deck_view_cycle_available=available,
        deck_view_lock_available=lock_available,
    )
    area = SimpleNamespace(focused_panel=lambda: panel)
    detail = SimpleNamespace(deck_area=area)
    if modal:
        from textual.screen import ModalScreen

        class _Modal(ModalScreen):
            pass

        _screen: object = _Modal()
    else:
        _screen = SimpleNamespace()

    class _App:
        current_tab = tab
        current_artifacts_pane_key = "patches"
        _screen_stack = ("home",)
        screen = _screen

        def _prompt_input_active(self) -> bool:
            return prompt

        def query_one(self, *args, **kwargs):
            return detail

    return _App()


def test_deck_view_default_key_is_uppercase_p() -> None:
    reg = load_keymap_registry({})
    assert reg.app.cycle_deck_view == "P"
    assert reg.app.toggle_deck_view_lock == "B"
    assert reg.app.pick_deck == "p"


def test_deck_view_binding_fallback_and_no_app_conflict() -> None:
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["cycle_deck_view"].key == "P"
    assert by_action["toggle_deck_view_lock"].key == "B"
    assert [b.action for b in bindings if b.key == "P"] == ["cycle_deck_view"]
    assert [b.action for b in bindings if b.key == "B"] == ["toggle_deck_view_lock"]
    fallback = {b.action: b for b in DEFAULT_BINDINGS}
    assert fallback["cycle_deck_view"].key == "P"
    assert fallback["toggle_deck_view_lock"].key == "B"
    # Lowercase p stays the deck picker; uppercase P is the view cycle.
    assert by_action["pick_deck"].key == "p"


def test_modal_scoped_p_keys_survive_app_p() -> None:
    from sase.ace.tui.keymaps.app_keymaps import (
        MemoryPanelKeymaps,
        SnippetPanelKeymaps,
        StatisticsPaneKeymaps,
    )

    assert StatisticsPaneKeymaps().cycle_project_filter_reverse == "P"
    assert MemoryPanelKeymaps().prev_scope == "P"
    assert SnippetPanelKeymaps().prev_project == "P"
    # Inside any modal the Agents-only cycle is gated off.
    assert (
        check_app_action(
            _gating_app(available=True, modal=True),
            "cycle_deck_view",
            (),
            lambda _a, _p: None,
        )
        is False
    )


def test_deck_view_gating_needs_agents_tab_available_panel_no_prompt() -> None:
    assert (
        check_app_action(
            _gating_app(available=True), "cycle_deck_view", (), lambda _a, _p: None
        )
        is not False
    )
    assert (
        check_app_action(
            _gating_app(lock_available=True),
            "toggle_deck_view_lock",
            (),
            lambda _a, _p: None,
        )
        is not False
    )
    # Tools, empty, partial, and single-layout decks report unavailable
    # through the cached panel predicate.
    assert (
        check_app_action(
            _gating_app(available=False), "cycle_deck_view", (), lambda _a, _p: None
        )
        is False
    )
    assert (
        check_app_action(
            _gating_app(lock_available=False),
            "toggle_deck_view_lock",
            (),
            lambda _a, _p: None,
        )
        is False
    )
    assert (
        check_app_action(
            _gating_app(tab="artifacts", available=True),
            "cycle_deck_view",
            (),
            lambda _a, _p: None,
        )
        is False
    )
    assert (
        check_app_action(
            _gating_app(available=True, prompt=True),
            "cycle_deck_view",
            (),
            lambda _a, _p: None,
        )
        is False
    )
    # FINAL panels never offer the cycle (explicit Main/Files dispatch).
    from sase.ace.tui.widgets.decks.panel import DeckPanel
    from sase.ace.tui.widgets.decks.model import DeckId

    panel = DeckPanel(0)
    panel._deck = DeckId.FINAL
    assert panel.deck_view_cycle_available is False


def test_panel_lock_availability_allows_only_cycle_or_locked_views() -> None:
    from sase.ace.tui.widgets.decks.model import (
        DeckId,
        DeckView,
        DeckViewPolicies,
    )
    from sase.ace.tui.widgets.decks.panel import DeckPanel

    panel = DeckPanel(0)
    panel._deck = DeckId.MAIN
    panel._main_document = SimpleNamespace(partial=False, cards=[object()])
    panel._view_policies = DeckViewPolicies()
    assert panel._compute_view_lock_available(cycle_available=True) is True
    assert panel._compute_view_lock_available(cycle_available=False) is False

    panel._view_policies = DeckViewPolicies(main=DeckView.SPREAD)
    assert panel._compute_view_lock_available(cycle_available=False) is True

    panel._main_document.partial = True
    assert panel._compute_view_lock_available(cycle_available=True) is False


def test_p_key_resolves_per_tab() -> None:
    reg = load_keymap_registry({})
    owners = keymap_actions_by_key(reg.app)
    assert set(owners["P"]) == {"cycle_deck_view"}
    assert set(owners["B"]) == {"toggle_deck_view_lock"}
    artifacts = _gating_app(tab="artifacts", available=True)
    assert (
        check_app_action(artifacts, "cycle_deck_view", (), lambda _a, _p: None) is False
    )


def test_deck_view_handlers_dispatch_and_refresh_footer() -> None:
    from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
    from sase.ace.tui.widgets.decks.model import DeckId, DeckView

    assert hasattr(AgentPanelDetailMixin, "action_cycle_deck_view")
    assert hasattr(AgentPanelDetailMixin, "action_set_deck_view_at")

    seen: dict[str, object] = {}

    class _Panel:
        deck = DeckId.MAIN

    class _Area:
        def focused_panel(self) -> object:
            return _Panel()

    class _Detail:
        deck_area = _Area()

        def cycle_focused_deck_view(self) -> tuple[DeckView, bool]:
            seen["cycled"] = True
            return (DeckView.SPREAD, True)

        def set_focused_deck_view(self, view: DeckView) -> bool:
            seen["set"] = view
            return True

    class _Host(AgentPanelDetailMixin):
        current_tab = "agents"
        _keymap_registry = SimpleNamespace(
            app=SimpleNamespace(toggle_deck_view_lock="B")
        )
        notified: str | None = None

        def query_one(self, *args, **kwargs):
            return _Detail()

        def notify(self, message: str, severity: str = "information") -> None:
            self.notified = message

        def _refresh_agent_footer_bindings_only(self) -> None:
            seen["refreshed"] = True

    host = _Host()
    host.action_cycle_deck_view()
    assert seen.get("cycled") is True
    assert seen.get("refreshed") is True
    assert host.notified == "Main view locked \U0001f512 \u00b7 B unlocks"
    assert len(host.notified) <= 70

    class _OtherTab(_Host):
        current_tab = "artifacts"

    seen.clear()
    other = _OtherTab()
    other.action_cycle_deck_view()
    assert seen == {}
    assert other.notified is None


def test_deck_view_lock_action_dispatches_without_a_toast() -> None:
    from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
    from sase.ace.tui.widgets.decks.model import DeckView

    class _Detail:
        def toggle_focused_deck_view_lock(self) -> DeckView:
            return DeckView.AUTO

    class _Host(AgentPanelDetailMixin):
        current_tab = "agents"

        def query_one(self, *args, **kwargs):
            return _Detail()

        def _refresh_agent_footer_bindings_only(self) -> None:
            self.refreshed = True

    host = _Host()
    host.action_toggle_deck_view_lock()
    assert host.refreshed is True
    assert not hasattr(host, "notified")


def test_focused_lock_toggle_preserves_effective_layout_and_unlocks() -> None:
    from sase.ace.tui.widgets._agent_detail_deck_view import AgentDetailDeckViewMixin
    from sase.ace.tui.widgets.decks.model import DeckId, DeckView

    changes: list[tuple[int, DeckId, DeckView, bool]] = []
    policy = DeckView.AUTO

    class _Panel:
        deck = DeckId.MAIN
        panel_index = 2
        deck_view_lock_available = True

        def view_policy(self, _deck: DeckId) -> DeckView:
            return policy

        def effective_layout(self, _deck: DeckId) -> DeckView:
            return DeckView.PAGE_BLOCKS

    class _Area:
        def focused_panel(self) -> _Panel:
            return _Panel()

        def set_panel_view(
            self, index: int, deck: DeckId, view: DeckView, *, user_initiated: bool
        ) -> None:
            changes.append((index, deck, view, user_initiated))

    class _Detail(AgentDetailDeckViewMixin):
        deck_area = _Area()

        def _notify_deck_state_changed(self) -> None:
            changes.append((0, DeckId.MAIN, DeckView.AUTO, False))

    detail = _Detail()
    assert detail.toggle_focused_deck_view_lock() is DeckView.PAGE_BLOCKS
    assert changes[0] == (2, DeckId.MAIN, DeckView.PAGE_BLOCKS, True)

    policy = DeckView.PAGE_BLOCKS
    assert detail.toggle_focused_deck_view_lock() is DeckView.AUTO
    assert changes[2] == (2, DeckId.MAIN, DeckView.AUTO, True)


def test_deck_view_first_fix_toast_fires_once() -> None:
    from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
    from sase.ace.tui.widgets.decks.model import DeckView

    notified: list[str] = []

    class _Detail:
        def __init__(self, first_fix: bool) -> None:
            self._first_fix = first_fix

        def cycle_focused_deck_view(self) -> tuple[DeckView, bool]:
            return (DeckView.PAGE_CARDS, self._first_fix)

        @property
        def deck_area(self) -> object:
            from sase.ace.tui.widgets.decks.model import DeckId

            return SimpleNamespace(
                focused_panel=lambda: SimpleNamespace(deck=DeckId.FILES)
            )

    class _Host(AgentPanelDetailMixin):
        current_tab = "agents"
        _keymap_registry = SimpleNamespace(
            app=SimpleNamespace(toggle_deck_view_lock="B")
        )

        def __init__(self, first_fix: bool, lock_key: str = "B") -> None:
            self._detail = _Detail(first_fix)
            self._keymap_registry = SimpleNamespace(
                app=SimpleNamespace(toggle_deck_view_lock=lock_key)
            )

        def query_one(self, *args, **kwargs):
            return self._detail

        def notify(self, message: str, severity: str = "information") -> None:
            notified.append(message)

        def _refresh_agent_footer_bindings_only(self) -> None:
            pass

    _Host(first_fix=True).action_cycle_deck_view()
    assert notified == ["Files view locked \U0001f512 \u00b7 B unlocks"]
    _Host(first_fix=False).action_cycle_deck_view()
    assert len(notified) == 1
    _Host(first_fix=True, lock_key="unbound").action_cycle_deck_view()
    assert notified[-1] == (
        'Files view locked \U0001f512 \u00b7 palette "Deck view: automatic" unlocks'
    )


def test_deck_view_set_action_maps_palette_index() -> None:
    from sase.ace.tui.actions.agents._panel_detail import AgentPanelDetailMixin
    from sase.ace.tui.widgets.decks.model import DECK_VIEW_CHOICES, DeckView

    seen: list[DeckView] = []

    class _Detail:
        def set_focused_deck_view(self, view: DeckView) -> bool:
            seen.append(view)
            return True

    class _Host(AgentPanelDetailMixin):
        current_tab = "agents"

        def query_one(self, *args, **kwargs):
            return _Detail()

        def _refresh_agent_footer_bindings_only(self) -> None:
            pass

    host = _Host()
    for index, view in enumerate(DECK_VIEW_CHOICES):
        host.action_set_deck_view_at(index)
        assert seen[-1] is view
    before = list(seen)
    host.action_set_deck_view_at(99)
    host.action_set_deck_view_at(-1)
    assert seen == before


def test_deck_view_footer_entry_is_conditional() -> None:
    footer = KeybindingFooter()
    agent = _agent()
    off = footer._compute_agent_bindings(agent)
    assert not any(label == "view" for _, label in off)
    on = footer._compute_agent_bindings(agent, deck_view_cycle_available=True)
    assert ("P", "view") in on


def test_deck_view_lock_footer_follows_availability_and_policy() -> None:
    footer = KeybindingFooter()
    agent = _agent()
    locked_out = footer._compute_agent_bindings(agent)
    assert not any(label in {"lock", "unlock"} for _, label in locked_out)
    automatic = footer._compute_agent_bindings(
        agent, deck_view_lock_available=True, deck_view_locked=False
    )
    assert ("B", "lock") in automatic
    locked = footer._compute_agent_bindings(
        agent, deck_view_lock_available=True, deck_view_locked=True
    )
    assert ("B", "unlock") in locked
    archive = footer._compute_archive_bindings(
        deck_view_lock_available=True, deck_view_locked=True
    )
    assert ("B", "unlock") in archive


def test_deck_card_footer_label_is_jump_when_spread() -> None:
    footer = KeybindingFooter()
    agent = _agent()
    paged = footer._compute_agent_bindings(agent, deck_card_count=2)
    assert any(label == "cards" for _, label in paged)
    spread = footer._compute_agent_bindings(
        agent, deck_card_count=2, deck_cards_spread=True
    )
    assert any(label == "jump" for _, label in spread)
    assert not any(label == "cards" for _, label in spread)


def test_deck_view_palette_specs_and_execution() -> None:
    from sase.ace.tui.commands import build_command_catalog
    from sase.ace.tui.commands.execute import execute_command
    from sase.ace.tui.widgets.decks.model import DECK_VIEW_CHOICES

    reg = load_keymap_registry({})
    by_id = {c.id: c for c in build_command_catalog(reg)}
    assert by_id["app.cycle_deck_view"].label == "Cycle deck view"
    assert by_id["app.cycle_deck_view"].key_display == "P"
    assert "spread" in by_id["app.cycle_deck_view"].aliases
    lock = by_id["app.toggle_deck_view_lock"]
    assert lock.label == "Toggle deck view lock"
    assert lock.key_display == "B"
    assert {"lock", "unlock", "hold view", "fixed"}.issubset(lock.aliases)
    labels = {
        "auto": "Deck view: automatic (unlock)",
        "spread": "Deck view: spread (locked)",
        "page_cards": "Deck view: page cards (locked)",
        "page_blocks": "Deck view: page blocks (locked)",
    }
    for index, view in enumerate(DECK_VIEW_CHOICES):
        spec = by_id[f"agents.deck_view.{view.value}"]
        assert spec.label == labels[view.value]
        assert spec.tabs == ("agents",)
        assert spec.executor.kind == "app_action"
        assert spec.executor.action == "set_deck_view_at"
        assert spec.executor.digit == index
        if view.value == "auto":
            assert "unlock" in spec.aliases
        else:
            assert "fixed" in spec.aliases
            assert "locked" in spec.aliases
            assert f"Deck view: {view.value.replace('_', ' ')} (fixed)" in spec.aliases

    class _App:
        def __init__(self) -> None:
            self.called: int | None = None

        def action_set_deck_view_at(self, digit: int) -> None:
            self.called = digit

        def notify(self, *args, **kwargs) -> None:
            pass

    app = _App()
    execute_command(app, by_id["agents.deck_view.page_cards"])
    assert app.called == 2


def test_deck_view_palette_availability_follows_context() -> None:
    def _spec(spec_id: str) -> CommandSpec:
        return CommandSpec(
            id=spec_id,
            label="x",
            key_sequence=(),
            key_display="",
            category="Navigation",
            tabs=("agents",),
            executor=("app-action", "set_deck_view_at"),
        )

    assert (
        agents_available(
            _spec("app.cycle_deck_view"),
            CommandContext(tab="agents", deck_view_cycle_available=True),
        )
        is True
    )
    assert (
        agents_available(
            _spec("app.cycle_deck_view"),
            CommandContext(tab="agents", deck_view_cycle_available=False),
        )
        is False
    )
    assert (
        agents_available(
            _spec("app.toggle_deck_view_lock"),
            CommandContext(
                tab="agents",
                deck_view_deck="main",
                deck_view_policy="auto",
                deck_view_cycle_available=True,
            ),
        )
        is True
    )
    assert (
        agents_available(
            _spec("app.toggle_deck_view_lock"),
            CommandContext(
                tab="agents",
                deck_view_deck="files",
                deck_view_policy="spread",
                deck_view_cycle_available=False,
            ),
        )
        is True
    )
    assert (
        agents_available(
            _spec("app.toggle_deck_view_lock"),
            CommandContext(
                tab="agents",
                deck_view_deck="main",
                deck_view_policy="auto",
                deck_view_cycle_available=False,
            ),
        )
        is False
    )
    # The command equal to the current policy is hidden.
    assert (
        agents_available(
            _spec("agents.deck_view.auto"),
            CommandContext(
                tab="agents", deck_view_deck="main", deck_view_policy="auto"
            ),
        )
        is False
    )
    assert (
        agents_available(
            _spec("agents.deck_view.auto"),
            CommandContext(
                tab="agents", deck_view_deck="main", deck_view_policy="spread"
            ),
        )
        is True
    )
    # page_blocks is Main-only.
    assert (
        agents_available(
            _spec("agents.deck_view.page_blocks"),
            CommandContext(
                tab="agents", deck_view_deck="files", deck_view_policy="auto"
            ),
        )
        is False
    )
    assert (
        agents_available(
            _spec("agents.deck_view.page_blocks"),
            CommandContext(
                tab="agents", deck_view_deck="main", deck_view_policy="auto"
            ),
        )
        is True
    )
    # Tools, FINAL, and empty/partial decks hide the direct commands.
    for deck in ("tools", "final", None):
        assert (
            agents_available(
                _spec("agents.deck_view.spread"),
                CommandContext(
                    tab="agents",
                    deck_view_deck=deck,
                    deck_view_policy="auto",  # type: ignore[arg-type]
                ),
            )
            is False
        )


def test_deck_view_context_threads_focused_panel_state() -> None:
    from sase.ace.tui.widgets.decks.model import DeckId, DeckView

    panel = SimpleNamespace(
        deck=DeckId.MAIN,
        deck_view_cycle_available=True,
        view_policy=lambda _d: DeckView.SPREAD,
        _main_document=SimpleNamespace(partial=False, cards=[object()]),
    )
    area = SimpleNamespace(focused_panel=lambda: panel)
    detail = SimpleNamespace(deck_area=area, deck_layout=SimpleNamespace())
    app = SimpleNamespace(
        current_tab="agents",
        current_artifacts_pane_key="patches",
        _agents=[],
        current_idx=0,
        _marked_agents=set(),
        current_attempt_number=None,
        _panel_group=None,
        _agent_panels_grouped=False,
        _current_group_key=None,
        _agent_metadata_search=SimpleNamespace(is_active=False),
        _fleet_mode_available=lambda: False,
        _get_selected_agent=lambda: None,
        query_one=lambda *a, **k: detail,
        link_follow_available_for_selection=lambda: False,
        _axe_items=[],
        axe_running=False,
    )
    ctx = extract_command_context(app)
    assert ctx.deck_view_deck == "main"
    assert ctx.deck_view_policy == "spread"
    assert ctx.deck_view_cycle_available is True


def test_deck_view_help_row() -> None:
    reg = load_keymap_registry({})
    pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert ("P", "Lock a wider deck view (B unlocks)") in pairs
    assert ("B", "Lock / unlock the deck view as shown") in pairs
    assert (
        "",
        "Tabs in a deck title mean one card per page; no tabs means one document, and ▴/▾ show where the rest is",
    ) in pairs


def test_deck_view_search_exit_keys() -> None:
    reg = load_keymap_registry({})
    app = SimpleNamespace(_keymap_registry=reg)
    keys = deck_structural_exit_keys(app)
    assert "P" in keys
    assert "B" in keys
    assert "p" in keys
