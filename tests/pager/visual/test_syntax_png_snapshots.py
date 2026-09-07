"""PNG golden tests for file-aware pager syntax highlighting."""

from __future__ import annotations

import pytest

from sase.ace.testing.wait import wait_for
from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection, RawSourceSpec
from sase.pager.screen import PagerScreen
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_SIZES = [(120, 40), (60, 30)]


class _SnapshotPager(SasePager):
    """Apply the snapshot theme before the pager screen mounts.

    Runtime ``app.theme = ...`` after first paint races syntax restyle and
    produces non-deterministic goldens. Setting the theme here means the
    first syntax pass already uses the intended palette.
    """

    def __init__(
        self,
        document: PagerDocument,
        *,
        theme_name: str | None = None,
    ) -> None:
        super().__init__(document)
        self._theme_name = theme_name

    def on_mount(self) -> None:
        if self._theme_name is not None:
            self.theme = self._theme_name
        super().on_mount()


class _SvgExport:
    def __init__(self, app: SasePager) -> None:
        self._app = app

    def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
        return self._app.export_screenshot(title=title, simplify=simplify)


def _pager_screen(app: SasePager) -> PagerScreen:
    screen = app.screen
    assert isinstance(screen, PagerScreen)
    return screen


def _python_document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body=(
            'path = "src/sase/cli_pager.py"\n'
            "# Quiet comment beside a string link.\n"
            "def open_pager() -> None:\n"
            "    return None\n"
        ),
        raw_source=RawSourceSpec(language="python"),
    )
    return PagerDocument(
        sections=(section,),
        title="demo.py",
        origin=PagerOrigin.FILE,
    )


def _markdown_document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/note.md",
        title="note.md",
        kind="file",
        body=(
            "---\n"
            "title: Demo\n"
            "---\n"
            "\n"
            "# Heading\n"
            "\n"
            "See *emphasis* and `code`.\n"
            "\n"
            "```python\n"
            'print("hi")\n'
            "value = 3\n"
            "```\n"
        ),
        raw_source=RawSourceSpec(language="markdown"),
    )
    return PagerDocument(
        sections=(section,),
        title="note.md",
        origin=PagerOrigin.FILE,
    )


def _diff_document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/change.diff",
        title="change.diff",
        kind="file",
        body=(
            "diff --git a/old b/new\n"
            "--- a/old\n"
            "+++ b/new\n"
            "@@ -1,1 +1,1 @@\n"
            "-removed line\n"
            "+added line\n"
        ),
        raw_source=RawSourceSpec(language="diff"),
    )
    return PagerDocument(
        sections=(section,),
        title="change.diff",
        origin=PagerOrigin.FILE,
    )


async def _wait_for_syntax(pilot: object, app: SasePager, identity: str) -> None:
    screen = _pager_screen(app)
    await wait_for(
        pilot,
        lambda: identity in screen._syntax_prepared and not screen._syntax_pass_running,
    )


@pytest.mark.parametrize("size", _SIZES)
@pytest.mark.parametrize("light", [False, True])
@pytest.mark.parametrize("state", ["python", "markdown", "diff", "search"])
async def test_syntax_png_snapshot(
    pager_png_visual: AcePngSnapshotFixture,
    size: tuple[int, int],
    light: bool,
    state: str,
) -> None:
    documents = {
        "python": _python_document(),
        "markdown": _markdown_document(),
        "diff": _diff_document(),
        "search": _python_document(),
    }
    identities = {
        "python": "file:/tmp/demo.py",
        "markdown": "file:/tmp/note.md",
        "diff": "file:/tmp/change.diff",
        "search": "file:/tmp/demo.py",
    }
    document = documents[state]
    theme_label = "light" if light else "dark"
    app = _SnapshotPager(
        document,
        theme_name="textual-light" if light else None,
    )
    async with app.run_test(size=size) as pilot:
        await _wait_for_syntax(pilot, app, identities[state])
        if state == "search":
            await pilot.press("slash")
            for character in "comment":
                await pilot.press(character)
            await pilot.press("enter")
        await pilot.pause()
        pager_png_visual.assert_page_png(
            _SvgExport(app),
            f"syntax_{state}_{theme_label}_{size[0]}x{size[1]}",
            title=f"SasePager: {state} syntax ({theme_label})",
        )
