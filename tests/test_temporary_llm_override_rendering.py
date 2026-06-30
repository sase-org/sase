"""Active-state rendering for the temporary LLM override modal."""

from __future__ import annotations

from sase.ace.tui.modals.temporary_llm_override_modal import TemporaryLLMOverrideModal
from sase.llm_provider.temporary_override import (
    get_active_temporary_override,
    set_temporary_override,
)


def test_render_state_line_until_cleared_shows_no_expiry() -> None:
    """An override with no expiry renders ``until cleared``."""
    set_temporary_override("opus", None, source="test")
    modal = TemporaryLLMOverrideModal()
    line = modal._render_state_line()
    assert "DEFAULT" in line
    assert "override" in line
    assert "until cleared" in line


def test_render_state_line_inactive_uses_resolved_default() -> None:
    """Without an override, the modal shows the resolved default model."""
    assert get_active_temporary_override() is None
    modal = TemporaryLLMOverrideModal()
    line = modal._render_state_line()
    assert "DEFAULT" in line
    assert "default" in line
    assert "(" in line and ")" in line
