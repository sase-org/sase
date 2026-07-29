"""Tests for ACE's unified clipboard-delivery seam."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static, TextArea

from sase.ace.tui.actions.clipboard._delivery import (
    OSC52_MAX_BASE64_BYTES,
    CopyDeliveryOutcome,
    deliver_copy,
    schedule_copy_delivery,
)
from sase.ace.tui.modals.copy_fallback_modal import CopyFallbackModal


@dataclass
class _FakeApp:
    _driver: object | None = field(default_factory=object)
    osc52_values: list[str] = field(default_factory=list)
    screens: list[object] = field(default_factory=list)

    def copy_to_clipboard(self, value: str) -> None:
        self.osc52_values.append(value)

    def push_screen(self, screen: object) -> None:
        self.screens.append(screen)


@dataclass
class _FakeOwner:
    app: _FakeApp = field(default_factory=_FakeApp)
    notifications: list[tuple[str, str]] = field(default_factory=list)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


class _FallbackTestApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("host")


@pytest.mark.asyncio
async def test_verified_transport_wins_over_osc52(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner()
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda value: value == "content",
    )

    outcome = await deliver_copy(owner, "content", copied_label="commit SHA")

    assert outcome is CopyDeliveryOutcome.VERIFIED
    assert owner.app.osc52_values == ["content"]
    assert owner.notifications == [("Copied commit SHA", "information")]
    assert owner.app.screens == []


@pytest.mark.asyncio
async def test_osc52_only_outcome_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner()
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda _value: False,
    )

    outcome = await deliver_copy(owner, "content", copied_label="plan path")

    assert outcome is CopyDeliveryOutcome.OSC52_ONLY
    assert owner.notifications == [("Copied plan path (OSC 52)", "information")]


@pytest.mark.asyncio
async def test_transport_exception_still_allows_osc52(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner()

    def fail(_value: str) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        fail,
    )

    outcome = await deliver_copy(owner, "content", copied_label="prompt")

    assert outcome is CopyDeliveryOutcome.OSC52_ONLY
    assert owner.app.osc52_values == ["content"]


@pytest.mark.asyncio
async def test_large_payload_skips_osc52_and_opens_exact_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner()
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda _value: False,
    )
    content = "x" * (OSC52_MAX_BASE64_BYTES + 1)

    outcome = await deliver_copy(owner, content, copied_label="large transcript")

    assert outcome is CopyDeliveryOutcome.FAILED
    assert owner.app.osc52_values == []
    assert len(owner.app.screens) == 1
    fallback = owner.app.screens[0]
    assert isinstance(fallback, CopyFallbackModal)
    assert fallback.content == content
    assert owner.notifications == []


@pytest.mark.asyncio
async def test_missing_driver_opens_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _FakeOwner(app=_FakeApp(_driver=None))
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda _value: False,
    )

    outcome = await deliver_copy(owner, "recover me", copied_label="text")

    assert outcome is CopyDeliveryOutcome.FAILED
    assert isinstance(owner.app.screens[0], CopyFallbackModal)
    assert owner.app.screens[0].content == "recover me"


@pytest.mark.asyncio
async def test_toast_and_silent_failure_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda _value: False,
    )
    toast_owner = _FakeOwner(app=_FakeApp(_driver=None))
    silent_owner = _FakeOwner(app=_FakeApp(_driver=None))

    toast = await deliver_copy(
        toast_owner,
        "text",
        copied_label="yanked text",
        on_failure="toast",
    )
    silent = await deliver_copy(
        silent_owner,
        "text",
        copied_label="best effort",
        on_failure="silent",
    )

    assert toast is CopyDeliveryOutcome.FAILED
    assert toast_owner.notifications == [("No clipboard transport available", "error")]
    assert toast_owner.app.screens == []
    assert silent is CopyDeliveryOutcome.FAILED
    assert silent_owner.notifications == []
    assert silent_owner.app.screens == []


@pytest.mark.asyncio
async def test_scheduled_copy_opens_selectable_fallback_with_exact_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FallbackTestApp()
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda _value: False,
    )

    async with app.run_test() as pilot:

        def fail_osc52(_value: str) -> None:
            raise RuntimeError("terminal has no OSC 52")

        monkeypatch.setattr(app, "copy_to_clipboard", fail_osc52)
        task = schedule_copy_delivery(
            app,
            "exact fallback text",
            copied_label="text",
            task_name="test-fallback-copy",
        )
        assert task is not None
        await task
        await pilot.pause()

        assert isinstance(app.screen, CopyFallbackModal)
        text_area = app.screen.query_one("#copy-fallback-text", TextArea)
        assert text_area.text == "exact fallback text"

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, CopyFallbackModal)
