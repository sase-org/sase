"""Pure Source-stage filtering and row construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections.abc import Mapping

from sase.project_onboarding import CandidateInputs
from sase.project_onboarding.render import GROUP_SECTIONS
from sase import workspace_provider


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One selectable or informational row in the Source list."""

    row_id: str
    group: str
    display: str
    ref: str = ""
    description: str = ""
    hidden_reason: str = ""
    owner: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        """Whether this row represents a provider-owner failure."""
        return self.group == "owner_error"


@dataclass(frozen=True, slots=True)
class _SourceGroup:
    """A named list section in the Source screen."""

    group_id: str
    heading: str
    glyph: str
    rows: tuple[SourceRow, ...]


@dataclass(frozen=True, slots=True)
class SourceView:
    """Fully filtered, render-ready Source list content."""

    groups: tuple[_SourceGroup, ...]
    hidden_counts: tuple[tuple[str, int], ...]
    owner_errors: tuple[SourceRow, ...]
    visible_count: int
    parsed_ref: Any | None = None

    @property
    def rows(self) -> tuple[SourceRow, ...]:
        """Flatten visible rows in screen order."""
        return tuple(row for group in self.groups for row in group.rows)


def _text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    return str(value) if value is not None else ""


def _source_row(group: str, data: Mapping[str, Any]) -> SourceRow:
    ref = _text(data, "ref")
    display = _text(data, "display") or ref or "?"
    identity = _text(data, "identity_key") or ref or display
    return SourceRow(
        row_id=f"{group}:{identity}",
        group=group,
        display=display,
        ref=ref,
        description=_text(data, "description"),
        hidden_reason=_text(data, "hidden_reason"),
        data=dict(data),
    )


def create_source_row(provider_display: str, workflow_type: str) -> SourceRow:
    """Build the pinned synthetic Create row for one provider.

    The row carries no ref, so detail and probe paths must never treat it as
    a repository. It stays pinned ahead of every other group and is never
    filtered out.
    """
    label = provider_display.strip() or workflow_type.strip() or "repository"
    return SourceRow(
        row_id=f"create:{workflow_type}",
        group="create",
        display=f"Create a new {label} repository…",
        ref="",
        description="start a new remote repository",
        data={"workflow_type": workflow_type, "provider_display": label},
    )


