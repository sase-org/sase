"""Verified branch projection shared by every gate renderer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.notification_gates.models import (
    GateError,
    GateFeedbackMode,
    GateGroup,
    GateOption,
    normalize_primary_branch,
)


@dataclass(frozen=True)
class GateBranchData:
    """Verified branch projection consumed by every ACE gate renderer."""

    query: str
    options: tuple[GateOption, ...]
    groups: tuple[GateGroup, ...]
    branches: tuple[tuple[str, ...], ...]
    primary_branch: tuple[str, ...]

    @classmethod
    def from_envelope(
        cls,
        envelope: Mapping[str, object],
        *,
        default_feedback: GateFeedbackMode = "disabled",
    ) -> GateBranchData:
        """Project a verified envelope without re-parsing its canonical query."""
        query = envelope.get("query")
        raw_options = envelope.get("options")
        raw_groups = envelope.get("groups")
        raw_branches = envelope.get("branches")
        raw_primary = envelope.get("primary_branch")
        if not isinstance(query, str) or not query:
            raise GateError("invalid_request", "query", "gate query is missing")
        if not isinstance(raw_options, list) or not raw_options:
            raise GateError("invalid_request", "options", "gate options are missing")
        if not isinstance(raw_groups, list):
            raise GateError("invalid_request", "groups", "gate groups are missing")
        if not isinstance(raw_branches, list) or not raw_branches:
            raise GateError("invalid_request", "branches", "gate branches are missing")

        options = tuple(
            GateOption.from_mapping(
                raw,
                index,
                default_feedback=default_feedback,
            )
            for index, raw in enumerate(raw_options)
        )
        groups = tuple(
            GateGroup.from_mapping(raw, index) for index, raw in enumerate(raw_groups)
        )
        branches: list[tuple[str, ...]] = []
        for index, raw_branch in enumerate(raw_branches):
            if (
                not isinstance(raw_branch, list)
                or not raw_branch
                or not all(isinstance(option_id, str) for option_id in raw_branch)
            ):
                raise GateError(
                    "invalid_request",
                    f"branches[{index}]",
                    "gate branch must be a non-empty array of option ids",
                )
            branches.append(tuple(raw_branch))

        option_ids = {option.id for option in options}
        flattened = [option_id for branch in branches for option_id in branch]
        if len(flattened) != len(set(flattened)) or set(flattened) != option_ids:
            raise GateError(
                "invalid_branches",
                "branches",
                "gate branches do not match the declared options",
            )
        group_members = {frozenset(group.options) for group in groups}
        branch_members = {frozenset(branch) for branch in branches if len(branch) > 1}
        if group_members != branch_members:
            raise GateError(
                "invalid_groups",
                "groups",
                "gate groups do not match the AND branches",
            )
        normalized_branches = tuple(branches)
        primary_branch = normalize_primary_branch(raw_primary, normalized_branches)
        return cls(
            query=query,
            options=options,
            groups=groups,
            branches=normalized_branches,
            primary_branch=primary_branch,
        )


__all__ = ["GateBranchData"]
