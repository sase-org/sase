"""Read-only inventory for ``sase plan list``."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_helpers import path_key, read_json_object
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import iter_sharded_files, sase_home, sase_projects_dir
from sase.core.time import get_timezone
from sase.main.plan_candidates import visible_pending_plan_notifications
from sase.notifications.models import Notification, format_relative_time
from sase.notifications.pending_actions import PENDING_ACTION_PREFIX_LEN

_APPROVED_LIMIT = 10
_REJECTED_LIMIT = 10
_REJECTED_NOTE = (
    "inferred from archived proposal not represented by proposed/approved state"
)
_APPROVED_META_CANDIDATE_LIMIT = 2_000


@dataclass(frozen=True)
class _ProposedPlan:
    _plan_key: str
    id_prefix: str
    notification_id: str
    timestamp: str
    age: str
    agent: str
    project: str
    provider_model: str
    plan_path: str
    tier: str
    response_dir: str


@dataclass(frozen=True)
class _ApprovedPlan:
    _plan_key: str
    timestamp: str
    age: str
    action: str
    agent: str
    project: str
    provider_model: str
    plan_path: str
    tier: str
    meta_path: str


@dataclass(frozen=True)
class _RejectedPlan:
    timestamp: str
    age: str
    plan_path: str
    tier: str
    note: str = _REJECTED_NOTE


@dataclass(frozen=True)
class _PlanInventory:
    proposed: tuple[_ProposedPlan, ...]
    approved: tuple[_ApprovedPlan, ...]
    rejected: tuple[_RejectedPlan, ...]
    total_archived_proposals: int
    tier_filter: tuple[str, ...] = ()


@dataclass(frozen=True)
class _DisplayPathRoots:
    sase_root: Path
    home: Path


def build_plan_inventory(
    *,
    approved_limit: int = _APPROVED_LIMIT,
    rejected_limit: int = _REJECTED_LIMIT,
    tiers: tuple[str, ...] = (),
) -> _PlanInventory:
    """Build the current plan proposal/approval inventory."""
    display_roots = _display_path_roots()
    tier_set = set(tiers)
    proposed = _collect_proposed_plans(display_roots=display_roots)
    approved = _collect_approved_plans(
        limit=approved_limit,
        display_roots=display_roots,
        tiers=tier_set,
    )

    represented_paths = {row._plan_key for row in proposed if row._plan_key} | {
        row._plan_key for row in approved if row._plan_key
    }
    archived_paths = _archived_plan_paths()
    rejected = _collect_rejected_plans(
        archived_paths,
        represented_paths=represented_paths,
        limit=rejected_limit,
        display_roots=display_roots,
        tiers=tier_set,
    )

    if tier_set:
        proposed = tuple(row for row in proposed if row.tier in tier_set)

    return _PlanInventory(
        proposed=proposed,
        approved=approved,
        rejected=rejected,
        total_archived_proposals=len(archived_paths),
        tier_filter=tiers,
    )


def plan_inventory_to_json(inventory: _PlanInventory) -> dict[str, object]:
    """Return a stable JSON projection for a plan inventory."""
    return {
        "summary": {
            "proposed": len(inventory.proposed),
            "approved_shown": len(inventory.approved),
            "rejected_shown": len(inventory.rejected),
            "total_archived_proposals": inventory.total_archived_proposals,
            **(
                {
                    "tier_filter": list(inventory.tier_filter),
                    "by_tier": _tier_counts(inventory),
                }
                if inventory.tier_filter
                else {}
            ),
        },
        "proposed": [_public_row_dict(row) for row in inventory.proposed],
        "approved": [_public_row_dict(row) for row in inventory.approved],
        "rejected": [asdict(row) for row in inventory.rejected],
    }


def render_plan_inventory(
    inventory: _PlanInventory, *, console: Any | None = None
) -> None:
    """Render the inventory as a compact Rich dashboard."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    rich_console = console or Console()

    summary = Table.grid(expand=True)
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_row(
        _summary_cell("Proposed", len(inventory.proposed), "yellow"),
        _summary_cell("Approved shown", len(inventory.approved), "green"),
        _summary_cell("Rejected shown", len(inventory.rejected), "red"),
        _summary_cell("Archived total", inventory.total_archived_proposals, "cyan"),
    )
    rich_console.print(
        Panel(summary, title="Plan Pipeline", border_style="cyan", box=box.ROUNDED)
    )
    if inventory.tier_filter:
        counts = _tier_counts(inventory)
        rich_console.print(
            "Tier filter: "
            + ", ".join(
                f"[{_tier_style(tier)}]{tier}[/]: {counts[tier]}"
                for tier in inventory.tier_filter
            )
        )

    rich_console.print(
        _section_panel(
            "Proposed",
            _proposed_table(inventory.proposed),
            empty="No pending plan proposals.",
            border_style="yellow",
        )
    )
    rich_console.print(
        _section_panel(
            "Approved",
            _approved_table(inventory.approved),
            empty="No approved plans found.",
            border_style="green",
        )
    )
    rich_console.print(
        _section_panel(
            "Rejected",
            _rejected_table(inventory.rejected),
            empty="No inferred rejected plans.",
            border_style="red",
        )
    )


