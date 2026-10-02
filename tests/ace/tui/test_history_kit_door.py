"""Guard tests for the public history kit (phase `history-service`).

ACE renders history presentation only through
:mod:`sase.pager.history_kit`: no module under ``src/sase/ace/`` may
import the pager private history modules directly. The kit itself is
a thin re-export facade, so this also pins a sample of its names to
their pager originals.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Private pager history modules ACE must never import directly. The
#: promoted :mod:`sase.pager._timeline_picker_rows` module is the one
#: sanctioned exception: the modal and the kit import its public names.
_FORBIDDEN_ACE_IMPORTS = frozenset(
    {
        "sase.pager._time_band",
        "sase.pager._time_band_model",
        "sase.pager._time_band_render",
        "sase.pager._time_band_render_band",
        "sase.pager._time_band_render_meaning",
        "sase.pager._time_band_render_shared",
        "sase.pager._time_band_vocab",
        "sase.pager._chrome_history",
        "sase.pager._timeline_picker",
        "sase.pager.history.diff",
        "sase.pager.history.moment",
        "sase.pager.history.models",
        "sase.pager.history.styles",
        "sase.pager.history.timeline",
    }
)


def _ace_sources() -> list[Path]:
    root = Path(__file__).resolve().parents[3] / "src" / "sase" / "ace"
    return sorted(root.rglob("*.py"))


def test_ace_imports_history_presentation_only_through_kit() -> None:
    """AST guard: ACE never imports pager private history modules directly."""
    offenders: list[str] = []
    for path in _ace_sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in _FORBIDDEN_ACE_IMPORTS:
                    offenders.append(f"{path}:{node.lineno}: from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_ACE_IMPORTS:
                        offenders.append(f"{path}:{node.lineno}: import {alias.name}")
    assert offenders == []


def test_history_kit_reexports_pager_originals() -> None:
    """The kit is a facade: its names are the pager originals."""
    import sase.pager._time_band as time_band
    import sase.pager._chrome_history as chrome_history
    import sase.pager._timeline_picker_rows as picker_rows
    import sase.pager.history.diff as history_diff
    import sase.pager.history.moment as history_moment
    import sase.pager.history.styles as history_styles
    import sase.memory.history.timeline_picker as timeline_picker
    import sase.memory.history.pager_provider_timelines as timelines
    import sase.memory.history.vocabulary as vocabulary
    from sase.pager import history_kit as kit

    assert kit.render_sparkline is time_band.render_sparkline
    assert kit.render_scrubber is time_band.render_scrubber
    assert kit.format_age is time_band.format_age
    assert kit.chrome_row_budget is time_band.chrome_row_budget
    assert kit.render_time_band is time_band.render_time_band
    assert kit.build_time_band_data is time_band.build_time_band_data
    assert kit.history_badge is chrome_history.history_badge
    assert kit.history_context is chrome_history.history_context
    assert kit.honest_chip is chrome_history.honest_chip
    assert kit.time_verbs_for_moment is chrome_history.time_verbs_for_moment
    assert kit.picker_columns is picker_rows.picker_columns
    assert kit.format_picker_row is picker_rows.format_picker_row
    assert kit.PickerColumns is picker_rows.PickerColumns
    assert kit.build_diff_body is history_diff.build_diff_body
    assert kit.diff_endpoints is history_diff.diff_endpoints
    assert kit.build_moment is history_moment.build_moment
    assert kit.moment_for_state is history_moment.moment_for_state
    assert kit.step_target is history_moment.step_target
    assert kit.boundary_notice is history_moment.boundary_notice
    assert kit.canonical_ordinal is history_moment.canonical_ordinal
    assert kit.history_styles_for_theme is history_styles.history_styles_for_theme
    assert kit.build_picker_rows is timeline_picker.build_picker_rows
    assert kit.visible_ordinals_for_timeline is timelines.visible_ordinals_for_timeline
    assert kit.glyph_for is vocabulary.glyph_for
    assert kit.label_for is vocabulary.label_for
    # Every kit export resolves: no stale re-export survives a pager move.
    assert len(kit.__all__) > 30


def test_timeline_picker_modal_uses_promoted_rows() -> None:
    """The modal formats rows through the promoted public module."""
    import sase.pager._timeline_picker as modal
    import sase.pager._timeline_picker_rows as rows

    assert modal.format_picker_row is rows.format_picker_row
    assert modal.picker_columns is rows.picker_columns
