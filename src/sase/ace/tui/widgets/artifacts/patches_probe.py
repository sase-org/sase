"""Patch query probe and relation helpers for the Artifacts Patches pane."""

from __future__ import annotations

from typing import Any


def patch_relation_status_hidden(status: str) -> bool:
    return status.startswith("Reverted") or status.startswith("Archived")


def patch_stack_size(
    patches: list[Any],
    by_name: dict[str, Any],
    root: str,
) -> int | None:
    """Count the stack rooted at *root*: the root plus its descendants."""
    folded = root.casefold()
    count = 0
    for item in patches:
        seen = {item.name.casefold()}
        current = item
        while current.name.casefold() != folded:
            parent_name = getattr(current, "parent", None)
            if not parent_name:
                break
            parent = by_name.get(str(parent_name).casefold())
            if parent is None or parent.name.casefold() in seen:
                break
            seen.add(parent.name.casefold())
            current = parent
        if current.name.casefold() == folded:
            count += 1
    return count or None


class PatchMembershipProbe:
    """One-row Patch matcher mirroring visible list membership.

    Uses the pane's own boolean query engine (not the shared Rust corpus)
    plus the same hide-toggle lifting the list applies, so Context
    verification and hidden-reason analysis agree with what the user sees.
    """

    def __init__(self, *, patch: Any, app: Any, parse: Any) -> None:
        self._patch = patch
        self._app = app
        self._parse = parse

    def matches(self, query: str) -> bool:
        """Return whether *query* would show this probe's Patch."""
        from sase.ace.query import QueryParseError
        from sase.ace.query.evaluator import evaluate_query
        from sase.ace.query.introspection import (
            query_explicitly_targets_submitted,
            query_explicitly_targets_terminal,
        )
        from sase.ace.query.matchers import get_base_status

        try:
            parsed = self._parse(query)
        except QueryParseError:
            return False
        except Exception:  # noqa: BLE001 - a probe failure is not absence
            return False
        try:
            all_patches = list(getattr(self._app, "_all_patches", ()))
            if not evaluate_query(parsed, self._patch, all_patches):
                return False
        except Exception:  # noqa: BLE001 - treat probe errors as excluding
            return False
        base_status = get_base_status(self._patch.status)
        if (
            bool(getattr(self._app, "hide_reverted", False))
            and base_status in ("Reverted", "Archived")
            and not query_explicitly_targets_terminal(parsed, all_patches)
        ):
            return False
        if (
            bool(getattr(self._app, "hide_submitted", False))
            and base_status == "Submitted"
            and not query_explicitly_targets_submitted(parsed, all_patches)
        ):
            return False
        return True


__all__ = [
    "PatchMembershipProbe",
    "patch_relation_status_hidden",
    "patch_stack_size",
]
