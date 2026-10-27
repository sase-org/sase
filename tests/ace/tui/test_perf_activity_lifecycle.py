"""Live Textual lifecycle coverage for opt-in prompt activity capture."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from sase.ace.testing import AcePage


async def test_prompt_and_nested_modals_produce_attributable_state(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(tmp_path / "perf.jsonl"))

    class EntryModal(ModalScreen[None]):
        def compose(self) -> ComposeResult:
            yield Input()

    class HelpModal(ModalScreen[None]):
        def compose(self) -> ComposeResult:
            yield Static("help")

    async with AcePage() as page:
        app = page.app
        tracker = app._prompt_activity
        assert tracker is not None
        assert tracker.transitions[0]["state"] == "prompt_idle"
        assert tracker.transitions[0]["app_instance_id"] == app._app_instance_id
        await app.push_screen(EntryModal())
        await page.pause()
        assert tracker.transitions[-1]["state"] == "modal_active"
        await app.push_screen(HelpModal())
        await page.pause()
        assert tracker.transitions[-1]["state"] == "modal_open"
        await app.pop_screen()
        await page.pause()
        assert tracker.transitions[-1]["state"] == "modal_active"
        await app.pop_screen()
        await page.pause()
        assert tracker.transitions[-1]["state"] == "prompt_idle"
        await page.press("space")
        await page.pause()
        assert tracker.transitions[-1]["state"] == "prompt_active"
        await page.press("ctrl+c")
        await page.pause()
        assert tracker.transitions[-1]["state"] == "prompt_idle"
