"""Tests for the CL info-panel grouping badge.

The badge is always shown on the CLs tab — there is no opt-out mode
since FLAT was removed.  An empty label still hides the badge so test
fixtures that don't seed a label don't render a stray ``[group:]``.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.changespec_info_panel import ChangeSpecInfoPanel


def _collect_text(panel: ChangeSpecInfoPanel) -> str:
    """Build the panel content without going through Textual's ``update`` path.

    ``Static.update`` walks the active-app context, which raises outside
    a mounted Textual app.  ``_build_content`` returns the rendered
    :class:`rich.text.Text` directly, so all assertions can read its
    plain text.
    """
    return panel._build_content().plain


def test_default_state_shows_by_project_badge() -> None:
    panel = ChangeSpecInfoPanel()
    plain = _collect_text(panel)
    assert "group:" in plain
    assert "by project" in plain


def test_empty_label_hides_badge() -> None:
    """An explicit empty label still hides the badge."""
    panel = ChangeSpecInfoPanel()
    with patch.object(panel, "_refresh_content"):
        panel.update_grouping_mode("")
    assert panel._grouping_label == ""
    assert "group:" not in _collect_text(panel)


def test_by_project_label_renders_badge_with_key_hint() -> None:
    panel = ChangeSpecInfoPanel()
    panel._grouping_label = "by project"
    plain = _collect_text(panel)
    assert "group:" in plain
    assert "by project" in plain
    # The configured key for ``cycle_grouping_mode`` is shown in parens
    # so the user can discover the binding without opening the help modal.
    assert "(o)" in plain


def test_by_status_label_renders_badge() -> None:
    panel = ChangeSpecInfoPanel()
    panel._grouping_label = "by status"
    plain = _collect_text(panel)
    assert "group:" in plain
    assert "by status" in plain
