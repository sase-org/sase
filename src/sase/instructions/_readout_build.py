"""Aggregate classified runs into the ``sase instructions readout`` payload."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.instructions._readout_classify import classify_artifact_dir
from sase.instructions._readout_shared import (
    ACCEPTED,
    CLASSES,
    EXPLICIT,
    LEGACY,
    MISS,
    MONITOR_PLAIN,
    MONITOR_PREPARED,
    NONE,
    NOT_REQUIRED,
    OTHER_HANDOFF,
    PLAN_HANDOFF,
    READOUT_SCHEMA_VERSION,
    UNKNOWN,
    read_json,
)

_PROVIDER_ORDER = ("claude", "codex", "grok", "muse", "agy")


@dataclass(frozen=True)
class _ClassifiedRun:
    """One finished root run with its delivery mode and class."""

    provider: str
    name: str
    artifact_dir: str
    started_at: datetime
    delivery_mode: str
    run_class: str
    is_research: bool
    rendered_at: str | None = None


@dataclass
class _ReadoutRow:
    """Aggregated counts for one provider × mode × research slice."""

    provider: str
    delivery_mode: str
    is_research: bool
    total: int = 0
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0))
    memory_reads_total: int = 0
    runs_with_reads: int = 0

    @property
    def misses(self) -> int:
        return self.counts.get(MISS, 0)

    @property
    def miss_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.misses / self.total

    @property
    def misses_label(self) -> str:
        if self.total == 0:
            return "≤0/0 (0%)"
        pct = 100.0 * self.misses / self.total
        return f"≤{self.misses}/{self.total} ({pct:.0f}%)"

    @property
    def memory_mean(self) -> float:
        if self.total == 0:
            return 0.0
        return self.memory_reads_total / self.total

    @property
    def memory_share(self) -> float:
        if self.total == 0:
            return 0.0
        return self.runs_with_reads / self.total


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _is_research_run(name: str, meta: dict[str, Any]) -> bool:
    """Return True for research runs, which get their own readout rows."""
    if name.startswith("research."):
        return True
    clan = meta.get("agent_clan")
    return isinstance(clan, str) and clan.startswith("research.")


def _is_excluded_run(meta: dict[str, Any]) -> bool:
    """Return True for monitor and gate turns, which never enter the readout."""
    role = meta.get("agent_session_role")
    if role in ("monitor", "gate"):
        return True
    kind = meta.get("turn_kind")
    if kind in ("monitor", "gate"):
        return True
    suffix = meta.get("role_suffix")
    if isinstance(suffix, str):
        normalized = suffix.strip().lower()
        if normalized.startswith(("--mon", "--gate", "--monitor")):
            return True
        if normalized in ("-mon", "-gate", "mon", "gate"):
            return True
    name = meta.get("name")
    if isinstance(name, str) and ("--mon" in name or "--gate" in name):
        return True
    return False


def _delivery_mode_for_dir(artifact_dir: Path) -> tuple[str, str | None]:
    """Return ``(mode, rendered_at)`` for one artifact dir's root manifest."""
    from sase.instructions.manifests import read_run_manifests

    try:
        entries = read_run_manifests(artifact_dir)
    except Exception:
        return NONE, None
    roots = [entry for entry in entries if not entry.is_helper]
    if not roots:
        return NONE, None
    ordinary = [
        entry
        for entry in roots
        if isinstance(entry.manifest, dict)
        and isinstance(entry.manifest.get("facts"), dict)
        and entry.manifest["facts"].get("purpose") == "ordinary"
    ]
    candidates = ordinary or roots
    rendered: str | None = None
    for entry in candidates:
        manifest = entry.manifest if isinstance(entry.manifest, dict) else entry.raw
        if not isinstance(manifest, dict):
            continue
        delivery = manifest.get("delivery")
        if not isinstance(delivery, dict):
            continue
        status = delivery.get("status")
        stamped = delivery.get("rendered_at")
        if status == EXPLICIT:
            if isinstance(stamped, str) and stamped:
                if rendered is None or stamped < rendered:
                    rendered = stamped
            else:
                rendered = rendered or None
            return EXPLICIT, rendered
    for entry in candidates:
        manifest = entry.manifest if isinstance(entry.manifest, dict) else entry.raw
        if not isinstance(manifest, dict):
            continue
        delivery = manifest.get("delivery")
        if not isinstance(delivery, dict):
            continue
        if delivery.get("status") in ("inherits_native", "shadow"):
            return LEGACY, None
    if any(
        isinstance(
            entry.manifest if isinstance(entry.manifest, dict) else entry.raw,
            dict,
        )
        for entry in candidates
    ):
        return LEGACY, None
    return NONE, None


