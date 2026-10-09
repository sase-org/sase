"""Historical failure enumeration for ``auto-restart scan``.

Two sources, both read-only:

- failed ``done.json`` rows under ``<projects>/<project>/artifacts/``,
  across every workflow layout (current day-sharded trees and legacy
  flat ones), located by filename instead of layout assumptions;
- dismissed bundles under ``dismissed_bundles/`` (month-sharded and
  legacy top-level), which survive the artifact-directory wipe that
  follows a dismiss or a manual ``,x``.

A dismissed bundle and a ``done.json`` row can describe the same
failure; they are deduplicated on the artifact directory, with the live
row winning. Monitor and tool rows (``sase tool run check`` failures
and friends) are skipped: tool, test, and monitor failures are never
restart candidates.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Mapping

from sase.agent.auto_restart.inputs import (
    find_runner_log,
    read_json_dict,
    read_log_tail,
)
from sase.core.time import get_timezone

#: Dismissed-bundle filename timestamp: leading 14-digit ``YYYYmmddHHMMSS``.
_BUNDLE_STAMP_LENGTH = 14


@dataclass(frozen=True)
class FailedCandidate:
    """One historical failure from either scan source."""

    source: str
    name: str
    project: str
    died_at: float | None
    artifacts_dir: Path | None
    done: Mapping[str, Any] | None
    meta: Mapping[str, Any] | None
    bundle: Mapping[str, Any] | None
    log_path: Path | None
    #: Source-marker mtime (``done.json`` or bundle file): the W2 window
    #: end for rows without a recorded finish time, and the dismissal
    #: bound for bundles whose artifact directory is already wiped.
    mtime: float | None = None


def _parse_local_stamp(text: str) -> float | None:
    """Parse artifact/bundle timestamps into epoch seconds.

    Accepts 14-digit ``YYYYmmddHHMMSS`` directory names, 12-digit
    ``YYmmdd_HHMMSS`` legacy stamps, and bare epoch numbers. Naive
    values are local-time constructions.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.replace(".", "", 1).isdigit() and (
        "." in stripped or len(stripped) not in (12, 14)
    ):
        try:
            return float(stripped)
        except ValueError:
            return None
    digits = "".join(ch for ch in stripped if ch.isdigit())
    local = get_timezone()
    for length, fmt in ((14, "%Y%m%d%H%M%S"), (12, "%y%m%d%H%M%S")):
        if len(digits) == length:
            try:
                parsed = datetime.datetime.strptime(digits, fmt)
            except ValueError:
                return None
            return parsed.replace(tzinfo=local).timestamp()
    return None


def _done_died_at(
    done: Mapping[str, Any], artifacts_dir: Path, fallback_mtime: float | None
) -> float | None:
    finished = done.get("finished_at")
    if isinstance(finished, bool):
        pass
    elif isinstance(finished, (int, float)):
        return float(finished)
    stamp = _parse_local_stamp(artifacts_dir.name)
    if stamp is not None:
        return stamp
    return fallback_mtime


def project_for_done(done: Mapping[str, Any], artifacts_dir: Path) -> str:
    cl_name = done.get("cl_name")
    if isinstance(cl_name, str) and cl_name:
        return cl_name
    try:
        return artifacts_dir.parents[2].name
    except IndexError:
        return artifacts_dir.parent.name


def _iter_done_candidates(
    projects_root: Path, workflows_root: Path
) -> list[FailedCandidate]:
    """Collect failed ``done.json`` rows under every project's artifacts."""
    candidates: list[FailedCandidate] = []
    try:
        project_dirs = sorted(path for path in projects_root.iterdir() if path.is_dir())
    except OSError:
        return []
    for project_dir in project_dirs:
        artifacts_root = project_dir / "artifacts"
        if not artifacts_root.is_dir():
            continue
        try:
            walker = artifacts_root.walk()
        except OSError:
            continue
        for current, _dirs, files in walker:
            if "done.json" not in files:
                continue
            artifacts_dir = current
            done_path = artifacts_dir / "done.json"
            try:
                mtime: float | None = done_path.stat().st_mtime
            except OSError:
                mtime = None
            done = read_json_dict(done_path)
            if done is None or done.get("outcome") != "failed":
                continue
            meta = read_json_dict(artifacts_dir / "agent_meta.json") or {}
            output_path = done.get("output_path")
            log_path = find_runner_log(
                artifacts_dir.name,
                output_path if isinstance(output_path, str) else None,
                workflows_root,
            )
            name = done.get("name")
            if not isinstance(name, str) or not name:
                meta_name = meta.get("name")
                name = (
                    meta_name
                    if isinstance(meta_name, str) and meta_name
                    else artifacts_dir.name
                )
            candidates.append(
                FailedCandidate(
                    source="done",
                    name=name,
                    project=project_for_done(done, artifacts_dir),
                    died_at=_done_died_at(done, artifacts_dir, mtime),
                    artifacts_dir=artifacts_dir,
                    done=done,
                    meta=meta,
                    bundle=None,
                    log_path=log_path,
                    mtime=mtime,
                )
            )
    return candidates


