"""Version chips and the launch row for the Agents-tab MEMORY lane.

The hint system carries :class:`MemoryVersionPin` entries (one per hint
number) so a row whose chip resolved to a committed version opens the
pager pinned to the version read, and the launch row opens ``AGENTS.md``
at the launch version (or its not-in-git snapshot).

Each audited memory read carries the blob OID the agent actually saw
(``MemoryReadEvent.blob_oid`` for a single note, ``included_blob_oids``
pairs for a batch). Resolving each blob through
``AceMemoryHistory.version_for_blob`` tells whether that version is still
current. The launch row resolves the workspace's root ``AGENTS.md`` from
the run's launch evidence (``agent_meta.json``) instead of from time.

All I/O runs on the caller's (worker) thread; every failure omits its
chip or row rather than raising.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.text import Text

CHIP_NOW_STYLE = "dim"
CHIP_PAST_STYLE = "#9d7cd8"
CHIP_UNCOMMITTED_STYLE = "#FFAF00"
CHIP_UNAVAILABLE_STYLE = "dim"

LAUNCH_GLYPH = "◇"


@dataclass(frozen=True)
class MemoryVersionChip:
    """One resolved version chip: text plus its Rich style."""

    text: str
    style: str

    def as_text(self) -> Text:
        """Return this chip as a Rich ``Text`` span."""
        return Text(f"  {self.text}", style=self.style)


@dataclass(frozen=True)
class MemoryLaunchRow:
    """The resolved ``AGENTS.md as launched`` row."""

    display: str
    chip: MemoryVersionChip | None
    blob_oid: str | None
    ordinal: int | None
    unavailable: bool = False


@dataclass(frozen=True)
class MemoryVersionPin:
    """A hint-numbered, version-pinned memory pager target.

    ``revision`` is a resolved ``vN`` ordinal selector (never a blob, so
    old wheels open it too). ``snapshot_path`` carries the not-in-git
    snapshot file for launch rows whose bytes were never committed;
    ``snapshot_title`` is its read-only document title.
    """

    scope_key: str
    repo_root: str
    subject: str
    revision: str
    title: str
    snapshot_path: str | None = None
    snapshot_title: str | None = None


def _chip_for_result(
    result: dict[str, Any] | str | None,
) -> MemoryVersionChip | None:
    """Return the per-read chip for a ``version_for_blob`` result.

    ``None`` (no blob, ambiguous prefix, unresolvable scope) renders no
    chip. A ``LookupError``-style miss is the caller's amber
    ``uncommitted`` chip; pass ``"uncommitted"`` as *result* for it.
    """
    if result is None:
        return None
    if result == "uncommitted":
        return MemoryVersionChip("◌ uncommitted at read", CHIP_UNCOMMITTED_STYLE)
    if not isinstance(result, dict):
        return None
    try:
        ordinal = int(result.get("ordinal", 0) or 0)
        newer_count = int(result.get("newer_count", 0) or 0)
        now_matches = bool(result.get("now_matches", False))
    except (AttributeError, TypeError, ValueError):
        return None
    if now_matches:
        return MemoryVersionChip("≡ now", CHIP_NOW_STYLE)
    if newer_count > 0:
        return MemoryVersionChip(f"v{ordinal} ⟲ {newer_count} newer", CHIP_PAST_STYLE)
    if ordinal > 0:
        return MemoryVersionChip(f"v{ordinal}", CHIP_PAST_STYLE)
    return None


def _aggregate_chip(
    results: list[dict[str, Any] | None | str],
) -> MemoryVersionChip | None:
    """Return one aggregate chip for a batch read's per-target results."""
    counted = [item for item in results if item is not None]
    if not counted:
        return None
    changed = sum(
        1
        for item in counted
        if item == "uncommitted"
        or (isinstance(item, dict) and not bool(item.get("now_matches", False)))
    )
    total = len(counted)
    if changed == 0:
        return MemoryVersionChip("≡ now", CHIP_NOW_STYLE)
    return MemoryVersionChip(f"⟲ {changed} of {total} changed", CHIP_PAST_STYLE)


def scope_for_event(event: Any, service: Any) -> Any | None:
    """Return the history scope for a memory-read event, or ``None``.

    Uses the same ``content_root`` resolution as the Memory pane's ring:
    the event's project resolves to a workspace root, falling back to
    the read's ``cwd``. An unresolvable scope omits the chips.
    """
    try:
        root: Path | None = None
        project = getattr(event, "project", "") or ""
        if project:
            try:
                from sase.memory.cli_common import resolve_memory_cli_project

                resolved = resolve_memory_cli_project(project)
                if resolved is not None:
                    root = Path(resolved.project_root)
            except Exception:
                root = None
        if root is None:
            cwd = getattr(event, "cwd", "") or ""
            if cwd:
                root = Path(str(cwd)).expanduser()
        if root is None:
            return None
        return service.project_scope(root)
    except Exception:
        return None


