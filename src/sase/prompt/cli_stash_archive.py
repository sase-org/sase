"""``sase prompt stash-archive`` — list, show, and restore archived drafts.

Every row that permanently leaves the prompt stash is first appended to an
append-only archive (``prompt_stash_archive.jsonl``, a sibling of the stash
file): restored, deleted, purged, evicted, and overwritten drafts all land
there with the full entry as it looked before removal. The archive never
deletes lines, so anything listed here can be appended back to Stash with
``restore``.
"""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.core.paths import prompt_stash_path
from sase.core.prompt_stash_facade import (
    read_prompt_stash_archive,
    recover_prompt_stash_archive,
)
from sase.core.prompt_stash_wire import (
    PromptStashArchiveRecordWire,
    prompt_stash_wire_to_json_dict,
)
from sase.prompt.render import format_timestamp

ARCHIVE_REASONS = ("evicted", "overwritten", "popped", "purged")

_REASON_STYLES = {
    "evicted": "yellow",
    "overwritten": "magenta",
    "popped": "cyan",
    "purged": "red",
}

# Reads beyond this cap are truncated server-side by the ``limit`` argument;
# filtered ``list`` calls fetch up to this many rows before filtering so a
# query can match older entries without scanning an unbounded file.
_FILTER_FETCH_CAP = 100_000


def handle_prompt_stash_archive(args: argparse.Namespace) -> None:
    """Dispatch ``sase prompt stash-archive`` subcommands."""
    sub = getattr(args, "stash_archive_subcommand", None)
    if sub == "list":
        _handle_stash_archive_list(args)
        sys.exit(0)
    if sub == "restore":
        sys.exit(_handle_stash_archive_restore(args))
        return
    if sub == "show":
        _handle_stash_archive_show(args)
        sys.exit(0)
    print("Usage: sase prompt stash-archive {list,restore,show}")
    sys.exit(1)


def _fetch_records(
    limit: int | None, query: str | None, reason: str | None
) -> list[PromptStashArchiveRecordWire]:
    """Read archive rows, newest-first, applying ``query``/``reason`` filters."""
    fetch_limit = limit if limit is not None else 20
    if query or reason:
        fetch_limit = max(fetch_limit, _FILTER_FETCH_CAP)
    snapshot = read_prompt_stash_archive(prompt_stash_path(), fetch_limit)
    records = list(snapshot.records)
    if reason:
        records = [record for record in records if record.reason == reason]
    if query:
        needle = query.casefold()
        records = [
            record
            for record in records
            if needle in record.entry.text.casefold()
            or needle in record.entry.frontmatter.casefold()
        ]
    if limit is not None:
        records = records[:limit]
    return records


def _record_to_json(record: PromptStashArchiveRecordWire) -> dict[str, object]:
    payload = prompt_stash_wire_to_json_dict(record)
    assert isinstance(payload, dict)
    return payload


def _handle_stash_archive_list(args: argparse.Namespace) -> None:
    """Render archived drafts (pretty table by default, JSON with ``-j``)."""
    limit: int | None = getattr(args, "limit", 20)
    query: str | None = getattr(args, "query", None)
    reason: str | None = getattr(args, "reason", None)
    records = _fetch_records(limit, query, reason)
    if bool(getattr(args, "json", False)):
        json.dump([_record_to_json(record) for record in records], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    _print_list_pretty(records, query=query, reason=reason)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:80]
    return "(empty)"


