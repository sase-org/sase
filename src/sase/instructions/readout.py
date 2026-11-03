"""Handoff-aware declaration readout for ``sase instructions readout``.

Per provider and delivery mode, finished root runs are classified as
accepted, plan handoff, monitor handoff (prepared or plain), other
recognized handoff, declaration not required, miss, or unknown. Memory
reads are joined per run. The JSON document carries ``schema_version: 1``.

Python gathers staged records/receipts, host lifecycle facts, declaration
evidence, prepared-intent evidence, and bounded legacy tail strings. Class
precedence belongs to the Rust core through
``sase.core.instruction_readout``; this module never reimplements it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.core.instruction_readout import classify_instruction_readout

READOUT_SCHEMA_VERSION = 1
TAIL_SCAN_BYTES = 262144

ACCEPTED = "accepted"
PLAN_HANDOFF = "plan_handoff"
MONITOR_PREPARED = "monitor_prepared"
MONITOR_PLAIN = "monitor_plain"
OTHER_HANDOFF = "other_handoff"
NOT_REQUIRED = "not_required"
MISS = "miss"
UNKNOWN = "unknown"

CLASSES = (
    ACCEPTED,
    PLAN_HANDOFF,
    MONITOR_PREPARED,
    MONITOR_PLAIN,
    OTHER_HANDOFF,
    NOT_REQUIRED,
    MISS,
    UNKNOWN,
)

EXPLICIT = "explicit"
LEGACY = "legacy"
NONE = "none"

MODES = (EXPLICIT, LEGACY, NONE)

_PROVIDER_ORDER = ("claude", "codex", "grok", "muse", "agy")

# Only ``propose`` stages a handoff: ``validate`` and ``decide`` never leave
# the turn, so a mere plan validation must not establish a handoff.
_PLAN_MARKERS = ("sase plan propose",)
_MONITOR_MARKER = "sase monitor start"
_PREPARE_MARKER = "sase final prepare"
_OTHER_MARKERS = ("sase pipe", "sase questions", "sase handoff")

_STAGED_RECORD_FILENAME = ".sase_handoff_staged.json"
_STAGED_RECEIPT_FILENAME = ".sase_handoff_adopted.json"


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


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


def _tail_text(path: Path, *, max_bytes: int = TAIL_SCAN_BYTES) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as stream:
            if size > max_bytes:
                stream.seek(size - max_bytes)
            raw = stream.read()
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _has_accepted_submission(artifact_dir: Path) -> bool:
    payload = _read_json(artifact_dir / "final_submission.json")
    return bool(payload)


def _is_not_required(artifact_dir: Path) -> bool:
    payload = _read_json(artifact_dir / "final_context.json")
    if not payload:
        return False
    if payload.get("submission_required") is False:
        return True
    selected = payload.get("selected_instances")
    if isinstance(selected, list) and selected:
        flags = [
            item.get("submission_required")
            for item in selected
            if isinstance(item, dict)
        ]
        if flags and all(flag is False for flag in flags):
            return True
    context = payload.get("context")
    if isinstance(context, dict):
        reqs = context.get("requirements")
        if isinstance(reqs, list) and reqs:
            flags = [
                item.get("submission_required")
                for item in reqs
                if isinstance(item, dict)
            ]
            if flags and all(flag is False for flag in flags):
                return True
    return False


def _find_real_marker(tail: str, marker: str) -> int:
    """Return the index of a real *marker* invocation (not ``-h``), or -1."""
    idx = tail.find(marker)
    while idx != -1:
        following = tail[idx + len(marker) : idx + len(marker) + 16]
        if following.startswith(" -h") or following.startswith(" --help"):
            idx = tail.find(marker, idx + 1)
            continue
        return idx
    return -1


def _has_real_prepare(tail: str) -> int:
    """Return the index of a real ``sase final prepare`` (not ``-h``), or -1."""
    return _find_real_marker(tail, _PREPARE_MARKER)


def _has_handoff_phase(meta: dict[str, Any]) -> bool:
    phases = meta.get("lifecycle_phases")
    if not isinstance(phases, list):
        return False
    return any(
        isinstance(entry, dict) and entry.get("phase") == "handoff" for entry in phases
    )


def _has_prepared_completion(artifact_dir: Path) -> bool:
    payload = _read_json(
        artifact_dir / "continuation" / "completion_intents" / "index.json"
    )
    intents = payload.get("intents")
    return isinstance(intents, dict) and bool(intents)


def _declaration_evidence(artifact_dir: Path) -> str:
    """Return the Rust declaration wire value for one artifact dir."""
    if _has_accepted_submission(artifact_dir):
        return "accepted"
    if _is_not_required(artifact_dir):
        return "not_required"
    return "missing"


def _read_staged_record(artifact_dir: Path) -> dict[str, Any] | None:
    """Return the staged-handoff record dict, or ``None`` when absent/corrupt."""
    payload = _read_json(artifact_dir / _STAGED_RECORD_FILENAME)
    return payload or None


def _read_staged_receipt(artifact_dir: Path) -> dict[str, Any] | None:
    """Return the staged adoption receipt dict, or ``None`` when absent/corrupt."""
    payload = _read_json(artifact_dir / _STAGED_RECEIPT_FILENAME)
    return payload or None


def _is_staged_evidence(
    meta: dict[str, Any],
    record: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
) -> bool:
    """Return True when durable facts show the handoff staged (not legacy).

    A staged record, an adoption receipt, or a ``staged`` handoff protocol
    marks new-protocol evidence. Historical ``killed``/unspecified evidence
    stays legacy so old runs keep their archived scoring.
    """
    if record is not None or receipt is not None:
        return True
    return meta.get("handoff_protocol") == "staged"


def _staged_prepared_ref(payload: Any) -> str | None:
    """Return the prepared-intent ref in a staged monitor payload, if any."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("prepared_intent_ref")
    if isinstance(raw, str) and raw.strip():
        return raw
    resources = payload.get("resources")
    if isinstance(resources, dict):
        nested = resources.get("prepared_intent_ref")
        if isinstance(nested, str) and nested.strip():
            return nested
    return None


