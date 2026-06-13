"""Active-state rendering for temporary LLM override lanes."""

from __future__ import annotations

import pytest

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
    assert "PRIMARY" in line
    assert "override" in line
    assert "until cleared" in line


def test_render_state_line_inactive_uses_resolved_default() -> None:
    """Without an override, the modal shows the resolved default model."""
    assert get_active_temporary_override() is None
    modal = TemporaryLLMOverrideModal()
    line = modal._render_state_line()
    assert "PRIMARY" in line
    assert "default" in line
    assert "(" in line and ")" in line


def test_lane_rows_render_default_source_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Idle primary and worker lanes show default source tags."""
    monkeypatch.setattr(
        "sase.ace.tui.modals.temporary_llm_override_modal."
        "get_configured_worker_model_for_primary",
        lambda _provider, _model: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.temporary_llm_override_modal."
        "resolve_effective_worker_provider_model",
        lambda: ("claude", "opus"),
    )
    modal = TemporaryLLMOverrideModal()

    assert "default" in modal._render_lane_row("primary")
    assert "default" in modal._render_lane_row("worker")


def test_lane_rows_render_config_source_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured worker model shows ``config`` in the worker row."""
    monkeypatch.setattr(
        "sase.ace.tui.modals.temporary_llm_override_modal."
        "get_configured_worker_model_for_primary",
        lambda _provider, _model: "codex/gpt-5.5",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.temporary_llm_override_modal."
        "resolve_effective_worker_provider_model",
        lambda: ("codex", "gpt-5.5"),
    )

    modal = TemporaryLLMOverrideModal()

    assert "config" in modal._render_lane_row("worker")


def test_lane_rows_render_follows_primary_source_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker falls through to the active primary override when unset."""
    monkeypatch.setattr(
        "sase.ace.tui.modals.temporary_llm_override_modal."
        "get_configured_worker_model_for_primary",
        lambda _provider, _model: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.temporary_llm_override_modal."
        "resolve_effective_worker_provider_model",
        lambda: ("codex", "o3"),
    )
    set_temporary_override("codex/o3", 3600.0, source="test")
    modal = TemporaryLLMOverrideModal()

    assert "follows primary" in modal._render_lane_row("worker")


def test_lane_rows_render_override_source_tag_for_worker() -> None:
    """An active worker override has the override source tag."""
    set_temporary_override("codex/o3", 3600.0, source="test", role="worker")
    modal = TemporaryLLMOverrideModal()

    row = modal._render_lane_row("worker")
    assert "WORKER" in row
    assert "override" in row
