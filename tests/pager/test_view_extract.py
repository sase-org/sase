"""Host contract tests for the extracted per-pane ``PagerView``.

``PagerScreen`` is a thin host: its bindings route per-document actions
to the focused view, while ``close_pager``/``show_help`` stay on the
screen. These tests pin that contract so later split phases can rely on
it.
"""

from __future__ import annotations

import asyncio

from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.pager.app import SasePager
from sase.pager.screen import PagerScreen
from sase.pager.view import PagerView
from tests.pager._app_helpers import long_document, pager_screen, pager_view

_HOST_ACTIONS = {"close_pager", "show_help"}


def test_every_screen_binding_resolves_to_the_focused_view() -> None:
    """Each routed binding name names a ``PagerView`` action method."""
    missing = []
    for binding in PagerScreen.BINDINGS:
        action = binding.action
        assert action, binding
        if action in _HOST_ACTIONS:
            assert callable(getattr(PagerScreen, f"action_{action}")), action
            continue
        target = getattr(PagerView, f"action_{action}", None)
        if not callable(target):
            missing.append(action)
    assert missing == []


async def test_host_exposes_views_focus_and_document() -> None:
    """A single-pane screen hosts one view that owns the document."""
    document = long_document()
    app = SasePager(document)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = pager_screen(app)
        assert isinstance(screen.focused_view, PagerView)
        assert screen.views == (screen.focused_view,)
        assert pager_view(app) is screen.focused_view
        assert screen.document is document
        assert screen.focused_view.document is document


async def test_view_pump_free_tasks_cancel_on_unmount() -> None:
    """Removing a view cancels the tasks it registered."""
    app = SasePager(long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = pager_screen(app)
        view = pager_view(app)
        assert screen.views == (view,)
        started = asyncio.Event()
        release = asyncio.Event()

        async def _never() -> None:
            started.set()
            await release.wait()

        task = spawn_pump_free_task(
            view,
            _never(),
            name="sase-pager-view-extract-probe",
            registry_attr="_pump_free_probe_tasks",
        )
        assert task is not None
        await pilot.pause()
        assert started.is_set()
        assert not task.done()
        await view.remove()
        await pilot.pause()
        assert task.done()
        assert task.cancelled()
