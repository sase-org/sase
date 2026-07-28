"""Family detail-panel section rendering tests."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_family import (
    FAMILY_PROMPT_SECTION_ID,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import build_header_text
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel, plain_of


def test_shared_collapsed_level_maps_family_to_bounded_previews(
    tmp_path: Path,
) -> None:
    root, _child = make_family(tmp_path)
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
    )
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 12" in plain
    assert "plan xprompt line 15" not in plain
    assert "▾ AGENT PROMPT\n" in plain
    assert "plan prompt line 12" in plain
    assert "plan prompt line 15" not in plain
    assert "▾ AGENT REPLY · 2\n" in plain
    assert "plan reply line 1" not in plain
    assert "plan reply line 6" in plain


def test_expanded_family_sections_render_bounded_previews(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.EXPANDED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.EXPANDED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 12" in plain
    assert "… +3 more lines" in plain
    assert "plan xprompt line 15" not in plain
    assert "plan prompt line 12" in plain
    assert "plan prompt line 15" not in plain
    assert "plan reply line 1" not in plain
    assert "plan reply line 6" in plain
    assert "… +2 earlier lines" in plain


def test_exhaustive_shared_level_clamps_to_full_family_view(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    full_panel = FakePromptPanel()
    full_header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.FULLY_EXPANDED,
    )
    full_panel._update_family_display(
        root,
        full_header,
        error,
        panel_level=FoldLevel.FULLY_EXPANDED,
        section_fold_overrides={},
    )
    exhaustive_panel = FakePromptPanel()
    exhaustive_header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.EXHAUSTIVE,
    )
    exhaustive_panel._update_family_display(
        root,
        exhaustive_header,
        error,
        panel_level=FoldLevel.EXHAUSTIVE,
        section_fold_overrides={},
    )

    assert plain_of(exhaustive_panel.captured[-1]) == plain_of(full_panel.captured[-1])


def test_fully_expanded_family_sections_preserve_full_content(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.FULLY_EXPANDED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.FULLY_EXPANDED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▼ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 15" in plain
    assert "plan prompt line 15" in plain
    assert "plan reply line 1" in plain
    assert "code reply line 1" in plain


def test_family_omits_empty_xprompt_and_prompt_sections(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    artifacts_dir = Path(root.artifacts_dir or "")
    (artifacts_dir / "raw_xprompt.md").unlink()
    (artifacts_dir / "01_prompt.md").unlink()
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "AGENT XPROMPT" not in plain
    assert "No xprompt file found." not in plain
    assert "AGENT PROMPT" not in plain
    assert "No prompt file found." not in plain
    assert "▾ AGENT REPLY · 2\n" in plain


def test_family_keeps_pending_reply_state(tmp_path: Path) -> None:
    root, child = make_family(tmp_path)
    Path(root.response_path or "").unlink()
    Path(child.response_path or "").unlink()
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
    )

    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides={},
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT REPLY · 2\n" in plain
    assert plain.count("No response content yet.") == 2


def test_family_section_override_wins_over_collapsed_panel(
    tmp_path: Path,
) -> None:
    root, _child = make_family(tmp_path)

    overrides = {FAMILY_PROMPT_SECTION_ID: FoldLevel.FULLY_EXPANDED}
    panel = FakePromptPanel()
    header, error = build_header_text(
        root,
        cheap=True,
        lane_fold_level=FoldLevel.COLLAPSED,
        lane_section_fold_overrides=overrides,
    )
    panel._update_family_display(
        root,
        header,
        error,
        panel_level=FoldLevel.COLLAPSED,
        section_fold_overrides=overrides,
    )
    plain = plain_of(panel.captured[-1])

    assert "▾ AGENT XPROMPT\n" in plain
    assert "plan xprompt line 12" in plain
    assert "plan xprompt line 15" not in plain
    assert "▼ AGENT PROMPT\n" in plain
    assert "plan prompt line 15" in plain
    assert "▾ AGENT REPLY · 2\n" in plain
