"""Decode bracketed pastes and request modifyOtherKeys mode 2 inside tmux.

Only the real Linux terminal driver is wrapped. Its paste-safe parser is used
in every session; the modifyOtherKeys request is sent only when ``TMUX`` is
set. Headless and test drivers are untouched. The module imports nothing but
the stdlib and the Textual Linux driver so the pager cold-path import diet is
unaffected.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

try:
    from textual.drivers.linux_driver import (
        LinuxDriver,
        Message,
        ParseError,
        XTermParser,
        getincrementaldecoder,
        loop_last,
        selectors,
    )
except Exception:  # pragma: no cover - non-Linux platforms
    LinuxDriver = None  # type: ignore[assignment,misc]


MODIFY_OTHER_KEYS_ON = "\x1b[>4;2m"
MODIFY_OTHER_KEYS_OFF = "\x1b[>4;0m"


def _tmux_modify_other_keys_active() -> bool:
    """Return whether the CSI-u request should be sent."""
    try:
        return bool(os.environ.get("TMUX"))
    except Exception:
        return False


if LinuxDriver is not None:
    from sase.bracketed_paste import BracketedPasteNormalizer

    class PasteSafeXTermParser(XTermParser):
        """XTerm parser that normalizes bracketed-paste bodies first."""

        def __init__(self, debug: bool = False) -> None:
            super().__init__(debug)
            self._paste_normalizer = BracketedPasteNormalizer()

        def feed(self, data: str) -> Iterable[Message]:
            if data == "":
                yield from super().feed(data)
                return
            forwarded = self._paste_normalizer.feed(data)
            if forwarded:
                yield from super().feed(forwarded)

    class TmuxModifyOtherKeysDriver(LinuxDriver):  # type: ignore[valid-type,misc]
        """Linux driver with paste-safe parsing and tmux CSI-u support."""

        def run_input_thread(self) -> None:
            """Wait for input and dispatch events with the paste-safe parser."""
            selector = selectors.SelectSelector()
            selector.register(self.fileno, selectors.EVENT_READ)

            fileno = self.fileno
            EVENT_READ = selectors.EVENT_READ

            parser = PasteSafeXTermParser(self._debug)
            feed = parser.feed
            tick = parser.tick

            utf8_decoder = getincrementaldecoder("utf-8")().decode
            decode = utf8_decoder
            read = os.read

            def process_selector_events(
                selector_events: list[tuple[selectors.SelectorKey, int]],
                final: bool = False,
            ) -> None:
                """Process events from selector."""
                for last, (_selector_key, mask) in loop_last(selector_events):
                    if mask & EVENT_READ:
                        unicode_data = decode(
                            read(fileno, 1024 * 4), final=final and last
                        )
                        if not unicode_data:
                            # This can occur if the stdin is piped
                            break
                        for event in feed(unicode_data):
                            self.process_message(event)
                for event in tick():
                    self.process_message(event)

            try:
                while not self.exit_event.is_set():
                    process_selector_events(selector.select(0.1))
                selector.unregister(self.fileno)
                process_selector_events(selector.select(0.1), final=True)

            finally:
                selector.close()
                try:
                    for event in feed(""):
                        pass
                except (EOFError, ParseError):
                    pass

        def start_application_mode(self) -> None:
            super().start_application_mode()
            if not _tmux_modify_other_keys_active():
                return
            try:
                self.write(MODIFY_OTHER_KEYS_ON)
                self.flush()
            except Exception:
                pass

        def stop_application_mode(self) -> None:
            if _tmux_modify_other_keys_active():
                try:
                    self.write(MODIFY_OTHER_KEYS_OFF)
                    self.flush()
                except Exception:
                    pass
            super().stop_application_mode()

else:  # pragma: no cover - non-Linux platforms

    class PasteSafeXTermParser:  # type: ignore[no-redef]
        """Placeholder when the Linux parser is unavailable."""

    class TmuxModifyOtherKeysDriver:  # type: ignore[no-redef]
        """Placeholder when the Linux driver is unavailable."""


def maybe_tmux_driver_class(base: type) -> type:
    """Return the tmux-aware driver when *base* is the Linux driver."""
    try:
        if LinuxDriver is not None and base is LinuxDriver:
            return TmuxModifyOtherKeysDriver
    except Exception:
        pass
    return base


__all__ = [
    "MODIFY_OTHER_KEYS_OFF",
    "MODIFY_OTHER_KEYS_ON",
    "PasteSafeXTermParser",
    "TmuxModifyOtherKeysDriver",
    "maybe_tmux_driver_class",
]