def core_selector_for_target(target: str, repo_root: Path) -> str:
    """Translate a read target to a core history selector (fail-open)."""
    try:
        from sase.memory.history.cli_history_selectors import (
            translate_history_selector,
        )

        return translate_history_selector(target, repo_root)
    except Exception:
        return target


def resolve_event_chips(
    event: Any,
    *,
    history: Any,
    service: Any,
) -> tuple[MemoryVersionChip | None, list[tuple[str, int | None]]]:
    """Resolve one event's chip plus per-target ``(target, ordinal)`` pins.

    Returns ``(chip, pins)``. Single-note reads yield one per-read chip;
    batch reads yield one aggregate chip. Pins name the resolved ordinal
    for each target with a blob (``None`` when unresolvable) so hints can
    open the pager at the version read.
    """
    scope = scope_for_event(event, service)
    if scope is None:
        return None, []
    try:
        repo_root = Path(str(getattr(scope, "repo_root", "") or ""))
    except Exception:
        return None, []
    pairs = _event_blob_pairs(event)
    if not pairs:
        return None, []
    results: list[dict[str, Any] | None | str] = []
    pins: list[tuple[str, int | None]] = []
    for target, oid in pairs:
        if not oid:
            pins.append((target, None))
            continue
        selector = core_selector_for_target(target, repo_root)
        try:
            result = history.version_for_blob(scope, selector, oid)
        except LookupError:
            results.append("uncommitted")
            pins.append((target, None))
            continue
        except Exception:
            pins.append((target, None))
            continue
        results.append(result)
        try:
            pins.append((target, int(result.get("ordinal", 0) or 0) or None))
        except (AttributeError, TypeError, ValueError):
            pins.append((target, None))
    if len(results) == 1 and len(pairs) == 1 and results[0] not in (None,):
        first = results[0]
        chip = _chip_for_result(first if isinstance(first, dict) else first)
        return chip, pins
    chip = _aggregate_chip(results)
    return chip, pins


def _event_blob_pairs(event: Any) -> list[tuple[str, str | None]]:
    """Return ``(target, blob_oid)`` pairs for one read event."""
    included = getattr(event, "included_blob_oids", ()) or ()
    if included:
        pairs: list[tuple[str, str | None]] = []
        for entry in included:
            try:
                target, oid = entry
            except (TypeError, ValueError):
                continue
            pairs.append((str(target), str(oid) if oid else None))
        if pairs:
            return pairs
    selectors = tuple(getattr(event, "selectors", ()) or ())
    targets = list(selectors) or [getattr(event, "canonical_path", "") or ""]
    blob = getattr(event, "blob_oid", None)
    oid = str(blob) if blob else None
    return [(str(target), oid) for target in targets if str(target)]


def _read_launch_evidence(agent: Any) -> dict[str, Any]:
    """Return the parsed ``agent_meta.json`` for *agent* (fail-open)."""
    try:
        artifacts_dir = agent.get_artifacts_dir()
    except Exception:
        return {}
    if not artifacts_dir:
        return {}
    try:
        raw = (Path(str(artifacts_dir)) / "agent_meta.json").read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_launch_row(
    agent: Any,
    *,
    history: Any,
    service: Any,
) -> MemoryLaunchRow | None:
    """Resolve the ``AGENTS.md as launched`` row for *agent*.

    Uses the run's ``instruction_snapshot`` entry for the workspace root
    ``AGENTS.md``, falling back to ``workspace_head``. Returns ``None``
    when the agent predates evidence capture or no scope resolves: those
    agents show no launch row. A snapshot whose bytes match no committed
    blob yields the not-in-git row; gone snapshot bytes yield the
    unavailable row.
    """
    workspace_dir = getattr(agent, "workspace_dir", None)
    if not workspace_dir:
        return None
    try:
        scope = service.project_scope(Path(str(workspace_dir)))
    except Exception:
        return None
    evidence = _read_launch_evidence(agent)
    snapshots = evidence.get("instruction_snapshot", ())
    if not isinstance(snapshots, (list, tuple)):
        snapshots = ()
    entry = _root_agents_entry(snapshots, Path(str(workspace_dir)))
    if entry is not None:
        return _launch_row_from_snapshot(entry, scope=scope, history=history)
    head = evidence.get("workspace_head")
    if isinstance(head, str) and head.strip():
        return _launch_row_from_head(head.strip(), scope=scope, service=service)
    return None


def _root_agents_entry(snapshots: Any, workspace_dir: Path) -> dict[str, Any] | None:
    """Return the snapshot entry for the workspace root ``AGENTS.md``."""
    try:
        wanted = (workspace_dir / "AGENTS.md").resolve(strict=False)
    except OSError:
        return None
    for entry in snapshots:
        if not isinstance(entry, dict):
            continue
        raw_path = entry.get("path")
        if not raw_path:
            continue
        try:
            candidate = Path(str(raw_path)).resolve(strict=False)
        except OSError:
            continue
        if candidate == wanted:
            return dict(entry)
    return None


