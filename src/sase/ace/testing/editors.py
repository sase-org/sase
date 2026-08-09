"""Focused text-editor test harnesses for ace widgets."""

from collections.abc import Sequence
from typing import Any

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from . import settle as settle_helpers


class _PromptTestApp(App[None]):
    """Minimal app hosting a single PromptTextArea for isolation testing.

    Implements the misspellings provider surface in memory so widget tests can
    seed sticky-misspelling state without touching ``~/.sase``.
    """

    def __init__(self, misspellings: Sequence[str] = ()) -> None:
        super().__init__()
        self._misspelled_words: frozenset[str] = frozenset(
            word.casefold() for word in misspellings
        )
        self._misspellings_generation_count = 0

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")

    def misspelled_words(self) -> frozenset[str]:
        return self._misspelled_words

    def misspellings_generation(self) -> int:
        return self._misspellings_generation_count

    def record_misspelling(self, word: str) -> None:
        key = word.casefold()
        if key and key not in self._misspelled_words:
            self._misspelled_words = self._misspelled_words | {key}
            self._misspellings_generation_count += 1

    def allow_word(self, word: str) -> None:
        key = word.casefold()
        if key in self._misspelled_words:
            self._misspelled_words = self._misspelled_words - {key}
            self._misspellings_generation_count += 1

    def forget_misspelling(self, word: str) -> None:
        key = word.casefold()
        if key in self._misspelled_words:
            self._misspelled_words = self._misspelled_words - {key}
            self._misspellings_generation_count += 1

    def warm_misspellings(self) -> None:
        return None


class PromptPage:
    """Async context manager wrapping PromptTextArea + Pilot for fluent testing.

    Absorbs the ``_TestApp`` + ``PromptTextArea`` boilerplate that every
    normal-mode test file duplicates::

        async with PromptPage("hello world", cursor=(0, 5)) as page:
            await page.press("d", "w")
            assert page.text == "hello"
    """

    def __init__(
        self,
        text: str = "",
        cursor: tuple[int, int] = (0, 0),
        mode: str = "normal",
        size: tuple[int, int] | None = None,
        misspellings: Sequence[str] = (),
    ) -> None:
        self._init_text = text
        self._init_cursor = cursor
        self._init_mode = mode
        self._size = size
        self._misspellings = misspellings
        self._app: _PromptTestApp | None = None
        self._ta: PromptTextArea | None = None
        self._pilot: Any = None
        self._pilot_cm: Any = None

    async def __aenter__(self) -> "PromptPage":
        self._app = _PromptTestApp(self._misspellings)
        if self._size is not None:
            self._pilot_cm = self._app.run_test(size=self._size)
        else:
            self._pilot_cm = self._app.run_test()
        self._pilot = await self._pilot_cm.__aenter__()
        self._ta = self._app.query_one("#ta", PromptTextArea)
        self._ta.text = self._init_text
        self._ta.cursor_location = self._init_cursor
        if self._init_mode == "normal":
            self._ta._enter_normal_mode()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._pilot_cm is not None:
            await self._pilot_cm.__aexit__(exc_type, exc_val, exc_tb)

    async def press(self, *keys: str) -> None:
        """Press one or more keys via the pilot."""
        await self._pilot.press(*keys)

    async def pause(self) -> None:
        """Let the app process events and render a frame."""
        await settle_helpers.settle_pilot(self._pilot)

    @property
    def text(self) -> str:
        """Get the current text content."""
        assert self._ta is not None
        return self._ta.text

    @text.setter
    def text(self, value: str) -> None:
        """Set the text content."""
        assert self._ta is not None
        self._ta.text = value

    @property
    def cursor(self) -> tuple[int, int]:
        """Get the current cursor position."""
        assert self._ta is not None
        return self._ta.cursor_location

    @cursor.setter
    def cursor(self, value: tuple[int, int]) -> None:
        """Set the cursor position."""
        assert self._ta is not None
        self._ta.cursor_location = value

    @property
    def mode(self) -> str:
        """Get the current vim mode."""
        assert self._ta is not None
        return self._ta._vim_mode

    @property
    def ta(self) -> PromptTextArea:
        """Direct access to the underlying PromptTextArea widget."""
        assert self._ta is not None
        return self._ta


