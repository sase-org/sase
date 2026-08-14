"""Unit coverage for Artifacts digit-shortcut numbering by visual position."""

from __future__ import annotations

import pytest

from sase.ace.tui._artifact_tab_descriptors import assign_artifacts_digit_shortcuts
from sase.ace.tui.artifact_tabs import ArtifactsTabDescriptor


def _descriptor(id_: str, *, is_provider: bool = False) -> ArtifactsTabDescriptor:
    return ArtifactsTabDescriptor(
        id=id_,
        label=id_.title(),
        accent="#000000",
        pane_id=f"{id_}-pane",
        provider_kind="ref" if is_provider else None,
    )


def test_fixed_only_strip_numbers_one_through_four() -> None:
    descriptors = assign_artifacts_digit_shortcuts(
        (
            _descriptor("stitches"),
            _descriptor("patches"),
            _descriptor("beads"),
            _descriptor("files"),
        )
    )
    assert [descriptor.digit_shortcut for descriptor in descriptors] == [
        "1",
        "2",
        "3",
        "4",
    ]


def test_two_providers_push_files_to_six() -> None:
    descriptors = assign_artifacts_digit_shortcuts(
        (
            _descriptor("stitches"),
            _descriptor("patches"),
            _descriptor("beads"),
            _descriptor("ref:plan", is_provider=True),
            _descriptor("ref:research", is_provider=True),
            _descriptor("files"),
        )
    )
    assert [descriptor.digit_shortcut for descriptor in descriptors] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
    ]
    by_id = {descriptor.id: descriptor.digit_shortcut for descriptor in descriptors}
    assert by_id["files"] == "6"
    assert by_id["ref:plan"] == "4"
    assert by_id["ref:research"] == "5"


@pytest.mark.parametrize("provider_count", range(6))
def test_digit_assignment_invariants_hold_for_provider_counts(
    provider_count: int,
) -> None:
    providers = [
        _descriptor(f"ref:provider{index}", is_provider=True)
        for index in range(provider_count)
    ]
    descriptors = assign_artifacts_digit_shortcuts(
        (
            _descriptor("stitches"),
            _descriptor("patches"),
            _descriptor("beads"),
            *providers,
            _descriptor("files"),
        )
    )
    digits = [descriptor.digit_shortcut for descriptor in descriptors]
    assert all(digit is not None for digit in digits)
    assert digits == [str(position) for position in range(1, len(descriptors) + 1)]
    assert len(set(digits)) == len(digits)

    files_digit = next(
        descriptor.digit_shortcut
        for descriptor in descriptors
        if descriptor.id == "files"
    )
    assert files_digit is not None
    assert int(files_digit) == max(int(digit) for digit in digits if digit is not None)


def test_overflow_at_ten_panes_files_still_gets_ninth_digit() -> None:
    providers = [
        _descriptor(f"ref:provider{index}", is_provider=True) for index in range(6)
    ]
    descriptors = assign_artifacts_digit_shortcuts(
        (
            _descriptor("stitches"),
            _descriptor("patches"),
            _descriptor("beads"),
            *providers,
            _descriptor("files"),
        )
    )
    assert len(descriptors) == 10

    files_descriptor = descriptors[-1]
    assert files_descriptor.id == "files"
    assert files_descriptor.digit_shortcut == "9"

    digits = [descriptor.digit_shortcut for descriptor in descriptors]
    assigned = [digit for digit in digits if digit is not None]
    assert len(assigned) == len(set(assigned)) == 9
    assert digits[:8] == ["1", "2", "3", "4", "5", "6", "7", "8"]
    assert digits[8] is None
