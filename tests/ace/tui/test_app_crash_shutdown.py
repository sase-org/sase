"""``AceApp._handle_exception`` must never leave the terminal wedged.

Textual's own crash path (``App._fatal_error``) can itself raise while
rendering ``show_locals=True`` tracebacks of a partially constructed object
(e.g. a ``Selection`` whose markup parsing failed mid-``__init__``, leaving
``Option.__rich_repr__`` broken). When that happens, ``_close_messages_no_wait``
is never reached, the driver stays in raw mode, and the TUI hangs with no
traceback logged anywhere -- see the ``question_gate_markup_freeze`` plan.
"""

from __future__ import annotations

import logging

import pytest
from textual.app import App

from sase.ace.tui.app import AceApp


def test_handle_exception_logs_and_force_closes_when_super_raises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    close_calls: list[None] = []

    def _boom_super(self: App, error: Exception) -> None:
        raise AttributeError("'Selection' object has no attribute '_prompt'")

    monkeypatch.setattr(App, "_handle_exception", _boom_super)

    app = AceApp(query="!!!", auto_start_axe=False)
    monkeypatch.setattr(
        app, "_close_messages_no_wait", lambda: close_calls.append(None)
    )

    original_error = RuntimeError("auto closing tag ('[/]') has nothing to close")

    with caplog.at_level(logging.ERROR, logger="sase.ace.tui.app"):
        app._handle_exception(original_error)

    assert close_calls == [None]
    assert any(
        record.levelno == logging.ERROR
        and record.exc_info is not None
        and record.exc_info[1] is original_error
        for record in caplog.records
    )


def test_handle_exception_success_path_does_not_double_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close_calls: list[None] = []

    def _succeed_super(self: App, error: Exception) -> None:
        # Mirrors real Textual behavior: the crash path closes the message
        # pump itself when it does *not* raise.
        self._close_messages_no_wait()

    monkeypatch.setattr(App, "_handle_exception", _succeed_super)

    app = AceApp(query="!!!", auto_start_axe=False)
    monkeypatch.setattr(
        app, "_close_messages_no_wait", lambda: close_calls.append(None)
    )

    app._handle_exception(RuntimeError("boom"))

    assert close_calls == [None]