def _collect_proposed_plans(
    *,
    display_roots: _DisplayPathRoots,
) -> tuple[_ProposedPlan, ...]:
    notifications = visible_pending_plan_notifications()
    return tuple(
        _proposed_plan_from_notification(notification, display_roots=display_roots)
        for notification in notifications
    )


def _proposed_plan_from_notification(
    notification: Notification,
    *,
    display_roots: _DisplayPathRoots,
) -> _ProposedPlan:
    action_data = notification.action_data
    plan_path = _first_str(*notification.files, action_data.get("plan_file"))
    provider_model = _provider_model_label(
        action_data.get("llm_provider"),
        action_data.get("model"),
    )
    return _ProposedPlan(
        _plan_key=path_key(plan_path) if plan_path else "",
        id_prefix=notification.id[:PENDING_ACTION_PREFIX_LEN],
        notification_id=notification.id,
        timestamp=notification.timestamp,
        age=format_relative_time(notification.timestamp),
        agent=_first_str(
            action_data.get("agent_name"),
            action_data.get("agent_cl_name"),
        )
        or "-",
        project=_project_from_action_data(action_data),
        provider_model=provider_model,
        plan_path=_display_path(plan_path, display_roots=display_roots),
        tier=_tier_for_path(plan_path),
        response_dir=_display_path(
            action_data.get("response_dir"),
            display_roots=display_roots,
        ),
    )


def _collect_approved_plans(
    *,
    limit: int,
    display_roots: _DisplayPathRoots,
    tiers: set[str],
) -> tuple[_ApprovedPlan, ...]:
    target = max(limit, 0)
    if target <= 0:
        return ()

    by_plan_key: dict[str, tuple[datetime, _ApprovedPlan]] = {}
    scanned = 0
    for meta_path in _agent_meta_paths_newest_first():
        if scanned >= _APPROVED_META_CANDIDATE_LIMIT:
            break
        scanned += 1
        meta = read_json_object(meta_path)
        if not _truthy(meta.get("plan_approved")):
            continue
        plan_path = _first_str(meta.get("plan_path"), meta.get("sdd_plan_path"))
        if not plan_path:
            continue
        timestamp = _approval_timestamp(meta, meta_path)
        row = _approved_plan_from_meta(
            meta,
            meta_path,
            plan_path,
            timestamp,
            display_roots=display_roots,
        )
        if tiers and row.tier not in tiers:
            continue
        key = path_key(plan_path)
        previous = by_plan_key.get(key)
        if previous is None or timestamp > previous[0]:
            by_plan_key[key] = (timestamp, row)
        if len(by_plan_key) >= target:
            break

    rows = [
        row
        for _, row in sorted(
            by_plan_key.values(), key=lambda item: item[0], reverse=True
        )
    ]
    return tuple(rows[:target])


def _approved_plan_from_meta(
    meta: dict[str, Any],
    meta_path: Path,
    plan_path: str,
    timestamp: datetime,
    *,
    display_roots: _DisplayPathRoots,
) -> _ApprovedPlan:
    timestamp_text = timestamp.isoformat()
    return _ApprovedPlan(
        _plan_key=path_key(plan_path),
        timestamp=timestamp_text,
        age=format_relative_time(timestamp_text),
        action=_first_str(meta.get("plan_action")) or "approve",
        agent=_first_str(meta.get("name"), meta.get("agent_name"), meta.get("cl_name"))
        or "-",
        project=_first_str(meta.get("project"), meta.get("project_name"))
        or _project_from_meta_path(meta_path),
        provider_model=_provider_model_label(
            _first_str(meta.get("llm_provider"), meta.get("provider")),
            _first_str(meta.get("model")),
        ),
        plan_path=_display_path(plan_path, display_roots=display_roots),
        tier=_tier_for_path(plan_path),
        meta_path=_display_path(str(meta_path), display_roots=display_roots),
    )


