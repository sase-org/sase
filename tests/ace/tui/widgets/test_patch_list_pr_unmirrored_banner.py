"""Tests for the Patches pane's ``· M remote-only`` banner chip."""

from __future__ import annotations

from typing import Any

from sase.ace.patch import Patch
from sase.ace.tui.models.patch_groups import PatchGroupingMode, PatchGroupRow
from sase.ace.tui.widgets import PatchList
from sase.ace.tui.widgets._patch_list_banner import (
    banner_natural_width,
    format_patch_banner_option,
)
from sase.ace.tui.widgets.patch_list import _BANNER_ROW


def _cs(name: str, *, project: str = "sase") -> Patch:
    return Patch(
        name=name,
        description="",
        parent=None,
        cl=None,
        status="WIP",
        file_path=f"/sase/projects/{project}/{project}.sase",
        line_number=1,
    )


def _l0_group(label: str, *, indices: tuple[int, ...] = (0,)) -> PatchGroupRow:
    return PatchGroupRow(level=0, group_key=(label,), patch_indices=indices)


def _l1_group(label: str, *, indices: tuple[int, ...] = (0,)) -> PatchGroupRow:
    return PatchGroupRow(level=1, group_key=("project", label), patch_indices=indices)


def _rendered_text(option: Any) -> str:
    return option.prompt.plain  # type: ignore[union-attr]


def test_l0_banner_gets_remote_only_suffix_when_count_is_known() -> None:
    group = _l0_group("sase")

    option = format_patch_banner_option(
        group,
        width=80,
        sequence=0,
        pr_unmirrored_counts={"sase": 3},
    )

    assert "3 remote-only" in _rendered_text(option)


def test_l0_banner_omits_suffix_when_no_count_is_known_for_this_project() -> None:
    group = _l0_group("sase")

    option = format_patch_banner_option(
        group,
        width=80,
        sequence=0,
        pr_unmirrored_counts={"other-project": 3},
    )

    assert "remote-only" not in _rendered_text(option)


def test_l0_banner_omits_suffix_when_counts_mapping_is_none() -> None:
    group = _l0_group("sase")

    option = format_patch_banner_option(
        group,
        width=80,
        sequence=0,
        pr_unmirrored_counts=None,
    )

    assert "remote-only" not in _rendered_text(option)


def test_l0_banner_omits_suffix_when_count_is_zero() -> None:
    group = _l0_group("sase")

    option = format_patch_banner_option(
        group,
        width=80,
        sequence=0,
        pr_unmirrored_counts={"sase": 0},
    )

    assert "remote-only" not in _rendered_text(option)


def test_l1_banner_never_gets_the_suffix_even_with_a_matching_key() -> None:
    group = _l1_group("sase")

    option = format_patch_banner_option(
        group,
        width=80,
        sequence=0,
        pr_unmirrored_counts={"sase": 3},
    )

    assert "remote-only" not in _rendered_text(option)


def test_banner_natural_width_grows_to_fit_the_remote_only_suffix() -> None:
    group = _l0_group("sase")

    without_counts = banner_natural_width(group, None)
    with_counts = banner_natural_width(group, None, pr_unmirrored_counts={"sase": 3})

    assert with_counts > without_counts


def test_patch_list_widget_renders_chip_for_by_project_grouping(
    monkeypatch: Any,
) -> None:
    widget = PatchList()
    monkeypatch.setattr(widget, "call_later", lambda callback: callback())
    monkeypatch.setattr(widget, "post_message", lambda _message: None)
    patches = [_cs("alpha", project="sase")]

    widget.update_list(
        patches,
        current_idx=0,
        grouping_mode=PatchGroupingMode.BY_PROJECT,
        pr_unmirrored_counts={"sase": 4},
    )

    banner_text = "".join(
        _rendered_text(widget.get_option_at_index(i))
        for i in range(widget.option_count)
        if widget._row_entries[i] == _BANNER_ROW
    )
    assert "4 remote-only" in banner_text
