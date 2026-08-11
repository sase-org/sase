"""Tests for the PR_ORIGIN chip on Patch list rows.

The PR badge (the ``(pr_url)`` text) and the origin chip are two
independent signals; ``sase`` origin renders no chip at all since it is
the expected case.
"""

from sase.ace.patch import Patch
from sase.ace.testing import make_patch
from sase.ace.tui.widgets._patch_list_helpers import (
    calculate_entry_display_width,
    format_patch_option,
    row_signature,
)


def test_sase_origin_renders_no_chip() -> None:
    patch = make_patch(cl="https://github.com/foo/bar/pull/812", pr_origin="sase")
    option = format_patch_option(patch, is_selected=False, is_marked=False)
    assert "external" not in option.prompt.plain
    assert "origin?" not in option.prompt.plain


def test_external_origin_renders_chip() -> None:
    patch = make_patch(cl="https://github.com/foo/bar/pull/819", pr_origin="external")
    option = format_patch_option(patch, is_selected=False, is_marked=False)
    assert "external" in option.prompt.plain


def test_unknown_origin_renders_chip() -> None:
    patch = make_patch(cl="https://github.com/foo/bar/pull/601", pr_origin="unknown")
    option = format_patch_option(patch, is_selected=False, is_marked=False)
    assert "origin?" in option.prompt.plain


def test_no_pr_url_renders_no_chip_even_when_origin_set() -> None:
    """A chip answers "who created that PR?" — no PR means no question."""
    patch = make_patch(cl=None, pr_origin="external")
    option = format_patch_option(patch, is_selected=False, is_marked=False)
    assert "external" not in option.prompt.plain


def test_width_calculation_includes_origin_chip() -> None:
    with_chip = make_patch(
        cl="https://github.com/foo/bar/pull/819", pr_origin="external"
    )
    without_chip = make_patch(
        cl="https://github.com/foo/bar/pull/819", pr_origin="sase"
    )
    assert calculate_entry_display_width(
        with_chip, is_marked=False
    ) > calculate_entry_display_width(without_chip, is_marked=False)


def test_width_calculation_matches_rendered_text() -> None:
    patch = make_patch(cl="https://github.com/foo/bar/pull/819", pr_origin="external")
    option = format_patch_option(patch, is_selected=False, is_marked=False)
    assert (
        calculate_entry_display_width(patch, is_marked=False) == option.prompt.cell_len
    )


def test_row_signature_changes_with_origin() -> None:
    external = make_patch(
        cl="https://github.com/foo/bar/pull/819", pr_origin="external"
    )
    sase_origin = make_patch(cl="https://github.com/foo/bar/pull/819", pr_origin="sase")

    def sig(patch: Patch) -> tuple[object, ...]:
        return row_signature(
            patch,
            is_selected=False,
            is_marked=False,
            show_hideable=False,
            show_submitted=False,
            mentor_stats=None,
            hint_char=None,
        )

    assert sig(external) != sig(sase_origin)
