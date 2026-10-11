"""Pure Archive list model: banners, page windows, and flattened list items.

Archive-column seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
Membership, order, counts, outcome classification, timestamps, and container
identity all come from the Rust-backed corpus. This module only combines
consecutive daily summaries into display banners, plans banner-local page
windows, and flattens loaded light rows into the selectable list items the
Archive column renders. It never evaluates a query or groups runs itself.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo, UTC
from typing import Any
from zoneinfo import ZoneInfo

from .agent_archive_controller import (
    ARCHIVE_CORPUS_MISSING,
    ARCHIVE_CORPUS_REBUILDING,
    ARCHIVE_CORPUS_UNREADABLE,
    ARCHIVE_INDEX_UNAVAILABLE_MESSAGE,
    ArchiveLoadedWindow,
    ArchivePageWindow,
)
from sase.core.time import get_timezone

from .agent_archive_view import banner_item_key, container_item_key, tail_item_key
from .date_subgroups import NO_TIMESTAMP_LABEL, day_subgroup_label, week_subgroup_label

ARCHIVE_PAGE_SIZE = 100
ARCHIVE_OPEN_ALL_MAX = 50
_WEEKLY_BANNER_MAX_AGE_DAYS = 62
_LAST_WEEK_MAX_AGE_DAYS = 6

ITEM_BANNER = "banner"
ITEM_ROW = "row"
ITEM_CONTAINER = "container"
ITEM_MEMBER = "member"
ITEM_TAIL = "tail"
ITEM_LOADING = "loading"
ITEM_MESSAGE = "message"

_NONE_BANNER_KEY = "none"

_OUTCOME_LABELS = {"done": "Done", "failed": "Failed", "interrupted": "Interrupted"}
_FIXED_OFFSET = re.compile(r"(?:UTC)?([+-])(\d{2}):?(\d{2})")


@dataclass(frozen=True)
class ArchiveBanner:
    """One display banner combining one or more core summary groups."""

    key: str
    label: str
    count: int
    group_keys: tuple[str, ...]
    group_counts: tuple[int, ...]


@dataclass(frozen=True)
class ArchiveListItem:
    """One rendered Archive list entry. Only banners and runs are selectable."""

    key: str
    kind: str
    selectable: bool
    banner_key: str | None = None
    row: Mapping[str, Any] | None = None
    label: str = ""
    count: int = 0
    remaining: int = 0
    open: bool = False
    expanded: bool = False
    member_of: str | None = None


@dataclass(frozen=True)
class ArchiveListModel:
    """Flattened Archive list: items in render order plus key lookups."""

    items: tuple[ArchiveListItem, ...] = ()
    index: Mapping[str, int] | None = None
    banners: tuple[ArchiveBanner, ...] = ()
    open_keys: frozenset[str] = frozenset()

    def position(self, key: str | None) -> int | None:
        if key is None or self.index is None:
            return None
        return self.index.get(key)

    def item(self, key: str | None) -> ArchiveListItem | None:
        position = self.position(key)
        return None if position is None else self.items[position]

    def selectable_keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.items if item.selectable)


def archive_timezone(name: str | None) -> tzinfo:
    """Resolve the corpus timezone name (IANA or fixed UTC offset)."""
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
        match = _FIXED_OFFSET.fullmatch(name.strip())
        if match is not None:
            delta = timedelta(hours=int(match[2]), minutes=int(match[3]))
            return timezone(-delta if match[1] == "-" else delta)
    return get_timezone()


def parse_archive_timestamp(value: object, tz: tzinfo) -> datetime | None:
    """Parse a core RFC 3339 timestamp into the corpus timezone."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(tz)