def _launch_row_from_snapshot(
    entry: dict[str, Any], *, scope: Any, history: Any
) -> MemoryLaunchRow | None:
    """Build the launch row from one ``instruction_snapshot`` entry."""
    oid = entry.get("blob_oid")
    blob = str(oid) if isinstance(oid, str) and oid else None
    if not blob:
        return MemoryLaunchRow(
            display="AGENTS.md",
            chip=MemoryVersionChip("snapshot unavailable", CHIP_UNAVAILABLE_STYLE),
            blob_oid=None,
            ordinal=None,
            unavailable=True,
        )
    try:
        result = history.version_for_blob(scope, "AGENTS.md", blob)
    except LookupError:
        chip = MemoryVersionChip("◌ as launched · not in git", CHIP_UNCOMMITTED_STYLE)
        if not _snapshot_bytes_present(blob):
            chip = MemoryVersionChip("snapshot unavailable", CHIP_UNAVAILABLE_STYLE)
            return MemoryLaunchRow(
                display="AGENTS.md",
                chip=chip,
                blob_oid=blob,
                ordinal=None,
                unavailable=True,
            )
        return MemoryLaunchRow(
            display="AGENTS.md", chip=chip, blob_oid=blob, ordinal=None
        )
    except Exception:
        return MemoryLaunchRow(
            display="AGENTS.md",
            chip=MemoryVersionChip("snapshot unavailable", CHIP_UNAVAILABLE_STYLE),
            blob_oid=blob,
            ordinal=None,
            unavailable=True,
        )
    try:
        ordinal = int(result.get("ordinal", 0) or 0)
        newer_count = int(result.get("newer_count", 0) or 0)
        now_matches = bool(result.get("now_matches", False))
    except (AttributeError, TypeError, ValueError):
        return None
    if now_matches:
        chip = MemoryVersionChip("≡ now", CHIP_NOW_STYLE)
    elif newer_count > 0:
        chip = MemoryVersionChip(
            f"v{ordinal} ⟲ {newer_count} newer since launch", CHIP_PAST_STYLE
        )
    else:
        chip = MemoryVersionChip(f"v{ordinal}", CHIP_PAST_STYLE)
    return MemoryLaunchRow(
        display="AGENTS.md", chip=chip, blob_oid=blob, ordinal=ordinal or None
    )


def _launch_row_from_head(
    head: str, *, scope: Any, service: Any
) -> MemoryLaunchRow | None:
    """Build the launch row from a ``workspace_head`` commit fallback."""
    try:
        resolved = service.resolve(scope, "AGENTS.md", at_commit=head)
    except Exception:
        return None
    version = resolved.get("version") if isinstance(resolved, dict) else None
    if not isinstance(version, dict):
        return None
    try:
        ordinal = int(version.get("ordinal", 0) or 0)
    except (TypeError, ValueError):
        return None
    if ordinal <= 0:
        return None
    blob = version.get("blob_oid")
    blob_oid = str(blob) if isinstance(blob, str) and blob else None
    try:
        timeline = service.timeline(scope, "AGENTS.md", include_hidden=True)
        committed = [
            int(row.get("ordinal", 0) or 0)
            for row in timeline.get("versions", ())
            if isinstance(row, dict) and int(row.get("ordinal", 0) or 0) > 0
        ]
        newest = max(committed) if committed else ordinal
    except Exception:
        newest = ordinal
    newer_count = max(0, newest - ordinal)
    if newer_count > 0:
        chip = MemoryVersionChip(
            f"v{ordinal} ⟲ {newer_count} newer since launch", CHIP_PAST_STYLE
        )
    else:
        chip = MemoryVersionChip("≡ now", CHIP_NOW_STYLE)
    return MemoryLaunchRow(
        display="AGENTS.md", chip=chip, blob_oid=blob_oid, ordinal=ordinal
    )


def _snapshot_bytes_present(blob: str) -> bool:
    """Return whether the not-in-git snapshot bytes are still stored."""
    try:
        return (Path.home() / ".sase" / "instruction_snapshots" / blob).is_file()
    except OSError:
        return False


__all__ = [
    "CHIP_NOW_STYLE",
    "CHIP_PAST_STYLE",
    "CHIP_UNAVAILABLE_STYLE",
    "CHIP_UNCOMMITTED_STYLE",
    "LAUNCH_GLYPH",
    "MemoryLaunchRow",
    "MemoryVersionChip",
    "MemoryVersionPin",
    "core_selector_for_target",
    "resolve_event_chips",
    "resolve_launch_row",
    "scope_for_event",
]