def _print_list_pretty(
    records: list[PromptStashArchiveRecordWire],
    *,
    query: str | None,
    reason: str | None,
) -> None:
    console = Console()
    title = f"Stash archive ({len(records)})"
    if not records:
        hint = (
            "Every draft that permanently leaves the stash is archived here "
            "before removal: restored, deleted, purged, evicted, or "
            "overwritten. Nothing to show for this filter."
            if (query or reason)
            else "The stash archive is empty: no draft has permanently left "
            "the stash yet. Restored, deleted, purged, evicted, and "
            "overwritten drafts are archived here first."
        )
        console.print(Panel(Text(hint), title=title, border_style="cyan"))
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ARCHIVED", style="dim", no_wrap=True)
    table.add_column("REASON", no_wrap=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("PROJECT", no_wrap=True)
    table.add_column("FIRST LINE")
    for record in records:
        reason_text = Text(record.reason, style=_REASON_STYLES.get(record.reason, ""))
        table.add_row(
            format_timestamp(record.archived_at),
            reason_text,
            record.entry.id[:8],
            record.entry.project or "-",
            _first_line(record.entry.text),
        )
    console.print(Panel(table, title=title, border_style="cyan"))


def _archived_ids_newest_first() -> list[str]:
    snapshot = read_prompt_stash_archive(prompt_stash_path(), _FILTER_FETCH_CAP)
    seen: set[str] = set()
    ordered: list[str] = []
    for record in snapshot.records:
        if record.entry.id not in seen:
            seen.add(record.entry.id)
            ordered.append(record.entry.id)
    return ordered


def _resolve_prefix(prefix: str, candidates: list[str]) -> str:
    """Resolve a unique id prefix to a full archived id.

    Raises :class:`ValueError` naming the ambiguity or the unknown prefix.
    """
    if prefix in candidates:
        return prefix
    matches = [candidate for candidate in candidates if candidate.startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"unknown archived draft id: {prefix!r}")
    preview = ", ".join(match[:8] for match in matches[:5])
    if len(matches) > 5:
        preview += f", … and {len(matches) - 5} more"
    raise ValueError(f"ambiguous id prefix {prefix!r}: matches {preview}")


def _handle_stash_archive_restore(args: argparse.Namespace) -> int:
    """Restore archived drafts back to Stash by id or unique id prefix.

    Returns the process exit code: 0 when at least one draft was restored,
    1 when everything was skipped.
    """
    from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

    raw_ids: list[str] = [str(item) for item in (getattr(args, "ids", None) or [])]
    if not raw_ids:
        print("restore needs at least one draft id.", file=sys.stderr)
        return 2
    archived_ids = _archived_ids_newest_first()
    pairs: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    for raw in raw_ids:
        try:
            pairs.append((raw, _resolve_prefix(raw, archived_ids)))
        except ValueError as exc:
            skipped.append((raw, str(exc)))
    restored: list[str] = []
    if pairs:
        resolved = [full_id for _, full_id in pairs]
        outcome = recover_prompt_stash_archive(prompt_stash_path(), resolved)
        restored = list(outcome.changed)
        recovered_set = set(restored)
        if len(recovered_set) != len(resolved):
            lifecycle = read_prompt_stash_lifecycle(prompt_stash_path())
            active = {entry.id for entry in lifecycle.active}
            trashed = {record.entry.id for record in lifecycle.trash}
            for raw, full_id in pairs:
                if full_id in recovered_set:
                    continue
                if full_id in active:
                    skipped.append((raw, "already in Stash"))
                elif full_id in trashed:
                    skipped.append(
                        (raw, "in Trash: restore it from the Trash view instead")
                    )
                else:
                    skipped.append((raw, "not in archive"))
    for full_id in restored:
        print(f"Restored {full_id}")
    for raw, why in skipped:
        print(f"Skipped {raw}: {why}")
    return 0 if restored else 1


def _handle_stash_archive_show(args: argparse.Namespace) -> None:
    """Print one archived draft: metadata plus the full entry text."""
    raw_id = str(getattr(args, "id", ""))
    snapshot = read_prompt_stash_archive(prompt_stash_path(), _FILTER_FETCH_CAP)
    candidates = [record.entry.id for record in snapshot.records]
    try:
        full_id = _resolve_prefix(raw_id, candidates)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    record = next(item for item in snapshot.records if item.entry.id == full_id)
    if bool(getattr(args, "json", False)):
        json.dump(_record_to_json(record), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    _print_show_pretty(record)


def _print_show_pretty(record: PromptStashArchiveRecordWire) -> None:
    console = Console()
    entry = record.entry
    header = Table(show_header=False, box=None, pad_edge=False)
    header.add_column("FIELD", style="bold", no_wrap=True)
    header.add_column("VALUE")
    header.add_row("ID", entry.id)
    header.add_row("Archived", f"{record.archived_at} ({record.reason})")
    header.add_row("Project", entry.project or "-")
    header.add_row("Created", entry.created_at)
    header.add_row("Source", entry.source or "-")
    header.add_row("Pinned", "yes" if entry.pinned else "no")
    if record.trashed_at:
        header.add_row("Trashed", record.trashed_at)
    if entry.frontmatter:
        header.add_row("Frontmatter", entry.frontmatter.strip())
    console.print(Panel(header, title="Archived draft", border_style="cyan"))
    console.print(Panel(entry.text or "(empty)", title="Text"))