def build_source_view(
    inputs: CandidateInputs,
    *,
    filter_text: str = "",
    reveal_forks: bool = False,
    reveal_all: bool = False,
    pending_owners: frozenset[str] = frozenset(),
    create_row: SourceRow | None = None,
) -> SourceView:
    """Build Source rows from core classification plus local filter state."""
    from sase.core.project_onboarding_facade import classify_project_candidates

    classified = classify_project_candidates(inputs.core_request())
    query = filter_text.casefold().strip()
    groups_by_id = {
        str(group.get("id")): group
        for group in classified.get("groups", [])
        if isinstance(group, dict)
    }
    search_rows = [
        row for row in classified.get("search_only", []) if isinstance(row, dict)
    ]
    hidden_counts = tuple(
        (str(item.get("reason") or "?"), int(item.get("count") or 0))
        for item in classified.get("hidden", [])
        if isinstance(item, dict) and int(item.get("count") or 0) > 0
    )

    visible_groups: list[_SourceGroup] = []
    already_visible: set[str] = set()
    for group_id, heading, glyph in GROUP_SECTIONS:
        group = groups_by_id.get(group_id)
        raw_rows = group.get("rows", []) if group is not None else []
        rows: list[SourceRow] = []
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            row = _source_row(group_id, raw)
            already_visible.add(_text(raw, "identity_key").casefold())
            if (
                not query
                or query in " ".join((row.display, row.ref, row.description)).casefold()
            ):
                rows.append(row)
        if rows:
            visible_groups.append(_SourceGroup(group_id, heading, glyph, tuple(rows)))

    hidden_matches: list[SourceRow] = []
    if query:
        for raw in search_rows:
            row = _source_row("search_only", raw)
            identity = str(row.data.get("identity_key") or "").casefold()
            if identity in already_visible:
                continue
            if query in " ".join((row.display, row.ref, row.description)).casefold():
                hidden_matches.append(row)
    else:
        for raw in search_rows:
            row = _source_row("search_only", raw)
            reason = row.hidden_reason
            if reveal_all or (reveal_forks and reason == "fork"):
                hidden_matches.append(row)
    if hidden_matches:
        visible_groups.append(
            _SourceGroup("search_only", "HIDDEN MATCHES", "┄", tuple(hidden_matches))
        )

    if query:
        try:
            parsed_ref = workspace_provider.parse_repo_ref(
                inputs.workflow_type, filter_text
            )
        except (
            Exception
        ):  # Provider parse hooks are expected to be pure and may reject.
            parsed_ref = None
        if parsed_ref is not None:
            identity = str(parsed_ref.identity_key or "").casefold()
            known = identity in already_visible or any(
                _text(row.data, "identity_key").casefold() == identity
                for row in hidden_matches
            )
            if not known:
                paste_row = SourceRow(
                    row_id=f"paste:{parsed_ref.identity_key}",
                    group="paste",
                    display=f"Add {parsed_ref.display}",
                    ref=parsed_ref.ref,
                    description="pasted repository reference",
                    data={
                        "identity_key": parsed_ref.identity_key,
                        "display": parsed_ref.display,
                        "ref": parsed_ref.ref,
                        "parsed": parsed_ref,
                    },
                )
                visible_groups.insert(
                    0, _SourceGroup("paste", "PASTED REFERENCE", "↵", (paste_row,))
                )
        else:
            parsed_ref = None
    else:
        parsed_ref = None

    owner_errors: list[SourceRow] = []
    fetching_rows: list[SourceRow] = []
    for owner in inputs.owners:
        if owner.status == "error":
            owner_errors.append(
                SourceRow(
                    row_id=f"owner-error:{owner.name}",
                    group="owner_error",
                    display=f"{owner.name}: {owner.message or 'owner failed'}",
                    owner=owner.name,
                    data={
                        "status": owner.status,
                        "message": owner.message,
                        "stale": owner.stale,
                        "remedy_argv": tuple(owner.remedy_argv),
                    },
                )
            )
        elif owner.name in pending_owners:
            fetching_rows.append(
                SourceRow(
                    row_id=f"owner-fetching:{owner.name}",
                    group="owner_fetching",
                    display=f"fetching {owner.name}…",
                    owner=owner.name,
                )
            )
    if owner_errors:
        visible_groups.insert(
            0, _SourceGroup("owner_error", "OWNER ISSUES", "⚠", tuple(owner_errors))
        )
    if fetching_rows:
        visible_groups.insert(
            0, _SourceGroup("owner_fetching", "UPDATING", "◌", tuple(fetching_rows))
        )
    if create_row is not None:
        visible_groups.insert(0, _SourceGroup("create", "CREATE", "✚", (create_row,)))

    return SourceView(
        groups=tuple(visible_groups),
        hidden_counts=hidden_counts,
        owner_errors=tuple(owner_errors),
        visible_count=sum(len(group.rows) for group in visible_groups),
        parsed_ref=parsed_ref,
    )


def hidden_footer(view: SourceView) -> str:
    """Render the hidden-count footer and its two reveal keys."""
    labels = {
        "sidecar": ("sidecar", "sidecars"),
        "fork": ("fork", "forks"),
        "archived": ("archived repository", "archived repositories"),
        "enabled_project": ("project", "projects"),
        "numbered_copy": ("numbered copy", "numbered copies"),
        "third_party_local": ("third-party checkout", "third-party checkouts"),
    }
    totals = [
        f"{count} {labels.get(reason, (reason, reason))[0 if count == 1 else 1]}"
        for reason, count in view.hidden_counts
    ]
    summary = " · ".join(totals) if totals else "0"
    return f"┄ {summary} hidden · f forks · . all"


__all__ = [
    "SourceRow",
    "SourceView",
    "build_source_view",
    "create_source_row",
    "hidden_footer",
]