def archive_row_key(row: Mapping[str, Any]) -> str | None:
    """Return the stable list/selection key for one core light row.

    A container is ``container:<container_key>``; a run is the index's
    ``user.machine@run`` identity. Rows lacking a complete archive key (legacy
    fixtures) fall back to their name.
    """
    container_key = row.get("container_key")
    if row.get("container") is True and isinstance(container_key, str):
        return container_item_key(container_key)
    archive_key = row.get("archive_key")
    if isinstance(archive_key, Mapping):
        user = archive_key.get("source_username")
        machine = archive_key.get("source_machine")
        run_id = archive_key.get("source_run_id")
        if all(isinstance(part, str) and part for part in (user, machine, run_id)):
            return f"{user}.{machine}@{run_id}"
    for name_key in ("name", "cl_name", "agent_name"):
        value = row.get(name_key)
        if isinstance(value, str) and value:
            return value
    if isinstance(archive_key, Mapping):
        run_id = archive_key.get("source_run_id")
        if isinstance(run_id, str) and run_id:
            return run_id
    return None


def _day_banner(day: date, today: date) -> tuple[str, str]:
    age = (today - day).days
    if age <= 0:
        return f"day:{today.isoformat()}", "Today"
    if age == 1:
        return f"day:{day.isoformat()}", "Yesterday"
    if age <= _LAST_WEEK_MAX_AGE_DAYS:
        stamp = datetime.combine(day, time())
        return f"day:{day.isoformat()}", day_subgroup_label(stamp)
    if age < _WEEKLY_BANNER_MAX_AGE_DAYS:
        monday = day - timedelta(days=day.weekday())
        return f"week:{monday.isoformat()}", week_subgroup_label(
            datetime.combine(day, time())
        )
    return f"month:{day:%Y-%m}", f"{day:%B %Y}"


def _day_group_banner(group_key: str, today: date) -> tuple[str, str]:
    try:
        day = date.fromisoformat(group_key)
    except ValueError:
        return _NONE_BANNER_KEY, NO_TIMESTAMP_LABEL
    return _day_banner(day, today)


def _plain_group_label(grouping: str, group_key: str) -> str:
    if grouping == "outcome":
        return _OUTCOME_LABELS.get(group_key, group_key or "(unknown)")
    if grouping == "project":
        return group_key or "(no project)"
    return group_key or "(no model)"


def build_archive_banners(
    summary: Mapping[str, Any] | None,
    grouping: str,
    *,
    today: date,
) -> tuple[ArchiveBanner, ...]:
    """Combine core summary groups into display banners, in core order.

    Day grouping merges consecutive daily groups into Today, Yesterday,
    last-week days, weeks for the rest of two months, then months. Other
    groupings show each core group as one banner. Core counts stay
    authoritative: a banner's count is the sum of its groups' root counts.
    """
    if not isinstance(summary, Mapping):
        return ()
    order: list[str] = []
    labels: dict[str, str] = {}
    members: dict[str, tuple[list[str], list[int]]] = {}
    for group in summary.get("groups", ()) or ():
        if not isinstance(group, Mapping):
            continue
        group_key = str(group.get("key", "") or "")
        count = int(group.get("count", 0) or 0)
        if grouping == "day":
            key, label = _day_group_banner(group_key, today)
        else:
            key = f"{grouping}:{group_key}"
            label = _plain_group_label(grouping, group_key)
        if key not in members:
            order.append(key)
            labels[key] = label
            members[key] = ([], [])
        members[key][0].append(group_key)
        members[key][1].append(count)
    return tuple(
        ArchiveBanner(
            key=key,
            label=labels[key],
            count=sum(members[key][1]),
            group_keys=tuple(members[key][0]),
            group_counts=tuple(members[key][1]),
        )
        for key in order
    )


def default_open_banner_keys(
    banners: Sequence[ArchiveBanner],
    *,
    grouping: str,
    total: int,
    today: date,
    complete: bool = True,
) -> frozenset[str]:
    """Return the banners open before any user fold change.

    Today and Yesterday open by default (the first banner for non-day
    groupings); a complete query matching at most 50 runs opens everything.
    An incomplete (rebuilding) index never counts as a complete small result.
    """
    if complete and total <= ARCHIVE_OPEN_ALL_MAX:
        return frozenset(banner.key for banner in banners)
    if grouping == "day":
        wanted = {
            f"day:{today.isoformat()}",
            f"day:{(today - timedelta(days=1)).isoformat()}",
        }
        return frozenset(banner.key for banner in banners if banner.key in wanted)
    return frozenset(banner.key for banner in banners[:1])