def _staged_kind_wire(artifact_dir: Path, record: dict[str, Any] | None) -> str | None:
    """Map a staged record to the Rust handoff wire value, or ``None``."""
    if not record:
        return None
    kind = record.get("kind")
    if kind == "plan":
        return "plan"
    if kind == "monitor":
        # Prepared-monitor evidence uses the validated context/intent
        # contract, not merely a tool-call substring.
        if _staged_prepared_ref(record.get("payload")) and _has_prepared_completion(
            artifact_dir
        ):
            return "monitor_prepared"
        return "monitor_plain"
    if kind in ("questions", "pipe", "gate"):
        return "other"
    return None


def _host_handoff_wire(
    artifact_dir: Path,
    meta: dict[str, Any],
    tail_text: Callable[[], str],
) -> str | None:
    """Classify an adopted handoff from host records, or ``None``.

    ``None`` means there is no host-evidence handoff (no ``handoff``
    lifecycle phase). Callers skip this step when
    ``handoff_aborted.json`` exists, then fall through to the tool-call
    tail scan used for older runs.
    """
    if not _has_handoff_phase(meta):
        return None
    if (artifact_dir / "plan_path.json").is_file():
        return "plan"
    if meta.get("monitor_id") or meta.get("monitor_member_agent_name"):
        prepared = _has_prepared_completion(artifact_dir)
        if prepared or _has_real_prepare(tail_text()) != -1:
            return "monitor_prepared"
        return "monitor_plain"
    return "other"


def _legacy_tail_wire(text: str) -> str | None:
    """Classify historical runs from bounded tool-call evidence, or ``None``.

    Command mentions, help invocations, and mere plan validations never
    establish a handoff: only real staging commands count.
    """
    if any(_find_real_marker(text, marker) != -1 for marker in _PLAN_MARKERS):
        return "plan"
    monitor_at = _find_real_marker(text, _MONITOR_MARKER)
    if monitor_at != -1:
        prepare_at = _has_real_prepare(text)
        if prepare_at != -1 and prepare_at < monitor_at:
            return "monitor_prepared"
        return "monitor_plain"
    for marker in _OTHER_MARKERS:
        if _find_real_marker(text, marker) != -1:
            return "other"
    return None


