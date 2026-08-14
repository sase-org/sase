"""``AceApp.notify()`` must degrade bad markup instead of crashing.

``Toast.render()`` unconditionally markup-parses a ``notify(markup=True)``
message at render time (not when ``notify()`` is called), so bracket tokens
from agent- or exception-supplied text can crash the render pipeline well
after ``notify()`` itself already returned -- see the
``question_gate_markup_freeze`` plan.

These tests capture what ``AceApp.notify()`` hands to ``App.notify()``
(rather than driving a full ``run_test()`` render pass, which pulls in
unrelated real background loaders) and independently confirm that
``Toast.render()`` succeeds for exactly the notification the app would have
produced.
"""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App
from textual.notifications import Notification
from textual.widgets._toast import Toast

from sase.ace.tui import app as app_module
from sase.ace.tui.app import AceApp


def _capture_super_notify(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake_notify(
        self: App,
        message: str,
        *,
        title: str = "",
        severity: str = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        calls.append(
            {
                "message": message,
                "title": title,
                "severity": severity,
                "timeout": timeout,
                "markup": markup,
            }
        )

    monkeypatch.setattr(App, "notify", _fake_notify)
    return calls


def test_notify_with_bad_markup_degrades_and_renders_literally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_super_notify(monkeypatch)
    app = AceApp(query="!!!", auto_start_axe=False)

    app.notify("bad `[/]` token in this message")

    assert len(calls) == 1
    assert calls[0]["markup"] is False
    assert calls[0]["message"] == "bad `[/]` token in this message"

    notification = Notification(
        calls[0]["message"],
        calls[0]["title"],
        calls[0]["severity"],
        5,
        markup=calls[0]["markup"],
    )
    rendered = Toast(notification).render()
    assert "[/]" in rendered.plain


def test_notify_with_intentional_markup_still_renders_styled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _capture_super_notify(monkeypatch)
    app = AceApp(query="!!!", auto_start_axe=False)

    app.notify("[bold]done[/bold]")

    assert len(calls) == 1
    assert calls[0]["markup"] is True
    assert calls[0]["message"] == "[bold]done[/bold]"

    notification = Notification(
        calls[0]["message"],
        calls[0]["title"],
        calls[0]["severity"],
        5,
        markup=calls[0]["markup"],
    )
    rendered = Toast(notification).render()
    assert rendered.plain == "done"
    assert rendered.spans, "expected the [bold] tag to produce a style span"


def test_notify_records_original_unmodified_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _capture_super_notify(monkeypatch)
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        app_module,
        "record_toast",
        lambda message, *, title, severity: recorded.append(
            {"message": message, "title": title, "severity": severity}
        ),
    )

    app = AceApp(query="!!!", auto_start_axe=False)
    app.notify("bad `[/]` token", title="Oops")
    app.notify("[bold]done[/bold]", title="Styled")

    assert recorded == [
        {"message": "bad `[/]` token", "title": "Oops", "severity": "information"},
        {"message": "[bold]done[/bold]", "title": "Styled", "severity": "information"},
    ]
