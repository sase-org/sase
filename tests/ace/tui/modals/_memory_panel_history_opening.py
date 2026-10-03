"""History and changes opening tests for the memory panel."""

from __future__ import annotations

from tests.ace.tui.modals.memory_panel_test_helpers import (
    memory_note,
    scope_ref,
    scope_snapshot,
)


def _prepare_history_panel(monkeypatch, *, webs: tuple = ()) -> tuple:
    """Build a loaded ``MemoryPane`` with the history open path stubbed.

    With *webs*, the scope holds only those webs plus their descriptor
    notes, so the first rail row is the first web's descriptor.
    """
    from types import SimpleNamespace

    from textual.screen import Screen
    from textual.widgets import Static

    from sase.ace.tui.modals.memory_pane import MemoryPane
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        MemoryPanelTestApp,
        install_fixed_load,
    )

    ref = scope_ref("sase", "sase")
    if webs:
        notes = tuple(
            memory_note(web.slug, note_type=None, type_source="missing") for web in webs
        )
    else:
        notes = (memory_note("gotchas"), memory_note("zebra"))
    snapshots = {"sase": scope_snapshot(ref, notes, webs=webs)}
    install_fixed_load(monkeypatch, (ref,), snapshots)

    panel = MemoryPane()
    app = MemoryPanelTestApp(panel)

    fake_scope = SimpleNamespace(scope_key="project:sase", repo_root="/tmp")
    service = SimpleNamespace()
    history = SimpleNamespace(service=service, scope_for_ref=lambda _ref: fake_scope)
    monkeypatch.setattr(panel, "_ace_history", lambda: history)

    import sase.ace.tui.modals.memory_panel_history as history_module

    monkeypatch.setattr(
        history_module, "_history_scope_for_panel_ref", lambda _ref, _svc: fake_scope
    )
    monkeypatch.setattr(
        history_module,
        "history_scopes_for_ring",
        lambda _ring, _svc: [fake_scope],
    )

    pushed: list = []

    class _FakePager(Screen):
        def __init__(self, document: object, **_kwargs: object) -> None:
            super().__init__()
            self.document = document
            pushed.append(self)

        def compose(self):  # noqa: ANN202
            yield Static("pager")

    import sase.pager.screen as pager_screen_module
    import sase.pager.syntax_policy as syntax_policy_module

    monkeypatch.setattr(pager_screen_module, "PagerScreen", _FakePager)
    monkeypatch.setattr(
        syntax_policy_module,
        "pager_syntax_session_from_config",
        lambda: SimpleNamespace(syntax_enabled=False),
    )
    return panel, app, pushed, service


async def test_open_history_key_opens_pager(
    monkeypatch,
) -> None:
    """Pressing ``H`` opens the pager instead of failing silently."""
    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    sentinel = object()
    import sase.memory.history.pager_provider as pager_provider_module

    monkeypatch.setattr(
        pager_provider_module,
        "build_history_document",
        lambda **_kwargs: sentinel,
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 1)
        assert pushed[0].document is sentinel


async def test_open_changes_key_opens_changes_lens(
    monkeypatch,
) -> None:
    """Pressing ``C`` turns the rail into the Changes lens (no pager push)."""
    from sase.ace.testing import wait_for

    panel, app, pushed, service = _prepare_history_panel(monkeypatch)
    panel._ace_history().feed = lambda _scopes: {"changesets": []}
    import sase.ace.tui.modals.memory_pane_changes_lens as changes_module

    seen: dict = {}
    real_fetch = changes_module.MemoryPaneChangesLensMixin._changes_fetch

    def _spy_fetch(self) -> None:  # noqa: ANN001, ANN202
        seen["fetched"] = True
        return real_fetch(self)

    monkeypatch.setattr(
        changes_module.MemoryPaneChangesLensMixin, "_changes_fetch", _spy_fetch
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "changes")
        assert pushed == []
        assert seen.get("fetched") is True
        await pilot.press("C")
        await wait_for(pilot, lambda: panel._lens == "notes")


async def test_open_history_failure_surfaces_error_toast(
    monkeypatch,
) -> None:
    """A pager build miss toasts instead of failing silently."""
    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    import sase.memory.history.pager_provider as pager_provider_module

    monkeypatch.setattr(
        pager_provider_module, "build_history_document", lambda **_kwargs: None
    )
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        panel,
        "notify",
        lambda message, *_, **kwargs: toasts.append(
            (str(message), str(kwargs.get("severity", "")))
        ),
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: len(toasts) == 1)
        assert "could not open history" in toasts[0][0]
        assert toasts[0][1] == "error"
        assert pushed == []


