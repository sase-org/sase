"""Parse and resolve epic phase selectors for bead CLI mutations."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sase.bead.model import BeadTier, IssueType

if TYPE_CHECKING:
    from sase.bead.project import BeadProject

_NUMBER_RE = re.compile(r"-?\d+")
_RANGE_RE = re.compile(r"(-?\d+)\s*-\s*(-?\d+)")
_EXPECTED_SELECTOR = "expected phase numbers or ranges, e.g. 1,3,5-7"
_MISSING_PHASE_LIMIT = 10


class PhaseSelectorError(ValueError):
    """A user-facing phase selector validation error."""


def parse_phase_selectors(values: Sequence[str]) -> tuple[int, ...]:
    """Parse repeated comma-separated phase numbers and inclusive ranges."""
    phase_numbers: set[int] = set()
    for value in values:
        for raw_item in value.split(","):
            item = raw_item.strip()
            if _NUMBER_RE.fullmatch(item):
                phase_numbers.add(_validate_phase_number(int(item)))
                continue

            match = _RANGE_RE.fullmatch(item)
            if match is None:
                raise PhaseSelectorError(
                    f"invalid --phases value: {item!r} ({_EXPECTED_SELECTOR})"
                )

            start = _validate_phase_number(int(match.group(1)))
            end = _validate_phase_number(int(match.group(2)))
            if start > end:
                raise PhaseSelectorError(
                    f"invalid --phases range: {item!r} (start must not exceed end)"
                )
            phase_numbers.update(range(start, end + 1))

    return tuple(sorted(phase_numbers))


def resolve_epic_phase_ids(
    project: BeadProject,
    epic_id: str,
    phase_numbers: Sequence[int],
) -> list[str]:
    """Resolve phase number suffixes beneath one epic plan bead."""
    epic = project.show(epic_id)
    if epic.issue_type is not IssueType.PLAN or epic.tier is not BeadTier.EPIC:
        if epic.issue_type is IssueType.PHASE:
            actual = epic.issue_type.value
        else:
            actual = epic.tier.value if epic.tier is not None else "missing tier"
        raise PhaseSelectorError(
            f"--phases only applies to epic plan beads (got {actual} for {epic_id})"
        )

    children_by_number = {}
    prefix = f"{epic_id}."
    for child in project.get_epic_children(epic_id):
        suffix = child.id.removeprefix(prefix)
        if child.id.startswith(prefix) and suffix.isdigit():
            children_by_number[int(suffix)] = child

    for phase_number in phase_numbers:
        selected_child = children_by_number.get(phase_number)
        if (
            selected_child is not None
            and selected_child.issue_type is not IssueType.PHASE
        ):
            raise PhaseSelectorError(
                f"{selected_child.id} is not a phase bead; "
                "close it by ID if that is intended"
            )

    missing = [
        phase_number
        for phase_number in phase_numbers
        if phase_number not in children_by_number
    ]
    if missing:
        missing_text = _format_missing_phase_numbers(missing)
        existing = sorted(
            phase_number
            for phase_number, child in children_by_number.items()
            if child.issue_type is IssueType.PHASE
        )
        if not existing:
            raise PhaseSelectorError(
                f"epic {epic_id} has no phase {missing_text} (epic has no phase beads)"
            )
        existing_text = ", ".join(str(number) for number in existing)
        raise PhaseSelectorError(
            f"epic {epic_id} has no phase {missing_text} "
            f"(existing phases: {existing_text})"
        )

    return [children_by_number[number].id for number in phase_numbers]


def _validate_phase_number(number: int) -> int:
    if number < 1:
        raise PhaseSelectorError(
            f"invalid --phases value: {str(number)!r} (phase numbers start at 1)"
        )
    return number


def _format_missing_phase_numbers(numbers: Sequence[int]) -> str:
    shown = numbers[:_MISSING_PHASE_LIMIT]
    formatted = ", ".join(str(number) for number in shown)
    remaining = len(numbers) - len(shown)
    if remaining:
        formatted += f" (+{remaining} more)"
    return formatted
