"""Tests for the CL info-panel grouping badge added in Phase 3.

The badge stays hidden in ``FLAT`` (the historical default) so the
already-dense top bar is not cluttered before the user opts in to
grouping.  Non-flat labels render the badge plus the configured cycle
key so ``o`` is discoverable.
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


def test_default_state_hides_grouping_badge() -> None:
    panel = ChangeSpecInfoPanel()
    assert "group:" not in _collect_text(panel)


def test_flat_label_normalizes_to_empty_and_hides_badge() -> None:
    """``FLAT`` (literal or empty) keeps the badge off."""
    panel = ChangeSpecInfoPanel()
    # Stub out the post-update refresh so we don't hit the active-app
    # context — the test only cares about the normalization.
    with patch.object(panel, "_refresh_content"):
        panel.update_grouping_mode("flat")
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