class _VimEditorTestApp(App[None]):
    """Minimal app hosting a single VimTextArea-family widget for testing."""

    def __init__(
        self,
        widget_cls: type[VimTextArea],
        text: str,
    ) -> None:
        super().__init__()
        self._widget_cls = widget_cls
        self._text = text
        self.submitted: list[str] = []

    def compose(self) -> ComposeResult:
        yield self._widget_cls(self._text, id="ed")

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        self.submitted.append(event.value)


class VimEditorPage:
    """Async context manager wrapping a bare VimTextArea (or subclass) + Pilot.

    The direct counterpart to :class:`PromptPage` for the shared base widgets::

        async with VimEditorPage("hello world", cursor=(0, 5)) as page:
            await page.press("d", "w")
            assert page.text == "hello"

    Pass ``widget_cls=SingleLineVimTextArea`` to exercise the single-line
    variant. Unlike ``PromptPage`` there is no parent prompt bar, so the host
    hooks fall back to their inert defaults (mode is shown on the widget border).
    """

    def __init__(
        self,
        text: str = "",
        cursor: tuple[int, int] = (0, 0),
        mode: str = "normal",
        size: tuple[int, int] | None = None,
        widget_cls: type[VimTextArea] = VimTextArea,
    ) -> None:
        self._init_text = text
        self._init_cursor = cursor
        self._init_mode = mode
        self._size = size
        self._widget_cls = widget_cls
        self._app: _VimEditorTestApp | None = None
        self._ta: VimTextArea | None = None
        self._pilot: Any = None
        self._pilot_cm: Any = None

    async def __aenter__(self) -> "VimEditorPage":
        self._app = _VimEditorTestApp(self._widget_cls, self._init_text)
        if self._size is not None:
            self._pilot_cm = self._app.run_test(size=self._size)
        else:
            self._pilot_cm = self._app.run_test()
        self._pilot = await self._pilot_cm.__aenter__()
        self._ta = self._app.query_one("#ed", self._widget_cls)
        self._ta.text = self._init_text
        self._ta.cursor_location = self._init_cursor
        if self._init_mode == "normal":
            self._ta._enter_normal_mode()
        self._ta.focus()
        return self

    @property
    def submitted(self) -> list[str]:
        """Values captured from ``SingleLineVimTextArea.Submitted`` messages."""
        assert self._app is not None
        return self._app.submitted

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._pilot_cm is not None:
            await self._pilot_cm.__aexit__(exc_type, exc_val, exc_tb)

    async def press(self, *keys: str) -> None:
        """Press one or more keys via the pilot."""
        await self._pilot.press(*keys)

    async def pause(self) -> None:
        """Let the app process events and render a frame."""
        await settle_helpers.settle_pilot(self._pilot)

    @property
    def text(self) -> str:
        """Get the current text content."""
        assert self._ta is not None
        return self._ta.text

    @text.setter
    def text(self, value: str) -> None:
        assert self._ta is not None
        self._ta.text = value

    @property
    def cursor(self) -> tuple[int, int]:
        """Get the current cursor position."""
        assert self._ta is not None
        return self._ta.cursor_location

    @cursor.setter
    def cursor(self, value: tuple[int, int]) -> None:
        assert self._ta is not None
        self._ta.cursor_location = value

    @property
    def mode(self) -> str:
        """Get the current vim mode."""
        assert self._ta is not None
        return self._ta._vim_mode

    @property
    def ta(self) -> VimTextArea:
        """Direct access to the underlying widget."""
        assert self._ta is not None
        return self._ta