def _memory_events_by_run(classified: list[_ClassifiedRun]) -> dict[str, int]:
    """Return ``{artifact_dir: read count}`` joined by identity and time."""
    from sase.core.paths import sase_projects_dir

    by_dir: dict[str, list[_ClassifiedRun]] = {}
    for run in classified:
        by_dir.setdefault(run.artifact_dir, []).append(run)
    counts = dict.fromkeys(by_dir, 0)
    if not by_dir:
        return counts
    try:
        projects_root = sase_projects_dir()
    except Exception:
        return counts
    try:
        log_paths = sorted(projects_root.glob("*/memory_reads.jsonl"))
    except OSError:
        return counts
    wanted_dirs = set(by_dir)
    by_name: dict[str, list[_ClassifiedRun]] = {}
    for run in classified:
        by_name.setdefault(run.name, []).append(run)
    for log_path in log_paths:
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            artifacts_dir = event.get("artifacts_dir")
            if isinstance(artifacts_dir, str) and artifacts_dir in wanted_dirs:
                counts[artifacts_dir] += 1
                continue
            agent_name = event.get("agent_name")
            if not isinstance(agent_name, str) or agent_name not in by_name:
                continue
            stamped = _parse_time(event.get("timestamp"))
            if stamped is None:
                continue
            for run in by_name[agent_name]:
                try:
                    if (
                        run.started_at <= stamped
                        and stamped <= run.started_at + timedelta(hours=48)
                    ):
                        counts[run.artifact_dir] += 1
                        break
                except (TypeError, ValueError):
                    continue
    return counts


