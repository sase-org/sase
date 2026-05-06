"""Direct tests for ``ChangeSpecList.patch_changespec_row``.

The patch path is the Phase 2 hot-path replacement for full
``update_list`` rebuilds when only one row's mark/selection changes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.message import Message

from sase.ace.testing import make_changespec
from sase.ace.tui.widgets import ChangeSpecList
from sase.ace.tui.widgets._changespec_list_helpers import (
    calculate_entry_display_width,
    format_changespec_option,
)
from sase.core.artifact_wire import ArtifactSummaryWire, ArtifactTypeCountWire
from sase.ace.tui.models.artifact_indicator import ArtifactIndicator


def _wire_widget(monkeypatch: Any) -> tuple[ChangeSpecList, list[Message]]:
    widget = ChangeSpecList()
    posted: list[Message] = []

    def _call_later(callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(widget, "call_later", _call_later)
    monkeypatch.setattr(widget, "post_message", posted.append)
    return widget, posted


def _indicator(total: int = 2) -> ArtifactIndicator:
    return ArtifactIndicator.from_wire(
        ArtifactSummaryWire(
            artifact_id="alpha",
            state="ok",
            total_linked_count=total,
            file_type_counts=[
                ArtifactTypeCountWire(artifact_type="plan", total_count=total)
            ],
        )
    )


def _seed_flat_patch_state(widget: ChangeSpecList, cs: Any) -> None:
    widget.clear_options()
    widget.add_option(
        format_changespec_option(
            cs,
            is_selected=True,
            is_marked=False,
        )
    )
    widget._changespecs = [cs]
    widget._row_entries = [0]
    widget._option_idx_by_changespec_name = {cs.name: 0}
    widget._row_render_ctx = {
        0: {
            "show_hideable": False,
            "show_submitted": False,
            "mentor_stats": None,
            "artifact_indicator": None,
        }
    }
    widget._last_row_signature_by_idx = {}
    widget._row_widths_by_idx = {0: calculate_entry_display_width(cs, is_marked=False)}


def test_patch_returns_false_before_initial_render(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs = make_changespec(name="alpha")
    assert widget.patch_changespec_row(0, cs, selected=True, marked=False) is False


def test_patch_refuses_when_banner_rows_offset_indices(monkeypatch: Any) -> None:
    """The grouped render path always emits banner rows, so the patch
    path's ``option_count == len(self._changespecs)`` gate is never
    satisfied on the CLs tab.  Single-row patches always fall back to a
    full :meth:`update_list` rebuild."""
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    cs1 = make_changespec(name="beta")
    widget.update_list([cs0, cs1], current_idx=0)

    ok = widget.patch_changespec_row(0, cs0, selected=True, marked=True)
    assert ok is False


def test_patch_unmarks_row_falls_back(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    cs1 = make_changespec(name="beta")
    widget.update_list([cs0, cs1], current_idx=0, marked_indices={0})

    ok = widget.patch_changespec_row(0, cs0, selected=True, marked=False)
    assert ok is False


def test_patch_falls_back_when_name_drifts(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    widget.update_list([cs0], current_idx=0)

    other = make_changespec(name="zulu")  # different name at same idx
    ok = widget.patch_changespec_row(0, other, selected=True, marked=False)
    assert ok is False


def test_patch_falls_back_when_idx_out_of_range(monkeypatch: Any) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    widget.update_list([cs0], current_idx=0)

    ok = widget.patch_changespec_row(5, cs0, selected=True, marked=False)
    assert ok is False


def test_patch_records_optimal_target_width(monkeypatch: Any) -> None:
    """The cached target width is what bounds future patch attempts."""
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    widget.update_list([cs0], current_idx=0)

    assert widget._target_width > 0
    # Name index map populated.
    assert widget._option_idx_by_changespec_name == {"alpha": 0}


def test_patch_renders_artifact_indicator_and_updates_signature(
    monkeypatch: Any,
) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    indicator = _indicator()
    _seed_flat_patch_state(widget, cs0)
    widget._target_width = 999

    ok = widget.patch_changespec_row(
        0,
        cs0,
        selected=True,
        marked=False,
        artifact_indicator=indicator,
    )

    assert ok is True
    prompt = widget.get_option_at_index(0).prompt
    assert "art 2 plan2" in prompt.plain  # type: ignore[union-attr]
    assert widget._last_row_signature_by_idx[0][-1] == indicator.render_signature


def test_patch_falls_back_when_artifact_indicator_exceeds_cached_width(
    monkeypatch: Any,
) -> None:
    widget, _ = _wire_widget(monkeypatch)
    cs0 = make_changespec(name="alpha")
    _seed_flat_patch_state(widget, cs0)
    widget._target_width = widget._row_widths_by_idx[0]

    ok = widget.patch_changespec_row(
        0,
        cs0,
        selected=True,
        marked=False,
        artifact_indicator=_indicator(total=20),
    )

    assert ok is False
