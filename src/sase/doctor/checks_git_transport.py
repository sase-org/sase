"""Git transport degradation checks for ``sase doctor``."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.logs.tui_telemetry import ENV_GIT_OPS_PATH, tui_git_ops_jsonl_path

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_RECENT_SAMPLE_LIMIT = 20
_WARN_RATIO = 0.85
_WARN_MIN_SAMPLES = 3
_WARN_MIN_HIGH_SAMPLES = 2
_WARN_HIGH_SHARE = 0.4


def check_git_transport_margin(context: DoctorContext) -> DiagnosticCheck:
    """Warn when recent local git telemetry is riding the configured ceiling."""
    path = _git_ops_path(context)
    samples = _recent_network_samples(path)
    if len(samples) < _WARN_MIN_SAMPLES:
        return DiagnosticCheck(
            id="vcs.git_transport_margin",
            group="vcs",
            status="OK",
            title="Git transport margin",
            summary=f"{len(samples)} recent network git sample(s); no trend warning",
            data={"path": str(path), "sample_count": len(samples)},
        )

    high_samples = [
        sample
        for sample in samples
        if sample.ratio is not None and sample.ratio >= _WARN_RATIO
    ]
    high_share = len(high_samples) / len(samples)
    should_warn = (
        len(high_samples) >= _WARN_MIN_HIGH_SAMPLES and high_share >= _WARN_HIGH_SHARE
    )
    status: CheckStatus = "WARN" if should_warn else "OK"
    slow_by_store = _slow_store_details(high_samples) if should_warn else ()
    return DiagnosticCheck(
        id="vcs.git_transport_margin",
        group="vcs",
        status=status,
        title="Git transport margin",
        summary=(
            f"{len(high_samples)}/{len(samples)} recent network git sample(s) "
            f"used at least {_WARN_RATIO:.0%} of their configured limit"
        ),
        details=slow_by_store,
        next_steps=(
            "Inspect the recent TUI git operations log for repeated cold clones or "
            "transport degradation.",
        )
        if status == "WARN"
        else (),
        data={
            "path": str(path),
            "sample_count": len(samples),
            "high_sample_count": len(high_samples),
            "high_sample_share": round(high_share, 3),
            "warning_ratio": _WARN_RATIO,
        },
    )


class _GitSample:
    def __init__(
        self,
        *,
        operation: str,
        store: str,
        duration_ms: float,
        timeout_seconds: float | None,
        ratio: float | None,
        reference_repo_used: bool | None,
    ) -> None:
        self.operation = operation
        self.store = store
        self.duration_ms = duration_ms
        self.timeout_seconds = timeout_seconds
        self.ratio = ratio
        self.reference_repo_used = reference_repo_used


def _git_ops_path(context: DoctorContext) -> Path:
    configured = context.env.get(ENV_GIT_OPS_PATH)
    return Path(configured) if configured else tui_git_ops_jsonl_path()


def _recent_network_samples(path: Path) -> list[_GitSample]:
    if not path.exists():
        return []
    samples: list[_GitSample] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        record = _json_record(line)
        if record is None or not _is_network_git_record(record):
            continue
        sample = _sample_from_record(record)
        if sample is not None:
            samples.append(sample)
    return samples[-_RECENT_SAMPLE_LIMIT:]


def _json_record(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _is_network_git_record(record: dict[str, Any]) -> bool:
    if record.get("event") != "sdd_git_operation":
        return False
    operation = str(record.get("operation") or "")
    if operation in {"sdd.clone.remote", "sdd.clone.primary"}:
        return True
    cmd = record.get("cmd")
    if not isinstance(cmd, list):
        return False
    return any(str(part) in {"clone", "fetch", "push"} for part in cmd)


def _sample_from_record(record: dict[str, Any]) -> _GitSample | None:
    duration_ms = _float_value(record.get("duration_ms"))
    if duration_ms is None:
        return None
    timeout_seconds = _float_value(record.get("timeout_seconds"))
    ratio = _float_value(record.get("duration_limit_ratio"))
    if ratio is None and timeout_seconds and timeout_seconds > 0:
        ratio = duration_ms / (timeout_seconds * 1000.0)
    return _GitSample(
        operation=str(record.get("operation") or "git"),
        store=_store_label(record),
        duration_ms=duration_ms,
        timeout_seconds=timeout_seconds,
        ratio=ratio,
        reference_repo_used=_optional_bool(record.get("reference_repo_used")),
    )


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _store_label(record: dict[str, Any]) -> str:
    name = record.get("sdd_store_name")
    if isinstance(name, str) and name:
        return name
    path = record.get("sdd_store_path")
    if isinstance(path, str) and path:
        return Path(path).name
    cwd = record.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd).name
    return "unknown"


def _slow_store_details(samples: list[_GitSample]) -> tuple[str, ...]:
    counts = Counter(sample.store for sample in samples)
    details: list[str] = []
    for store, _count in counts.most_common(5):
        store_samples = [sample for sample in samples if sample.store == store]
        durations = ", ".join(
            _format_seconds(sample.duration_ms / 1000.0) for sample in store_samples[:5]
        )
        max_ratio = max(sample.ratio or 0.0 for sample in store_samples)
        references = Counter(sample.reference_repo_used for sample in store_samples)
        reference_summary = _reference_summary(references)
        details.append(
            f"{store}: {len(store_samples)} near-ceiling sample(s), max "
            f"{max_ratio:.0%} of limit, durations {durations}{reference_summary}"
        )
    return tuple(details)


def _format_seconds(value: float) -> str:
    return f"{value:.1f}s"


def _reference_summary(counts: Counter[bool | None]) -> str:
    true_count = counts.get(True, 0)
    false_count = counts.get(False, 0)
    if not true_count and not false_count:
        return ""
    parts: list[str] = []
    if false_count:
        parts.append(f"{false_count} without reference")
    if true_count:
        parts.append(f"{true_count} with reference")
    return f" ({', '.join(parts)})"


__all__ = [
    "check_git_transport_margin",
]
