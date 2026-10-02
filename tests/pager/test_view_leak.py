"""Dismissed pager views must be garbage-collectable.

``PagerView`` used to watch the app's ``theme`` reactive, and Textual only
prunes those watchers on the next theme change — so every closed pager
stayed alive (with its document, trail, and strip caches) until then. Views
now subscribe to the app's theme signal and unsubscribe on unmount.
"""

from __future__ import annotations

import gc
import weakref
from typing import Any

from sase.pager.app import SasePager
from sase.pager.screen import PagerScreen
from sase.pager.view import PagerView
from tests.pager._app_helpers import long_document, pager_screen

_HOST_SIZE = (120, 40)


async def _push_pop_views(
    host: SasePager, pilot: Any, count: int
) -> list[weakref.ReferenceType[PagerView]]:
    """Push and pop a screen *count* times; return weakrefs to its views."""
    refs: list[weakref.ReferenceType[PagerView]] = []
    for _ in range(count):
        pushed = PagerScreen(host.document)
        await host.push_screen(pushed)
        await pilot.pause()
        refs.append(weakref.ref(pushed.query_one(PagerView)))
        await host.pop_screen()
        await pilot.pause()
        del pushed
    return refs


async def test_pushed_and_popped_screens_release_their_views() -> None:
    """Three push/pop cycles leave zero live ``PagerView``s after gc.

    The check runs while the host app is still alive: app shutdown frees
    watcher registries anyway, so asserting after exit could not catch
    the leak this guards against.
    """
    host = SasePager(long_document())
    async with host.run_test(size=_HOST_SIZE) as pilot:
        await pilot.pause()
        refs = await _push_pop_views(host, pilot, 3)
        gc.collect()
        assert [ref() for ref in refs] == [None, None, None]


async def test_split_open_and_close_releases_both_panes() -> None:
    """A split opened and closed inside one push/pop cycle leaves nothing."""
    host = SasePager(long_document())
    async with host.run_test(size=_HOST_SIZE) as pilot:
        await pilot.pause()
        pushed = PagerScreen(host.document)
        await host.push_screen(pushed)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(pushed.views) == 2
        removed_ref = weakref.ref(pushed.views[0])
        survivor_ref = weakref.ref(pushed.views[1])
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(pushed.views) == 1
        # The removed pane already left the theme signal on unmount: the
        # old watcher leak pinned every closed view from the app.
        subscriptions = host.theme_changed_signal._subscriptions  # noqa: SLF001
        assert removed_ref() not in subscriptions
        await host.pop_screen()
        await pilot.pause()
        del pushed
        gc.collect()
        assert removed_ref() is None
        assert survivor_ref() is None


async def test_exited_app_releases_its_views() -> None:
    """Quitting the standalone pager frees the hosted view."""
    host = SasePager(long_document())
    async with host.run_test(size=_HOST_SIZE) as pilot:
        await pilot.pause()
        view_ref = weakref.ref(pager_screen(host).focused_view)
        await pilot.press("q")
        await pilot.pause()
    gc.collect()
    assert view_ref() is None