def _handoff_evidence(
    artifact_dir: Path,
    meta: dict[str, Any],
    tail_text: Callable[[], str],
) -> tuple[str | None, bool, dict[str, Any] | None]:
    """Return ``(handoff_wire, is_staged, staged_record)`` for one run.

    Durable host facts win over tool-call strings: the staged record comes
    first, then adopted lifecycle facts, then the bounded legacy tail scan.
    """
    record = _read_staged_record(artifact_dir)
    receipt = _read_staged_receipt(artifact_dir)
    if _is_staged_evidence(meta, record, receipt):
        wire = _staged_kind_wire(artifact_dir, record)
        if wire is None:
            wire = _host_handoff_wire(artifact_dir, meta, tail_text)
        if wire is None:
            wire = _legacy_tail_wire(tail_text())
        return wire, True, record
    wire = _host_handoff_wire(artifact_dir, meta, tail_text)
    if wire is None:
        wire = _legacy_tail_wire(tail_text())
    return wire, False, record


def _final_context_requires_submission(artifact_dir: Path) -> bool:
    """Return True when final_context shows a required declaration."""
    payload = _read_json(artifact_dir / "final_context.json")
    if not payload:
        return False
    if payload.get("submission_required") is True:
        return True
    selected = payload.get("selected_instances")
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, dict) and item.get("submission_required") is True:
                return True
    context = payload.get("context")
    if isinstance(context, dict):
        requirements = context.get("requirements")
        if isinstance(requirements, list):
            for item in requirements:
                if isinstance(item, dict) and item.get("submission_required") is True:
                    return True
    return False


def _has_dirty_obligations(artifact_dir: Path, record: dict[str, Any] | None) -> bool:
    """Return True when staged or finalizer facts show dirty obligations."""
    if record is not None:
        dirty = record.get("dirty_obligations_at_stage")
        if isinstance(dirty, list) and any(
            isinstance(entry, str) and entry.strip() for entry in dirty
        ):
            return True
    # An absent/corrupt final context is not proof that no declaration was
    # required; only an explicit not-required context clears the obligations.
    return _final_context_requires_submission(artifact_dir)


def _classify_via_core(
    handoff: str | None, declaration: str, has_dirty_obligations: bool
) -> str:
    """Score gathered evidence with the Rust readout policy."""
    result = classify_instruction_readout(
        {
            "handoff": handoff,
            "declaration": declaration,
            "has_dirty_obligations": bool(has_dirty_obligations),
        }
    )
    if result not in CLASSES:
        raise ValueError(f"unknown readout class from Rust core: {result!r}")
    return result


def _classify_artifact_dir(
    artifact_dir: Path, meta: dict[str, Any] | None = None
) -> str:
    """Classify one artifact dir, delegating precedence to the Rust core."""
    if meta is None:
        meta = _read_json(artifact_dir / "agent_meta.json")
    declaration = _declaration_evidence(artifact_dir)
    if (artifact_dir / "handoff_aborted.json").is_file():
        # An aborted handoff is never a handoff; the declaration still counts.
        return _classify_via_core(None, declaration, False)
    tail: str | None = None

    def tail_text() -> str:
        nonlocal tail
        if tail is None:
            tail = _tail_text(artifact_dir / "tool_calls.jsonl")
        return tail

    handoff, staged, record = _handoff_evidence(artifact_dir, meta, tail_text)
    dirty = _has_dirty_obligations(artifact_dir, record) if staged else False
    return _classify_via_core(handoff, declaration, dirty)


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
        meta = _read_json(artifact_dir / "agent_meta.json")
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
            provisional = _classify_artifact_dir(artifact_dir, meta)
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
        run_class = _classify_artifact_dir(artifact_dir, meta)
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


__all__ = (
    "ACCEPTED",
    "CLASSES",
    "EXPLICIT",
    "LEGACY",
    "MISS",
    "MODES",
    "MONITOR_PLAIN",
    "MONITOR_PREPARED",
    "NONE",
    "NOT_REQUIRED",
    "OTHER_HANDOFF",
    "PLAN_HANDOFF",
    "READOUT_SCHEMA_VERSION",
    "TAIL_SCAN_BYTES",
    "UNKNOWN",
    "build_readout",
    "render_readout_table",
)