def _collect_rejected_plans(
    archived_paths: tuple[Path, ...],
    *,
    represented_paths: set[str],
    limit: int,
    display_roots: _DisplayPathRoots,
    tiers: set[str],
) -> tuple[_RejectedPlan, ...]:
    rows: list[tuple[datetime, _RejectedPlan]] = []
    for path in archived_paths:
        if path_key(path) in represented_paths:
            continue
        timestamp = _file_mtime(path)
        timestamp_text = timestamp.isoformat()
        tier = _tier_for_path(str(path))
        if tiers and tier not in tiers:
            continue
        rows.append(
            (
                timestamp,
                _RejectedPlan(
                    timestamp=timestamp_text,
                    age=format_relative_time(timestamp_text),
                    plan_path=_display_path(str(path), display_roots=display_roots),
                    tier=tier,
                ),
            )
        )
    sorted_rows = sorted(rows, key=lambda item: item[0], reverse=True)
    return tuple(row for _, row in sorted_rows[: max(limit, 0)])


def _agent_meta_paths_newest_first() -> tuple[Path, ...]:
    projects_dir = sase_projects_dir()
    if not projects_dir.is_dir():
        return ()
    # `sase plan list` only displays a fixed-size recent approval summary.
    # Artifact directory names are `YYYYmmddHHMMSS`, so newest-first ordering
    # does not require statting every historical meta file. Delegate the
    # per-workflow walk to `iter_agent_artifact_dirs` so both the legacy flat
    # layout and the day-sharded layout (`<YYYYMM>/<DD>/<timestamp>`) are seen.
    candidates: list[tuple[str, str, Path]] = []
    for project_dir in projects_dir.iterdir():
        artifacts_dir = project_dir / "artifacts"
        if not artifacts_dir.is_dir():
            continue
        for workflow_dir in artifacts_dir.iterdir():
            if not workflow_dir.is_dir():
                continue
            for artifact_dir in iter_agent_artifact_dirs(
                project_dir.name,
                workflow_dir.name,
                projects_root=projects_dir,
                newest_first=True,
            ):
                timestamp = artifact_dir.name
                if len(timestamp) != 14 or not timestamp.isdigit():
                    continue
                meta_path = artifact_dir / "agent_meta.json"
                candidates.append((timestamp, str(meta_path), meta_path))
    return tuple(path for _, _, path in sorted(candidates, reverse=True))


def _display_path_roots() -> _DisplayPathRoots:
    return _DisplayPathRoots(
        sase_root=sase_home().expanduser().resolve(strict=False),
        home=Path.home().expanduser().resolve(strict=False),
    )


def _archived_plan_paths() -> tuple[Path, ...]:
    return tuple(
        path for path in iter_sharded_files("plans", pattern="*.md") if path.is_file()
    )


def _approval_timestamp(meta: dict[str, Any], meta_path: Path) -> datetime:
    for key in ("plan_approved_at", "approved_at"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            parsed = _parse_datetime(value)
            if parsed is not None:
                return parsed
    return _file_mtime(meta_path)


def _file_mtime(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, get_timezone())
    except OSError:
        return datetime.fromtimestamp(0, UTC)


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone())
    return parsed


def _project_from_action_data(action_data: dict[str, str]) -> str:
    project_dir = _first_str(action_data.get("project_dir"))
    if project_dir:
        return Path(project_dir).name or project_dir
    project_file = _first_str(action_data.get("agent_project_file"))
    if project_file:
        return Path(project_file).stem or project_file
    return "-"


def _project_from_meta_path(meta_path: Path) -> str:
    projects_dir = sase_projects_dir()
    try:
        return meta_path.relative_to(projects_dir).parts[0]
    except (ValueError, IndexError):
        return "-"


