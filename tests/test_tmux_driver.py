"""Unit tests for the tmux modifyOtherKeys driver hook."""

from __future__ import annotations

import os
import hashlib
import inspect
import threading

from textual import events
from textual.drivers.linux_driver import LinuxDriver

from sase.tmux_driver import (
    MODIFY_OTHER_KEYS_OFF,
    MODIFY_OTHER_KEYS_ON,
    PasteSafeXTermParser,
    TmuxModifyOtherKeysDriver,
    _tmux_modify_other_keys_active,
    maybe_tmux_driver_class,
)


def _driver_with_capture(monkeypatch) -> tuple[TmuxModifyOtherKeysDriver, list[str]]:
    writes: list[str] = []
    monkeypatch.setattr(
        TmuxModifyOtherKeysDriver, "write", lambda self, data: writes.append(data)
    )
    monkeypatch.setattr(TmuxModifyOtherKeysDriver, "flush", lambda self: None)
    import sase.tmux_driver as mod

    monkeypatch.setattr(mod.LinuxDriver, "start_application_mode", lambda self: None)
    monkeypatch.setattr(mod.LinuxDriver, "stop_application_mode", lambda self: None)
    driver = TmuxModifyOtherKeysDriver.__new__(TmuxModifyOtherKeysDriver)
    return driver, writes


def test_sequences_written_only_when_tmux_set(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1,2,3")
    assert _tmux_modify_other_keys_active() is True
    driver, writes = _driver_with_capture(monkeypatch)
    driver.start_application_mode()
    assert writes == [MODIFY_OTHER_KEYS_ON]
    writes.clear()
    driver.stop_application_mode()
    assert writes == [MODIFY_OTHER_KEYS_OFF]


def test_no_sequences_without_tmux(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    assert _tmux_modify_other_keys_active() is False
    driver, writes = _driver_with_capture(monkeypatch)
    driver.start_application_mode()
    driver.stop_application_mode()
    assert writes == []


def test_headless_base_class_is_untouched() -> None:
    class Headless:
        pass

    assert maybe_tmux_driver_class(Headless) is Headless


def test_linux_base_selects_tmux_driver() -> None:
    import sase.tmux_driver as mod

    assert maybe_tmux_driver_class(mod.LinuxDriver) is TmuxModifyOtherKeysDriver


def test_stop_writes_reset_for_suspend_path(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-9,9,9")
    driver, writes = _driver_with_capture(monkeypatch)
    driver.stop_application_mode()
    assert writes == [MODIFY_OTHER_KEYS_OFF]
    assert os.environ.get("TMUX")


_PASTE = "\x1b[200~line1\x1b[106;5u│ line2\r\x1b[106;5u\tline3\x1b[201~"
_PASTE_TEXT = "line1\n│ line2\r\n\tline3"


def test_paste_safe_parser_keeps_reproduction_bytes_in_one_paste() -> None:
    parsed = list(PasteSafeXTermParser().feed(_PASTE))
    pastes = [event for event in parsed if isinstance(event, events.Paste)]
    keys = [event for event in parsed if isinstance(event, events.Key)]

    assert [event.text for event in pastes] == [_PASTE_TEXT]
    assert keys == []


def test_paste_safe_parser_preserves_event_order_and_chunking() -> None:
    stream = "a" + _PASTE + "\x1b[102;6u"
    parsed = list(PasteSafeXTermParser().feed(stream))
    assert [(type(event), getattr(event, "key", None)) for event in parsed] == [
        (events.Key, "a"),
        (events.Paste, None),
        (events.Key, "ctrl+shift+f"),
    ]
    assert parsed[1].text == _PASTE_TEXT

    parser = PasteSafeXTermParser()
    chunked = [event for char in stream for event in parser.feed(char)]
    chunked_pastes = [event for event in chunked if isinstance(event, events.Paste)]
    assert [event.text for event in chunked_pastes] == [_PASTE_TEXT]
    assert [(type(event), getattr(event, "key", None)) for event in chunked] == [
        (type(event), getattr(event, "key", None)) for event in parsed
    ]


def test_driver_input_thread_uses_paste_safe_parser(monkeypatch) -> None:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, _PASTE.encode())
        driver = TmuxModifyOtherKeysDriver.__new__(TmuxModifyOtherKeysDriver)
        driver.fileno = read_fd
        driver.exit_event = threading.Event()
        driver._debug = False
        messages: list[object] = []

        def collect_message(message: object) -> None:
            messages.append(message)
            driver.exit_event.set()

        monkeypatch.setattr(driver, "process_message", collect_message)

        driver.run_input_thread()

        pastes = [event for event in messages if isinstance(event, events.Paste)]
        keys = [event for event in messages if isinstance(event, events.Key)]
        assert [event.text for event in pastes] == [_PASTE_TEXT]
        assert keys == []
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_input_thread_override_matches_textual_8_0_1() -> None:
    upstream_source = inspect.getsource(LinuxDriver.run_input_thread)
    assert hashlib.sha256(upstream_source.encode()).hexdigest() == (
        "d796af6d69db337d6fa6bd463984f7d17188d991dbb22f60efb92a8a9619507c"
    ), (
        "The run_input_thread override in sase.tmux_driver must be re-synced with upstream before bumping Textual."
    )