def build_readout(
    scored_runs: list[Any],
    *,
    since: datetime | None,
    until: datetime | None,
    providers: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Aggregate classified runs into the stable ``schema_version: 1`` payload."""
    now = datetime.now(tz=UTC)
    wanted = {p.lower() for p in providers if p}
    classified: list[_ClassifiedRun] = []
    first_explicit: dict[str, str] = {}
    for run in scored_runs:
        provider = str(getattr(run, "provider", "") or "").lower()
        if wanted and provider not in wanted:
            continue
        artifact_dir = Path(str(getattr(run, "artifact_dir", "")))
        name = str(getattr(run, "name", "") or "")
        started_at = getattr(run, "started_at", None)
        if not isinstance(started_at, datetime):
            continue
        if since is not None and started_at < since:
            continue
        if until is not None and started_at > until:
            continue
        meta = read_json(artifact_dir / "agent_meta.json")
        if _is_excluded_run(meta):
            continue
        if "--mon" in name or "--gate" in name:
            continue
        research = _is_research_run(name, meta)
        done_path = artifact_dir / "done.json"
        if not done_path.is_file():
            if meta.get("lifecycle_phase") == "waiting":
                continue
            if not meta.get("run_started_at"):
                continue
            try:
                age_hours = (now - started_at).total_seconds() / 3600.0
            except (TypeError, ValueError):
                age_hours = 99.0
            if age_hours < 2.0:
                continue
            mode, rendered = _delivery_mode_for_dir(artifact_dir)
            provisional = classify_artifact_dir(artifact_dir, meta)
            run_class = provisional if provisional != MISS else UNKNOWN
            classified.append(
                _ClassifiedRun(
                    provider=provider,
                    name=name,
                    artifact_dir=str(artifact_dir),
                    started_at=started_at,
                    delivery_mode=mode,
                    run_class=run_class,
                    is_research=research,
                    rendered_at=rendered,
                )
            )
            continue
        mode, rendered = _delivery_mode_for_dir(artifact_dir)
        run_class = classify_artifact_dir(artifact_dir, meta)
        if mode == EXPLICIT and rendered:
            prior = first_explicit.get(provider)
            if prior is None or rendered < prior:
                first_explicit[provider] = rendered
        classified.append(
            _ClassifiedRun(
                provider=provider,
                name=name,
                artifact_dir=str(artifact_dir),
                started_at=started_at,
                delivery_mode=mode,
                run_class=run_class,
                is_research=research,
                rendered_at=rendered,
            )
        )
    for run in classified:
        if run.delivery_mode != EXPLICIT or not run.rendered_at:
            continue
        prior = first_explicit.get(run.provider)
        if prior is None or run.rendered_at < prior:
            first_explicit[run.provider] = run.rendered_at
    read_counts = _memory_events_by_run(classified)
    rows: dict[tuple[str, str, bool], _ReadoutRow] = {}
    for run in classified:
        key = (run.provider, run.delivery_mode, run.is_research)
        row = rows.get(key)
        if row is None:
            row = _ReadoutRow(
                provider=run.provider,
                delivery_mode=run.delivery_mode,
                is_research=run.is_research,
            )
            rows[key] = row
        row.total += 1
        row.counts[run.run_class] = row.counts.get(run.run_class, 0) + 1
        got = read_counts.get(run.artifact_dir, 0)
        row.memory_reads_total += got
        if got >= 1:
            row.runs_with_reads += 1
    ordered = sorted(
        rows.values(),
        key=lambda r: (
            _PROVIDER_ORDER.index(r.provider) if r.provider in _PROVIDER_ORDER else 99,
            r.provider,
            r.delivery_mode,
            r.is_research,
        ),
    )
    payload_rows: list[dict[str, Any]] = []
    for row in ordered:
        payload_rows.append(
            {
                "provider": row.provider,
                "delivery_mode": row.delivery_mode,
                "is_research": row.is_research,
                "total": row.total,
                "accepted": row.counts.get(ACCEPTED, 0),
                "plan_handoff": row.counts.get(PLAN_HANDOFF, 0),
                "monitor_prepared": row.counts.get(MONITOR_PREPARED, 0),
                "monitor_plain": row.counts.get(MONITOR_PLAIN, 0),
                "other_handoff": row.counts.get(OTHER_HANDOFF, 0),
                "not_required": row.counts.get(NOT_REQUIRED, 0),
                "miss": row.counts.get(MISS, 0),
                "unknown": row.counts.get(UNKNOWN, 0),
                "misses": row.misses_label,
                "miss_rate": round(row.miss_rate, 4),
                "memory_mean": round(row.memory_mean, 2),
                "memory_share": round(row.memory_share, 4),
            }
        )
    return {
        "schema_version": READOUT_SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "filters": {
            "since": since.isoformat() if since is not None else None,
            "until": until.isoformat() if until is not None else None,
            "providers": sorted(wanted),
        },
        "first_explicit_rendered_at": dict(sorted(first_explicit.items())),
        "rows": payload_rows,
    }


def render_readout_table(
    payload: dict[str, Any], *, console: Any | None = None
) -> None:
    """Render one row per provider × mode with class counts and memory."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    table = Table(
        "provider",
        "mode",
        "research",
        "total",
        "accepted",
        "plan",
        "mon-prep",
        "mon",
        "other",
        "not-req",
        "miss",
        "unk",
        "mem-mean",
        "mem-≥1",
        title=None,
    )
    rows = payload.get("rows")
    if not isinstance(rows, list):
        rows = []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        table.add_row(
            str(entry.get("provider", "")),
            str(entry.get("delivery_mode", "")),
            "R" if entry.get("is_research") else "—",
            str(entry.get("total", 0)),
            str(entry.get("accepted", 0)),
            str(entry.get("plan_handoff", 0)),
            str(entry.get("monitor_prepared", 0)),
            str(entry.get("monitor_plain", 0)),
            str(entry.get("other_handoff", 0)),
            str(entry.get("not_required", 0)),
            str(entry.get("misses", "")),
            str(entry.get("unknown", 0)),
            f"{float(entry.get('memory_mean', 0.0)):.2f}",
            f"{100.0 * float(entry.get('memory_share', 0.0)):.0f}%",
        )
    first = payload.get("first_explicit_rendered_at")
    subtitle = ""
    if isinstance(first, dict) and first:
        subtitle = "first explicit: " + ", ".join(
            f"{provider}={stamped}" for provider, stamped in sorted(first.items())
        )
    else:
        subtitle = "no explicit manifests in window"
    target = console if console is not None else Console()
    target.print(Panel(table, title="Instruction readout", subtitle=subtitle))


__all__ = ["build_readout", "render_readout_table"]