def _looks_like_monitor_row(bundle: Mapping[str, Any]) -> bool:
    """Return whether a dismissed bundle is a monitor/tool row."""
    if bundle.get("agent_session_role") == "monitor":
        return True
    name = bundle.get("agent_name")
    if isinstance(name, str) and "--mon" in name:
        return True
    return False


def _iter_bundle_candidates(
    bundles_root: Path, workflows_root: Path
) -> list[FailedCandidate]:
    """Collect failed dismissed bundles that are not monitor rows."""
    candidates: list[FailedCandidate] = []
    try:
        paths = sorted(bundles_root.rglob("*.json"))
    except OSError:
        return []
    for path in paths:
        if not path.is_file():
            continue
        try:
            bundle_mtime: float | None = path.stat().st_mtime
        except OSError:
            bundle_mtime = None
        bundle = read_json_dict(path)
        if bundle is None:
            continue
        if bundle.get("status") != "FAILED" and not bundle.get("error_message"):
            continue
        if _looks_like_monitor_row(bundle):
            continue
        artifacts_dirname = bundle.get("artifacts_dir")
        artifacts_dir = (
            Path(str(artifacts_dirname))
            if isinstance(artifacts_dirname, str) and artifacts_dirname
            else None
        )
        stamp = _parse_local_stamp(path.stem[:_BUNDLE_STAMP_LENGTH])
        if stamp is None and artifacts_dir is not None:
            stamp = _parse_local_stamp(artifacts_dir.name)
        output_path = bundle.get("output_path")
        log_path = find_runner_log(
            artifacts_dir.name if artifacts_dir is not None else None,
            output_path if isinstance(output_path, str) else None,
            workflows_root,
        )
        name = bundle.get("agent_name")
        project = bundle.get("cl_name")
        candidates.append(
            FailedCandidate(
                source="bundle",
                name=name if isinstance(name, str) and name else path.stem,
                project=(
                    project if isinstance(project, str) and project else "unknown"
                ),
                died_at=stamp,
                artifacts_dir=artifacts_dir,
                done=None,
                meta=None,
                bundle=bundle,
                log_path=log_path,
                mtime=bundle_mtime,
            )
        )
    return candidates


def collect_failed_candidates(
    *,
    projects_root: Path | None = None,
    bundles_root: Path | None = None,
    workflows_root: Path | None = None,
    since_seconds: float | None = None,
    now: float | None = None,
) -> list[FailedCandidate]:
    """Collect historical failures from both sources, deduplicated.

    ``since_seconds`` keeps rows whose death is within that age (rows
    with an unknown time are always kept); ``now`` is injectable for
    tests. Live ``done.json`` rows win over dismissed bundles that name
    the same artifact directory. Results sort newest-first with
    unknown-time rows last.
    """
    from sase.core.paths import sase_projects_dir, sase_subdir

    if projects_root is None:
        projects_root = sase_projects_dir()
    if bundles_root is None:
        bundles_root = sase_subdir("dismissed_bundles")
    if workflows_root is None:
        workflows_root = sase_subdir("workflows")
    candidates = _iter_done_candidates(projects_root, workflows_root)
    owned_dirs = {
        str(candidate.artifacts_dir)
        for candidate in candidates
        if candidate.artifacts_dir is not None
    }
    for bundle_candidate in _iter_bundle_candidates(bundles_root, workflows_root):
        key = (
            str(bundle_candidate.artifacts_dir)
            if bundle_candidate.artifacts_dir is not None
            else f"bundle:{bundle_candidate.name}"
        )
        if key in owned_dirs:
            continue
        owned_dirs.add(key)
        candidates.append(bundle_candidate)
    if since_seconds is not None:
        current = (
            now if now is not None else datetime.datetime.now(datetime.UTC).timestamp()
        )
        cutoff = current - since_seconds
        candidates = [
            candidate
            for candidate in candidates
            if candidate.died_at is None or candidate.died_at >= cutoff
        ]
    candidates.sort(
        key=lambda candidate: (
            candidate.died_at is None,
            -(candidate.died_at or 0.0),
        )
    )
    return candidates


def candidate_log_tail(candidate: FailedCandidate) -> str:
    """Read the candidate's runner log tail (empty when unknown)."""
    return read_log_tail(candidate.log_path)


__all__ = [
    "FailedCandidate",
    "candidate_log_tail",
    "collect_failed_candidates",
]
