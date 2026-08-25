"""Shared helpers for the ``BeadProjectMutationMixin`` submixins."""

from __future__ import annotations


def _combine_mutation_outcomes(
    operation: str,
    outcomes: list[dict[str, object]],
) -> dict[str, object]:
    if not outcomes:
        return {"operation": operation, "issue_ids": []}
    issue_ids: list[str] = []
    reopened_ancestor_ids: list[str] = []
    for outcome in outcomes:
        _extend_unique(issue_ids, outcome.get("issue_ids"))
        _extend_unique(reopened_ancestor_ids, outcome.get("reopened_ancestor_ids"))
    combined = outcomes[-1].copy()
    combined["operation"] = operation
    combined["issue_ids"] = issue_ids
    if reopened_ancestor_ids:
        combined["reopened_ancestor_ids"] = reopened_ancestor_ids
    return combined


def _extend_unique(target: list[str], raw: object) -> None:
    if not isinstance(raw, list):
        return
    for item in raw:
        if not isinstance(item, str) or item in target:
            continue
        target.append(item)
