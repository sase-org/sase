"""Non-slow performance regression gates for the virtualized pager.

The dismissed-view leak probe already runs as regular tests in
``test_view_leak.py``; this module adds the memory side:

- the strip cache stays bounded no matter how far the document scrolls;
- opening a 20k-line document headless stays under a generous
  ``tracemalloc`` ceiling (measured ~40 MB; the bound is deliberately
  loose so shared-host noise cannot flake it).

The slow ``tests/perf/bench_pager.py`` matrix remains the measuring tool
for exact before/after numbers; these tests are the tripwires.
"""

from __future__ import annotations

import tracemalloc

from sase.pager._screen_widgets import PagerBodyScroll
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from tests.pager._app_helpers import body_scroll

_HOST_SIZE = (120, 40)

# Measured ~40 MB on the bench host; 6x headroom keeps host noise out.
_LARGE_DOCUMENT_PEAK_MB = 250


def _plain_document(count: int) -> PagerDocument:
    body = "".join(
        f"line {index:05d} with some trailing words to fill the row\n"
        for index in range(count)
    )
    section = PagerSection(
        identity="file:/tmp/gate-lines.txt",
        title="gate-lines.txt",
        kind="file",
        body=body,
    )
    return PagerDocument(
        sections=(section,), title="gate-lines", origin=PagerOrigin.FILE
    )


def _assert_cache_bounded(scroll: PagerBodyScroll) -> None:
    cache = scroll._strip_cache  # noqa: SLF001 - the bound is the assertion
    assert len(cache) <= cache.maxsize
    assert cache.maxsize >= 512


async def test_strip_cache_stays_bounded_while_scrolling() -> None:
    """Scrolling a 5k-line document never grows the strip cache past its cap."""
    host = SasePager(_plain_document(5000))
    async with host.run_test(size=_HOST_SIZE) as pilot:
        await pilot.pause()
        scroll = body_scroll(host)
        _assert_cache_bounded(scroll)
        for key in ("G", "g", "ctrl+d", "ctrl+d", "G", "g"):
            await pilot.press(key)
            await pilot.pause()
            _assert_cache_bounded(scroll)


async def test_large_document_memory_ceiling() -> None:
    """Opening a 20k-line document headless stays under a generous ceiling."""
    tracemalloc.start()
    try:
        host = SasePager(_plain_document(20000))
        async with host.run_test(size=_HOST_SIZE) as pilot:
            await pilot.pause()
            try:
                await pilot.press("q")
                await pilot.pause()
            except Exception:  # noqa: BLE001 - teardown is best effort
                pass
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak / 1e6 <= _LARGE_DOCUMENT_PEAK_MB