async def test_open_history_stale_selection_drops_the_open(
    monkeypatch,
) -> None:
    """Moving the cursor while history loads drops the pager open."""
    import threading

    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    release = threading.Event()
    started = threading.Event()
    sentinel = object()
    import sase.memory.history.pager_provider as pager_provider_module

    def _slow_build(**_kwargs):  # noqa: ANN202
        started.set()
        assert release.wait(timeout=10)
        return sentinel

    monkeypatch.setattr(pager_provider_module, "build_history_document", _slow_build)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: started.is_set())
        await pilot.press("j")
        release.set()
        await wait_for(
            pilot,
            lambda: (
                panel._history_open_worker is not None
                and panel._history_open_worker.is_finished
            ),
        )
        await pilot.pause()
        assert pushed == []


async def test_open_history_key_opens_web_descriptor_and_strand(
    monkeypatch,
) -> None:
    """``H`` opens a web descriptor by path and a strand as ``web:slug``."""
    from sase.ace.testing import wait_for
    from tests.ace.tui.modals.memory_panel_test_helpers import (
        install_fake_strand_read,
        memory_web_with_mentioning_strands,
    )

    web = memory_web_with_mentioning_strands()
    panel, app, pushed, _service = _prepare_history_panel(monkeypatch, webs=(web,))
    install_fake_strand_read(monkeypatch)
    titles: list[str] = []
    import sase.memory.history.pager_provider as pager_provider_module

    def _build(**kwargs):  # noqa: ANN202
        titles.append(str(kwargs.get("title")))
        return object()

    monkeypatch.setattr(pager_provider_module, "build_history_document", _build)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 1)
        assert titles == ["sase/memory/glossary.md"]
        app.pop_screen()
        await pilot.press("space")
        await pilot.press("j")
        await wait_for(
            pilot,
            lambda: getattr(panel._selected_row(), "strand", None) is not None,
        )
        await pilot.press("H")
        await wait_for(pilot, lambda: len(pushed) == 2)
        assert titles[-1] == "glossary:alpha"


async def test_open_history_failure_names_the_reason(
    monkeypatch,
) -> None:
    """A raising pager build toasts ``could not open history: <reason>``."""
    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    import sase.memory.history.pager_provider as pager_provider_module

    def _boom(**_kwargs):  # noqa: ANN202
        raise RuntimeError("index is locked")

    monkeypatch.setattr(pager_provider_module, "build_history_document", _boom)
    toasts: list[str] = []
    monkeypatch.setattr(
        panel, "notify", lambda message, *_, **_kw: toasts.append(str(message))
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: len(toasts) == 1)
        assert toasts == ["could not open history: index is locked"]
        assert pushed == []


async def test_open_history_hidden_hub_drops_the_open(
    monkeypatch,
) -> None:
    """Hiding the hosting hub while history loads drops the pager open."""
    import threading

    from sase.ace.testing import wait_for

    panel, app, pushed, _service = _prepare_history_panel(monkeypatch)
    release = threading.Event()
    started = threading.Event()
    import sase.memory.history.pager_provider as pager_provider_module

    def _slow_build(**_kwargs):  # noqa: ANN202
        started.set()
        assert release.wait(timeout=10)
        return object()

    monkeypatch.setattr(pager_provider_module, "build_history_document", _slow_build)
    toasts: list[str] = []
    monkeypatch.setattr(
        panel, "notify", lambda message, *_, **_kw: toasts.append(str(message))
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        await pilot.press("H")
        await wait_for(pilot, lambda: started.is_set())
        panel.on_center_tab_visibility_changed(False)
        release.set()
        await wait_for(
            pilot,
            lambda: (
                panel._history_open_worker is not None
                and panel._history_open_worker.is_finished
            ),
        )
        await pilot.pause()
        assert pushed == []
        assert toasts == []


def test_open_history_failure_uses_honest_state_words() -> None:
    """Untracked and no-VCS misses toast the pager's honest words."""
    import sase.ace.tui.modals.memory_pane_history as memory_pane_history_module

    assert (
        memory_pane_history_module._history_open_failure(
            {"state": "untracked"}, home_without_scope=False, reason="x"
        )
        == "no history yet · commit this file to start its history"
    )
    assert (
        memory_pane_history_module._history_open_failure(
            {"state": "no_vcs"}, home_without_scope=False, reason=""
        )
        == "home memory is not in git"
    )
    assert (
        memory_pane_history_module._history_open_failure(
            None, home_without_scope=True, reason="no scope"
        )
        == "home memory is not in git"
    )
    assert (
        memory_pane_history_module._history_open_failure(
            {"state": "tracked"}, home_without_scope=False, reason="boom"
        )
        == "could not open history: boom"
    )
    assert (
        memory_pane_history_module._history_open_failure(
            None, home_without_scope=False, reason=""
        )
        == "could not open history: unknown reason"
    )