def effective_open_banner_keys(
    default_open: Collection[str],
    expanded: Collection[str],
    folded: Collection[str],
) -> frozenset[str]:
    """Apply the user's explicit fold overrides to the default-open set."""
    return (frozenset(default_open) - frozenset(folded)) | frozenset(expanded)


def with_banner_open(
    expanded: Collection[str],
    folded: Collection[str],
    key: str,
    *,
    open: bool,
    default_open: bool,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return updated ``(expanded, folded)`` overrides after opening/folding."""
    expanded_set = set(expanded)
    folded_set = set(folded)
    if open:
        folded_set.discard(key)
        if not default_open:
            expanded_set.add(key)
    else:
        expanded_set.discard(key)
        if default_open:
            folded_set.add(key)
    return tuple(sorted(expanded_set)), tuple(sorted(folded_set))


def _banner_page_target(pages: Mapping[str, int], banner_key: str) -> int:
    """Return how many visible rows a banner currently asks for."""
    return ARCHIVE_PAGE_SIZE * max(1, int(pages.get(banner_key, 1) or 1))


def plan_archive_windows(
    banners: Sequence[ArchiveBanner],
    open_keys: Collection[str],
    pages: Mapping[str, int],
    *,
    probe_totals: bool = False,
) -> tuple[ArchivePageWindow, ...]:
    """Plan core row windows for every open banner's visible page.

    A banner spans several core groups in order. Each group can contribute at
    most ``target - roots in earlier groups`` flattened rows, because every
    root yields at least one row, so one request covers the whole page.
    ``probe_totals`` also asks (limit 0) for the flattened total of groups
    past the cap, which expanded containers make larger than the root count.
    """
    windows: list[ArchivePageWindow] = []
    for banner in banners:
        if banner.key not in open_keys:
            continue
        target = _banner_page_target(pages, banner.key)
        consumed = 0
        for group_key, count in zip(
            banner.group_keys, banner.group_counts, strict=True
        ):
            cap = target - consumed
            if cap > 0:
                windows.append(ArchivePageWindow(group_key, 0, cap))
            elif probe_totals:
                windows.append(ArchivePageWindow(group_key, 0, 0))
            consumed += count
    return tuple(windows)


def windows_satisfy(
    loaded: Sequence[ArchiveLoadedWindow],
    planned: Sequence[ArchivePageWindow],
) -> bool:
    """Return whether the loaded windows already hold every planned window.

    A loaded window satisfies a plan when it starts at the same offset and is
    at least as large, or already holds every row of its group. Extra loaded
    windows (a folded banner's) are harmless, so folding needs no request.
    """
    by_group = {window.group_key: window for window in loaded if window.offset == 0}
    for want in planned:
        have = by_group.get(want.group_key)
        if have is None:
            return False
        if want.limit > have.limit and have.total > len(have.rows):
            return False
    return True


def banner_key_for_row(
    row: Mapping[str, Any],
    grouping: str,
    tz: tzinfo,
    today: date,
) -> str | None:
    """Return the banner a core light row lands in under ``grouping``."""
    if grouping == "day":
        moment = parse_archive_timestamp(row.get("last_activity_at"), tz)
        if moment is None:
            return _NONE_BANNER_KEY
        return _day_banner(moment.date(), today)[0]
    if grouping == "project":
        return f"project:{row.get('project') or ''}"
    if grouping == "model":
        return f"model:{row.get('model') or ''}"
    if grouping == "outcome":
        return f"outcome:{row.get('outcome') or ''}"
    return None


def _status_message(
    *,
    status: str,
    error_message: str | None,
    indexed_rows: int,
    summary_known: bool,
    loading: bool,
) -> ArchiveListItem | None:
    """Return the header note for a missing, rebuilding, or loading corpus."""
    if status in {ARCHIVE_CORPUS_MISSING, ARCHIVE_CORPUS_UNREADABLE}:
        text = error_message or ARCHIVE_INDEX_UNAVAILABLE_MESSAGE
        return ArchiveListItem("message:status", ITEM_MESSAGE, False, label=text)
    if status == ARCHIVE_CORPUS_REBUILDING:
        text = f"Archive index rebuilding — {indexed_rows} runs indexed so far"
        return ArchiveListItem("message:status", ITEM_MESSAGE, False, label=text)
    if not summary_known:
        label = "Loading Archive…" if loading else "Archive results unavailable"
        return ArchiveListItem("message:status", ITEM_MESSAGE, False, label=label)
    return None


def assemble_archive_list(
    *,
    banners: Sequence[ArchiveBanner],
    open_keys: Collection[str],
    windows: Sequence[ArchiveLoadedWindow],
    pages: Mapping[str, int],
    desired_expanded: Collection[str],
    applied_expanded: Collection[str],
    status: str,
    error_message: str | None,
    indexed_rows: int,
    summary_known: bool,
    loading: bool,
) -> ArchiveListModel:
    """Flatten banners and loaded light windows into render-ordered items."""
    items: list[ArchiveListItem] = []
    note = _status_message(
        status=status,
        error_message=error_message,
        indexed_rows=indexed_rows,
        summary_known=summary_known,
        loading=loading,
    )
    if note is not None:
        items.append(note)
    if (
        summary_known
        and not banners
        and status not in {ARCHIVE_CORPUS_MISSING, ARCHIVE_CORPUS_UNREADABLE}
    ):
        text = "No archived runs match this query."
        if status == ARCHIVE_CORPUS_REBUILDING:
            text = "No matches yet — the index is still rebuilding."
        items.append(ArchiveListItem("message:empty", ITEM_MESSAGE, False, label=text))
    by_group = {window.group_key: window for window in windows}
    wanted = frozenset(desired_expanded)
    applied = frozenset(applied_expanded)
    open_set = frozenset(open_keys)
    for banner in banners:
        is_open = banner.key in open_set
        items.append(
            ArchiveListItem(
                banner_item_key(banner.key),
                ITEM_BANNER,
                True,
                banner_key=banner.key,
                label=banner.label,
                count=banner.count,
                open=is_open,
            )
        )
        if not is_open:
            continue
        items.extend(_banner_rows(banner, by_group, pages, wanted, applied))
    index = {item.key: position for position, item in enumerate(items)}
    return ArchiveListModel(
        items=tuple(items),
        index=index,
        banners=tuple(banners),
        open_keys=open_set,
    )


def _banner_rows(
    banner: ArchiveBanner,
    by_group: Mapping[str, ArchiveLoadedWindow],
    pages: Mapping[str, int],
    wanted: frozenset[str],
    applied: frozenset[str],
) -> list[ArchiveListItem]:
    target = _banner_page_target(pages, banner.key)
    flat_total = 0
    loaded: list[Mapping[str, Any]] = []
    contiguous = True
    for group_key, count in zip(banner.group_keys, banner.group_counts, strict=True):
        window = by_group.get(group_key)
        if window is None:
            flat_total += count
            contiguous = False
            continue
        flat_total += max(window.total, count)
        if contiguous:
            loaded.extend(window.rows)
    out: list[ArchiveListItem] = []
    shown = 0
    hidden_members = 0
    current_container: str | None = None
    for row in loaded:
        if shown >= target:
            break
        key = archive_row_key(row)
        if key is None:
            continue
        if row.get("container") is True:
            container_key = str(row.get("container_key") or "")
            current_container = container_key
            expanded = container_key in wanted
            out.append(
                ArchiveListItem(
                    key,
                    ITEM_CONTAINER,
                    True,
                    banner_key=banner.key,
                    row=row,
                    count=int(row.get("member_count", 0) or 0),
                    expanded=expanded,
                )
            )
            shown += 1
            if expanded and container_key not in applied:
                out.append(
                    ArchiveListItem(
                        f"loading:{container_key}",
                        ITEM_LOADING,
                        False,
                        banner_key=banner.key,
                        label="loading members…",
                        member_of=container_key,
                    )
                )
            continue
        container_key = str(row.get("container_key") or "")
        if current_container is not None and container_key == current_container:
            if container_key not in wanted:
                hidden_members += 1  # stale members of a just-collapsed container
                continue
            out.append(
                ArchiveListItem(
                    key,
                    ITEM_MEMBER,
                    True,
                    banner_key=banner.key,
                    row=row,
                    member_of=container_key,
                )
            )
        else:
            current_container = None
            out.append(
                ArchiveListItem(key, ITEM_ROW, True, banner_key=banner.key, row=row)
            )
        shown += 1
    remaining = flat_total - hidden_members - shown
    if not out and not contiguous and banner.count > 0:
        out.append(
            ArchiveListItem(
                f"loading:{banner.key}",
                ITEM_LOADING,
                False,
                banner_key=banner.key,
                label="loading…",
            )
        )
    elif remaining > 0:
        out.append(
            ArchiveListItem(
                tail_item_key(banner.key),
                ITEM_TAIL,
                True,
                banner_key=banner.key,
                remaining=remaining,
            )
        )
    return out


def neighbor_key(model: ArchiveListModel, key: str | None, step: int) -> str | None:
    """Return the adjacent selectable key (clamped, no wrap)."""
    selectable = model.selectable_keys()
    if not selectable:
        return None
    if key not in selectable:
        return selectable[0] if step >= 0 else selectable[-1]
    position = selectable.index(str(key)) + step
    return selectable[max(0, min(len(selectable) - 1, position))]


def edge_key(model: ArchiveListModel, *, last: bool) -> str | None:
    """Return the first or last selectable key."""
    selectable = model.selectable_keys()
    if not selectable:
        return None
    return selectable[-1] if last else selectable[0]


def parent_banner_key(model: ArchiveListModel, key: str | None) -> str | None:
    """Return the banner item key that owns ``key``'s row."""
    item = model.item(key)
    if item is None or item.banner_key is None:
        return None
    if item.kind == ITEM_BANNER:
        return None
    return banner_item_key(item.banner_key)


def fallback_cursor(
    previous: ArchiveListModel,
    key: str | None,
    current: ArchiveListModel,
) -> str | None:
    """Pick the nearest still-valid cursor after the list was rebuilt."""
    if key is not None and current.position(key) is not None:
        return key
    selectable = current.selectable_keys()
    if not selectable:
        return None
    position = previous.position(key)
    if position is not None:
        for item in previous.items[position + 1 :]:
            if item.selectable and current.position(item.key) is not None:
                return item.key
        for item in reversed(previous.items[:position]):
            if item.selectable and current.position(item.key) is not None:
                return item.key
    return selectable[0]


__all__ = [
    "ARCHIVE_OPEN_ALL_MAX",
    "ARCHIVE_PAGE_SIZE",
    "ITEM_BANNER",
    "ITEM_CONTAINER",
    "ITEM_LOADING",
    "ITEM_MEMBER",
    "ITEM_MESSAGE",
    "ITEM_ROW",
    "ITEM_TAIL",
    "ArchiveBanner",
    "ArchiveListItem",
    "ArchiveListModel",
    "archive_row_key",
    "archive_timezone",
    "assemble_archive_list",
    "banner_key_for_row",
    "build_archive_banners",
    "default_open_banner_keys",
    "edge_key",
    "effective_open_banner_keys",
    "fallback_cursor",
    "neighbor_key",
    "parent_banner_key",
    "parse_archive_timestamp",
    "plan_archive_windows",
    "windows_satisfy",
    "with_banner_open",
]