def _provider_model_label(provider: str | None, model: str | None) -> str:
    if provider and model:
        return f"{provider}/{model}"
    if model:
        return model
    if provider:
        return provider
    return "-"


def _display_path(
    path: str | None,
    *,
    display_roots: _DisplayPathRoots | None = None,
) -> str:
    if not path:
        return "-"
    roots = display_roots or _display_path_roots()
    candidate = Path(path).expanduser()
    resolved = candidate.resolve(strict=False)
    try:
        return f"~/.sase/{resolved.relative_to(roots.sase_root)}"
    except ValueError:
        pass

    try:
        relative = resolved.relative_to(roots.home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative}"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _tier_for_path(path: str | None) -> str:
    if not path:
        return "-"
    from sase.sdd.plan_tiers import existing_plan_path, read_plan_tier

    candidate = Path(path).expanduser()
    resolved = existing_plan_path(candidate)
    tier = read_plan_tier(resolved) if resolved is not None else None
    return tier or "-"


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _public_row_dict(row: Any) -> dict[str, object]:
    return {key: value for key, value in asdict(row).items() if not key.startswith("_")}


def _summary_cell(label: str, value: int, style: str) -> Any:
    from rich.text import Text

    text = Text()
    text.append(str(value), style=f"bold {style}")
    text.append(f"\n{label}", style="dim")
    return text


def _section_panel(
    title: str, table: Any | None, *, empty: str, border_style: str
) -> Any:
    from rich import box
    from rich.panel import Panel
    from rich.text import Text

    content = table if table is not None else Text(empty, style="dim")
    return Panel(content, title=title, border_style=border_style, box=box.ROUNDED)


def _proposed_table(rows: tuple[_ProposedPlan, ...]) -> Any | None:
    if not rows:
        return None
    table = _base_table()
    table.add_column("ID", no_wrap=True, style="yellow")
    table.add_column("Age", no_wrap=True)
    table.add_column("Agent/Project")
    table.add_column("Model")
    table.add_column("Tier", no_wrap=True)
    table.add_column("Plan path", ratio=2, overflow="fold")
    for row in rows:
        table.add_row(
            row.id_prefix,
            row.age,
            _agent_project(row.agent, row.project),
            row.provider_model,
            _tier_text(row.tier),
            row.plan_path,
        )
    return table


def _approved_table(rows: tuple[_ApprovedPlan, ...]) -> Any | None:
    if not rows:
        return None
    table = _base_table()
    table.add_column("Approved", no_wrap=True)
    table.add_column("Action", no_wrap=True, style="green")
    table.add_column("Agent/Project")
    table.add_column("Tier", no_wrap=True)
    table.add_column("Plan path", ratio=2, overflow="fold")
    for row in rows:
        table.add_row(
            row.age,
            row.action,
            _agent_project(row.agent, row.project),
            _tier_text(row.tier),
            row.plan_path,
        )
    return table


def _rejected_table(rows: tuple[_RejectedPlan, ...]) -> Any | None:
    if not rows:
        return None
    table = _base_table()
    table.add_column("Archived", no_wrap=True)
    table.add_column("Tier", no_wrap=True)
    table.add_column("Plan path", ratio=2, overflow="fold")
    table.add_column("Note", ratio=1)
    for row in rows:
        table.add_row(row.age, _tier_text(row.tier), row.plan_path, row.note)
    return table


def _base_table() -> Any:
    from rich import box
    from rich.table import Table

    return Table(box=box.SIMPLE, expand=True, show_edge=False)


def _agent_project(agent: str, project: str) -> str:
    if agent == "-" and project == "-":
        return "-"
    if agent == "-":
        return project
    if project == "-":
        return agent
    return f"{agent} / {project}"


def _tier_style(tier: str) -> str:
    return "green" if tier == "tale" else "magenta" if tier == "epic" else "dim"


def _tier_text(tier: str) -> Any:
    from rich.text import Text

    return Text(tier, style=_tier_style(tier))


def _tier_counts(inventory: _PlanInventory) -> dict[str, int]:
    return {
        tier: (
            sum(row.tier == tier for row in inventory.proposed)
            + sum(row.tier == tier for row in inventory.approved)
            + sum(row.tier == tier for row in inventory.rejected)
        )
        for tier in ("tale", "epic")
    }
