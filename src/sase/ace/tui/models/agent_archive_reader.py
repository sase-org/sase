"""Archived identity, placeholders, and retained-content helpers.

Archive-reader seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
Identity copy and light-row facts live here; hydration I/O lives in the
actions module. The ``_archive_read_only`` flag on Agent is the live-path
guard and is never serialized.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.text import Text

from .agent_archive_view import ARCHIVE_IDENTITY_ACCENT, ARCHIVE_IDENTITY_KIND

ARCHIVE_LOADING_TITLE = "Loading archived run…"
ARCHIVE_UNREADABLE_TITLE = "Archive entry unreadable — Record only"
ARCHIVE_MISSING_CONTEXT = (
    "Context not retained — the chat file was removed by retention"
)
ARCHIVE_MISSING_REPLY = "Reply not retained — the chat file was removed by retention"
ARCHIVE_MISSING_FILES = "Files not retained — the chat file was removed by retention"
ARCHIVE_MISSING_TOOLS = "Tools not retained — the chat file was removed by retention"
ARCHIVE_MISSING_FINAL = "FINAL not retained — the chat file was removed by retention"

_TIME_BASIS_WORDS = {
    "ended": "Ended",
    "started": "Started",
    "dismissed": "Dismissed",
}


@dataclass
class ArchiveReaderRuntime:
    """Transient per-app Archive reader state (never persisted, never Inbox)."""

    archive_key: str | None = None
    generation: int = 0
    hydrated_agent: Any = None
    unreadable: bool = False
    loading: bool = False
    retained: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    bundle_path: str | None = None
    light_row: Mapping[str, Any] | None = field(default=None)


def mark_agent_archive_read_only(agent: Any) -> Any:
    """Stamp ``agent`` as an Archive hydration that must not take live paths."""
    agent._archive_read_only = True
    return agent


def titled_archive_card(title: str, detail: str = "") -> Text:
    """Return a titled missing/loading/unreadable card body."""
    body = Text()
    body.append(title, style="bold #d7af5f")
    if detail:
        body.append(f"\n{detail}", style="dim")
    return body


def archive_identity_header_from_light_row(
    row: Mapping[str, Any] | None,
    *,
    loading: bool = False,
    unreadable: bool = False,
    retained: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
    dismissed_at: str | None = None,
) -> Any:
    """Build the archived identity header from a core light row (no bundle)."""
    from ..widgets.prompt_panel._identity_header import IdentityHeader

    name = "archived run"
    if row:
        name = str(row.get("agent_name") or row.get("name") or name)
    expanded = Text()
    expanded.append(f"{name}\n", style="bold")
    if row:
        status = str(row.get("status") or "")
        outcome = str(row.get("outcome") or "")
        basis = str(row.get("time_basis") or "")
        stamp = str(row.get("last_activity_at") or row.get("start_time") or "")
        runtime = row.get("runtime_seconds")
        model = str(row.get("model") or "")
        if status:
            expanded.append(f"Stored status: {status}\n", style="dim")
        if outcome:
            expanded.append(f"Outcome: {outcome}\n")
        if basis and stamp:
            expanded.append(f"{_time_basis_word(basis)}: {stamp}\n")
        elif stamp:
            expanded.append(f"Time: {stamp}\n")
        if runtime not in (None, ""):
            expanded.append(f"Runtime: {runtime}s\n")
        if model:
            expanded.append(f"Model: {model}\n")
    dismissed = dismissed_at or (None if row is None else row.get("dismissed_at"))
    basis = str(row.get("time_basis") or "") if row else ""
    stamp = (
        str(row.get("last_activity_at") or row.get("start_time") or "") if row else ""
    )
    if dismissed and not (basis == "dismissed" and str(dismissed) == stamp):
        expanded.append(f"Dismissed: {dismissed}\n")
    if loading:
        expanded.append(f"{ARCHIVE_LOADING_TITLE}\n", style="italic #d7af5f")
    if unreadable:
        expanded.append(f"{ARCHIVE_UNREADABLE_TITLE}\n", style="italic #d7af5f")
    if retained:
        expanded.append("Retained: " + ", ".join(retained) + "\n", style="dim")
    if missing:
        expanded.append("Missing: " + ", ".join(missing) + "\n", style="dim")
    compact = Text(name)
    if row and row.get("status"):
        compact.append(f" · {row.get('status')}")
    compact.append("\n")
    return IdentityHeader(
        kind_label=ARCHIVE_IDENTITY_KIND,
        accent=ARCHIVE_IDENTITY_ACCENT,
        expanded=expanded,
        compact=compact,
    )


def _time_basis_word(basis: str) -> str:
    """Return the identity-header time label for a light-row time basis."""
    return _TIME_BASIS_WORDS.get(basis, basis.title() or "Time")


def archive_container_summary_text(
    row: Mapping[str, Any] | None,
    members: tuple[Mapping[str, Any], ...],
) -> Text:
    """Summary card body for a container selection (light members only)."""
    text = Text()
    name = "container"
    if row:
        name = str(
            row.get("agent_name") or row.get("container_key") or row.get("name") or name
        )
    text.append(f"{name}\n", style=f"bold {ARCHIVE_IDENTITY_ACCENT}")
    text.append(f"{len(members)} matching member(s)\n", style="dim")
    for member in members:
        member_name = str(member.get("agent_name") or member.get("name") or "member")
        outcome = str(member.get("outcome") or member.get("status") or "")
        line = f"  {member_name}"
        if outcome:
            line += f"  {outcome}"
        text.append(line + "\n")
    return text


def resolve_archive_bundle_path(
    row: Mapping[str, Any] | None,
    archive_root: Path | None,
) -> Path | None:
    """Resolve the on-disk bundle for one light row without writing anything."""
    if row:
        explicit = row.get("bundle_path")
        if isinstance(explicit, str) and explicit:
            path = Path(explicit)
            if path.is_file():
                return path
    run_id = None
    archive_key = None if row is None else row.get("archive_key")
    if isinstance(archive_key, Mapping):
        run_id = archive_key.get("source_run_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    filename = f"{run_id}.json"
    roots: list[Path] = []
    if archive_root is not None:
        roots.append(archive_root)
        nested = archive_root / "bundles"
        if nested.is_dir():
            roots.append(nested)
    try:
        from sase.ace.dismissed_agents import dismissed_bundles_dir

        default_root = dismissed_bundles_dir()
        if default_root not in roots:
            roots.append(default_root)
    except Exception:
        pass
    from sase.ace.dismissed_agents_paths import find_bundle

    for root in roots:
        found = find_bundle(root, filename)
        if found is not None:
            return found
        direct = root / filename
        if direct.is_file():
            return direct
    return None


def probe_retained_archive_content(
    agent: Any,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Classify retained vs missing decks from a hydrated agent (off-thread)."""
    retained: list[str] = []
    missing: list[str] = []

    prompt = getattr(agent, "raw_prompt", None) or getattr(agent, "prompt", None)
    if not prompt:
        for name in ("get_raw_prompt_content", "get_prompt_content"):
            getter = getattr(agent, name, None)
            if not callable(getter):
                continue
            try:
                prompt = getter()
            except Exception:
                prompt = None
            if prompt:
                break
    (retained if prompt else missing).append("context")

    reply = None
    for name in ("get_response_content", "get_live_reply_content"):
        getter = getattr(agent, name, None)
        if not callable(getter):
            continue
        try:
            reply = getter()
        except Exception:
            reply = None
        if reply:
            break
    (retained if reply else missing).append("reply")

    has_files = bool(
        getattr(agent, "all_files", None)
        or getattr(agent, "extra_files", None)
        or getattr(agent, "diff_path", None)
    )
    (retained if has_files else missing).append("files")

    has_tools = bool(
        getattr(agent, "llm_calls", None) or getattr(agent, "tool_calls", None)
    )
    (retained if has_tools else missing).append("tools")

    has_final = getattr(agent, "finalizer_status", None) is not None
    (retained if has_final else missing).append("final")
    return tuple(retained), tuple(missing)


__all__ = [
    "ARCHIVE_LOADING_TITLE",
    "ARCHIVE_MISSING_CONTEXT",
    "ARCHIVE_MISSING_FILES",
    "ARCHIVE_MISSING_FINAL",
    "ARCHIVE_MISSING_REPLY",
    "ARCHIVE_MISSING_TOOLS",
    "ARCHIVE_UNREADABLE_TITLE",
    "ArchiveReaderRuntime",
    "archive_container_summary_text",
    "archive_identity_header_from_light_row",
    "mark_agent_archive_read_only",
    "probe_retained_archive_content",
    "resolve_archive_bundle_path",
    "titled_archive_card",
]
