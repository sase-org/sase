"""Fast-path candidates for plans awaiting approval (``pending_plan`` kind).

Offers the display names of visible pending plan proposals, newest first,
for the ``sase plan approve`` / ``sase plan reject`` PLAN slot. Each
description reads ``tier · title · @agent · age``.

Import contract: module scope stays on the stdlib plus this package (see
:mod:`sase.completion.candidates.catalog`). Every real dependency is
imported inside its function, and only the light ones: ``sase.core.paths``,
``sase.core.rust``, ``sase.core.agent_scan_facade``, and
``sase.plan_names``. In particular this module never imports
``sase.notifications``, ``sase.gate_shell``, ``sase.sdd``, ``sase.ace``,
or ``rich`` — those packages cost about 75 ms of import plus about 150 ms
per snapshot read, which would blow the completion latency budget.

Visibility mirrors the resolver's gate-owned rule
(:mod:`sase.main.plan_candidates`) with two documented approximations that
keep the fast path light:

- "Available" is decided from the bundle markers, the pending-action
  store, and the 24h staleness window, without the adapter registry.
- A proposal with no gate-shell record (a legacy gate) counts as visible
  while its notification is not dismissed. The resolver additionally
  requires a live planner row, which the fast path cannot see; offering a
  legacy orphan here only costs the resolver's miss diagnosis.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.completion.candidates.catalog_support import dedupe
from sase.completion.candidates.protocol import Candidate

_PLAN_APPROVAL_ACTIONS = frozenset({"PlanApproval", "EpicApproval"})
_STALE_THRESHOLD_SECONDS = 24 * 60 * 60

#: Terminal gate-shell states. Local pin of
#: ``sase.gate_shell.state.TERMINAL_GATE_STATES``: importing that module
#: would drag the gate-shell package onto the completion fast path, so this
#: copy stays and a parity test fails if the two drift.
PENDING_PLAN_TERMINAL_GATE_STATES = frozenset(
    {"answered", "completed", "failed", "timeout", "stopped", "lost"}
)

_ADAPTER_KIND_BY_ACTION = {
    "PlanApproval": "plan",
    "EpicApproval": "epic_plan",
}
_PLAN_REQUEST_FILENAME = "plan_request.json"
_PLAN_RESPONSE_FILENAME = "plan_response.json"
_NEUTRAL_RESPONSE_FILENAME = "response.json"
_NEUTRAL_CANCELLATION_FILENAME = "cancellation.json"
_APPROVED_MARKER_FILENAME = "plan_approved.marker"
_FRONTMATTER_READ_BYTES = 8192


def pending_plan_source_path(_project: str | None) -> Path | None:
    """Return the notification JSONL whose mtime invalidates candidates."""
    from sase.core.paths import sase_subdir

    return sase_subdir("notifications") / "notifications.jsonl"


def pending_plan_candidates(_project: str | None) -> list[Candidate]:
    """Return display names of visible pending proposals, newest first."""
    from sase.plan_names import plan_display_names

    rows = _load_plan_approval_rows()
    if not rows:
        return []
    store = _load_pending_action_store()
    now = time.time()
    visible = [
        row
        for row in rows
        if _row_is_available(row, store, now) and _row_is_gate_visible(row)
    ]
    visible.sort(key=_row_sort_key, reverse=True)
    archives = [_archive_path_for_row(row) or "" for row in visible]
    display = plan_display_names(
        [
            path or str(row.get("id") or "")
            for path, row in zip(archives, visible, strict=True)
        ]
    )
    candidates = []
    for row, archive in zip(visible, archives, strict=True):
        key = archive or str(row.get("id") or "")
        value = display.get(key, key)
        candidates.append(Candidate(value, _describe_row(row, archive)))
    return dedupe(candidates)


def _load_plan_approval_rows() -> list[dict[str, Any]]:
    """Read plan-approval notification rows through the Rust binding."""
    from sase.core.paths import sase_subdir
    from sase.core.rust import require_rust_binding

    try:
        snapshot = require_rust_binding("read_notifications_snapshot")(
            str(sase_subdir("notifications") / "notifications.jsonl"),
            True,
            False,
        )
    except Exception:
        return []
    rows = snapshot.get("notifications") if isinstance(snapshot, dict) else None
    if not isinstance(rows, list):
        return []
    return [
        row
        for row in rows
        if isinstance(row, dict) and row.get("action") in _PLAN_APPROVAL_ACTIONS
    ]


def _load_pending_action_store() -> dict[str, Any]:
    """Read the pending-action store (with legacy rows) through Rust."""
    from sase.core.paths import sase_subdir
    from sase.core.rust import require_rust_binding

    try:
        store = require_rust_binding("read_pending_action_store")(
            str(sase_subdir("pending_actions") / "actions.json"),
            str(sase_subdir("telegram") / "pending_actions.json"),
        )
    except Exception:
        return {}
    return dict(store) if isinstance(store, dict) else {}


def _row_is_available(row: dict[str, Any], store: dict[str, Any], now: float) -> bool:
    """Mirror the pending-action ``available`` state for one row."""
    action = row.get("action")
    action_data = row.get("action_data")
    if not isinstance(action_data, dict):
        return False
    bundle = _resolve_bundle(action, action_data)
    if bundle is None:
        return False
    if _bundle_is_terminal(action, bundle):
        return False
    pending = _store_entry_for(store, row.get("id"))
    if pending is not None:
        if pending.get("state") == "already_handled":
            return False
        try:
            deadline = float(pending.get("stale_deadline_unix", 0.0))
        except (TypeError, ValueError):
            deadline = 0.0
        if pending.get("state") == "stale" or deadline <= now:
            return False
    elif _row_is_stale(row.get("timestamp"), now):
        return False
    return True


def _resolve_bundle(
    action: Any, action_data: dict[str, Any]
) -> tuple[Path, Path, Path, bool] | None:
    """Resolve one plan-approval row to bundle paths, neutral first.

    Returns ``(root, request, response, legacy)`` mirroring
    ``resolve_action_bundle`` for the plan adapters, or ``None`` when no
    bundle directory is recorded.
    """
    from sase.core.paths import sase_subdir

    adapter_kind = _ADAPTER_KIND_BY_ACTION.get(str(action))
    if adapter_kind is None:
        return None
    request_id = str(action_data.get("request_id") or "").strip()
    request_kind = str(action_data.get("request_kind") or adapter_kind).strip()
    if request_id:
        root = sase_subdir("interaction_requests") / request_kind / request_id
        request = root / "request.json"
        try:
            if request.is_file():
                return (
                    root,
                    request,
                    root / _NEUTRAL_RESPONSE_FILENAME,
                    False,
                )
        except OSError:
            return None
    legacy_dir = str(action_data.get("response_dir") or "").strip()
    if not legacy_dir:
        return None
    root = Path(legacy_dir).expanduser()
    return (
        root,
        root / _PLAN_REQUEST_FILENAME,
        root / _PLAN_RESPONSE_FILENAME,
        True,
    )


def _bundle_is_terminal(action: Any, bundle: tuple[Path, Path, Path, bool]) -> bool:
    """Mirror ``gate_notification_is_terminal`` from bundle markers."""
    root, request, response, _legacy = bundle
    try:
        if response.exists():
            return True
        if (root / _NEUTRAL_CANCELLATION_FILENAME).exists():
            return True
        if (
            str(action) == "PlanApproval"
            and (root / _APPROVED_MARKER_FILENAME).exists()
        ):
            return True
        return root.is_dir() and not request.exists()
    except OSError:
        return False


def _store_entry_for(store: dict[str, Any], notification_id: Any) -> Any:
    actions = store.get("actions")
    if not isinstance(actions, dict):
        return None
    return next(
        (
            entry
            for entry in actions.values()
            if isinstance(entry, dict)
            and entry.get("notification_id") == notification_id
        ),
        None,
    )


def _row_is_stale(timestamp: Any, now: float) -> bool:
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return False
    return parsed.timestamp() + _STALE_THRESHOLD_SECONDS <= now


def _row_is_gate_visible(row: dict[str, Any]) -> bool:
    """Mirror the gate-owned visibility rule for one available row."""
    action_data = row.get("action_data")
    if not isinstance(action_data, dict):
        return False
    terminal = _gate_shell_terminal(_gate_id_for_row(action_data))
    if terminal is None:
        # No gate-shell record (a legacy gate) or an unreadable index:
        # stay visible while the inbox row is not dismissed.
        return not bool(row.get("dismissed"))
    return not terminal


def _gate_id_for_row(action_data: dict[str, Any]) -> str | None:
    """Return the gate id owning one row, mirroring the resolver."""
    request_id = str(action_data.get("request_id") or "").strip()
    if request_id:
        return request_id
    for key in ("bundle_path", "response_dir"):
        raw = str(action_data.get(key) or "").strip()
        if raw:
            return Path(raw).expanduser().name or None
    return None


def _gate_shell_terminal(gate_id: str | None) -> bool | None:
    """Return whether one gate id settled, or ``None`` without a record."""
    if not gate_id:
        return None
    from sase.core import agent_scan_facade

    try:
        record = agent_scan_facade.find_gate_shell_by_gate_id(
            agent_scan_facade.default_agent_artifact_index_path(),
            None,
            gate_id,
        )
    except Exception:
        return None
    if record is None:
        return None
    shell = getattr(getattr(record, "agent_meta", None), "agent_session_shell", None)
    state = getattr(shell, "state", None) or "pending"
    return state in PENDING_PLAN_TERMINAL_GATE_STATES


def _archive_path_for_row(row: dict[str, Any]) -> str | None:
    """Return the durable proposal file recorded on one row, if any."""
    action_data = row.get("action_data")
    if isinstance(action_data, dict):
        explicit = str(action_data.get("original_plan_file") or "").strip()
        if explicit:
            return explicit
    files = row.get("files")
    if isinstance(files, list) and files and str(files[0]).endswith(".md"):
        return str(files[0])
    return None


def _describe_row(row: dict[str, Any], archive: str | None) -> str:
    """Render one candidate description: ``tier · title · @agent · age``."""
    action_data = row.get("action_data")
    data: dict[str, Any] = action_data if isinstance(action_data, dict) else {}
    title, file_tier = _scan_plan_frontmatter(archive)
    tier = str(data.get("plan_tier") or "").strip().lower()
    if tier not in {"tale", "epic"}:
        tier = file_tier if file_tier in {"tale", "epic"} else ""
    if not tier:
        tier = "epic" if row.get("action") == "EpicApproval" else "tale"
    agent = (
        str(data.get("agent_name") or "").strip()
        or str(data.get("agent_cl_name") or "").strip()
        or "-"
    )
    parts = [tier]
    if title:
        parts.append(title)
    parts.append(f"@{agent}")
    age = _short_age(row.get("timestamp"))
    if age:
        parts.append(age)
    return " · ".join(parts)


def _scan_plan_frontmatter(path: str | None) -> tuple[str | None, str | None]:
    """Return ``(title, tier)`` from one plan file's frontmatter."""
    if not path:
        return None, None
    try:
        with open(Path(path).expanduser(), encoding="utf-8") as handle:
            text = handle.read(_FRONTMATTER_READ_BYTES)
    except (OSError, UnicodeDecodeError):
        return None, None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    end = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() in ("---", "...")
        ),
        None,
    )
    if end is None:
        return None, None
    title: str | None = None
    tier: str | None = None
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if not separator:
            continue
        name = key.strip().lower()
        if name not in ("title", "tier"):
            continue
        cleaned = _unquote(value.strip())
        if not cleaned:
            continue
        if name == "title" and title is None:
            title = " ".join(cleaned.split())
        elif name == "tier" and tier is None:
            tier = cleaned.strip().lower()
    return title, tier


def _unquote(value: str) -> str:
    """Strip one layer of matching single or double quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _short_age(timestamp: Any) -> str:
    """Format an ISO-8601 timestamp as a short age like ``4m``."""
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return ""
    total_seconds = int((datetime.now().astimezone() - parsed).total_seconds())
    if total_seconds < 0:
        return "now"
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"


def _parse_timestamp(timestamp: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, assuming local time when naive."""
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def _row_sort_key(row: dict[str, Any]) -> datetime:
    """Sort key for newest-first ordering; malformed timestamps sink."""
    return _parse_timestamp(row.get("timestamp")) or datetime.min.replace(
        tzinfo=datetime.now().astimezone().tzinfo
    )


__all__ = [
    "PENDING_PLAN_TERMINAL_GATE_STATES",
    "pending_plan_candidates",
    "pending_plan_source_path",
]
