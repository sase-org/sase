"""Read-only release history metrics built on the steward's fact readers."""

from __future__ import annotations

import json
import math
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from _release_core import (
    CoreEnsureError,
    CoreLag,
    Pinned,
    complete_files_for_version,
    ensure_core,
    parse_expected_suffixes,
)
from _release_watch_facts import ReleaseFactsReader
from _release_watch_health import ReleaseHealthReader
from _release_watch_transport import GithubTransport, ReleaseTransportError


DEFAULT_REPO = "sase-org/sase"
DEFAULT_WINDOW_DAYS = 28
GITHUB_HISTORY_TIMEOUT_SECONDS = 120.0
_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$", re.IGNORECASE)
_VERSION_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
_VERSION_RE = re.compile(r"(?<![0-9.])v?(\d+\.\d+\.\d+)(?![0-9.])")
_FIX_WORD_RE = re.compile(
    r"\b(?:fix(?:es|ed)?|repair(?:s|ed)?|correct(?:s|ed)?|regression)\b",
    re.I,
)
_DEFAULT_INVENTORY = (
    Path(__file__).resolve().parents[1] / ".github" / "release-qualification.json"
)


class MetricsError(ValueError):
    """A required history input is malformed or unreadable."""


def _instant(value: object, where: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MetricsError(f"{where} must be an RFC 3339 timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        result = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise MetricsError(f"{where} is not a valid timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise MetricsError(f"{where} must include a UTC offset")
    return result.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def load_inventory(path: Path) -> dict[str, Any]:
    """Read the versioned N1 inventory and return its blocking job mappings."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetricsError(f"cannot read N1 inventory {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise MetricsError("N1 inventory must be an object with schema_version 1")
    checks = payload.get("checks")
    if not isinstance(checks, list):
        raise MetricsError("N1 inventory checks must be a list")
    blocking: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(checks):
        if not isinstance(raw, dict):
            raise MetricsError(f"N1 inventory checks[{index}] must be an object")
        if raw.get("disposition") != "blocking":
            continue
        check_id = raw.get("id")
        workflow = raw.get("workflow")
        job = raw.get("job")
        job_name = job.get("name") if isinstance(job, dict) else None
        if (
            not isinstance(check_id, str)
            or not check_id.strip()
            or not isinstance(workflow, str)
            or not workflow.endswith(".yml")
            or not isinstance(job_name, str)
            or not job_name.strip()
        ):
            raise MetricsError(f"N1 inventory blocking check {check_id} is malformed")
        workflow = Path(workflow).name
        if check_id in seen:
            continue
        seen.add(check_id)
        item: dict[str, Any] = {
            "id": check_id.strip(),
            "workflow": workflow,
            "job_name": job_name.strip(),
        }
        if workflow == "release.yml":
            required_legs = raw.get("required_legs")
            if not isinstance(required_legs, list):
                raise MetricsError(f"N1 check {check_id}.required_legs must be a list")
            item["required_legs"] = required_legs
        blocking.append(item)
    if not blocking:
        raise MetricsError("N1 inventory has no blocking checks")
    return {"checks": blocking, "path": str(path)}


def pypi_history(payload: object, package: str) -> list[dict[str, Any]]:
    """Normalize complete PyPI release file history, including yanks and times."""
    if not isinstance(payload, dict) or not isinstance(payload.get("releases"), dict):
        raise MetricsError(f"PyPI {package} response is missing releases")
    rows: list[dict[str, Any]] = []
    for version, raw_files in payload["releases"].items():
        if not isinstance(version, str) or not isinstance(raw_files, list):
            raise MetricsError(f"PyPI {package} has a malformed release entry")
        for index, raw in enumerate(raw_files):
            if not isinstance(raw, dict):
                raise MetricsError(f"PyPI {package} {version} file {index} is invalid")
            name = raw.get("filename")
            digests = raw.get("digests")
            yanked = raw.get("yanked")
            if not isinstance(name, str) or not name.strip():
                raise MetricsError(f"PyPI {package} {version} file {index} is invalid")
            if not isinstance(digests, dict):
                raise MetricsError(f"PyPI {package} {version} file {index} is invalid")
            digest = digests.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", digest.lower()
            ):
                raise MetricsError(f"PyPI {package} {version} file {index} is invalid")
            if not isinstance(yanked, bool):
                raise MetricsError(f"PyPI {package} {version} file {index} is invalid")
            uploaded = _instant(
                raw.get("upload_time_iso_8601"),
                f"PyPI {package} {version}[{index}].upload_time_iso_8601",
            )
            rows.append(
                {
                    "package": package,
                    "version": version,
                    "filename": name,
                    "sha256": digest.lower(),
                    "yanked": yanked,
                    "uploaded_at": _iso(uploaded),
                }
            )
    return sorted(
        rows, key=lambda item: (item["uploaded_at"], item["version"], item["filename"])
    )


def confirmed_releases(
    pypi_files: list[dict[str, Any]], github_releases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Join public wheel/sdist files to un-drafted GitHub releases."""
    releases = {
        match.group("version"): raw
        for raw in github_releases
        if isinstance(raw, dict)
        and not raw.get("draft", True)
        and isinstance(raw.get("tag"), str)
        and (match := _VERSION_TAG_RE.fullmatch(raw["tag"]))
    }
    by_version: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in pypi_files:
        by_version[item["version"]].append(item)
    found: list[dict[str, Any]] = []
    for version, files in by_version.items():
        release = releases.get(version)
        if release is None:
            continue
        wheels = [
            item for item in files if str(item.get("filename", "")).endswith(".whl")
        ]
        sdists = [
            item
            for item in files
            if str(item.get("filename", "")).endswith((".tar.gz", ".zip"))
        ]
        if not wheels or not sdists:
            continue
        uploaded = max(
            _instant(item["uploaded_at"], "file.uploaded_at") for item in files
        )
        found.append(
            {
                "version": version,
                "tag": release["tag"],
                "confirmed_at": _iso(uploaded),
                "yanked": any(item.get("yanked") for item in files),
                "file_count": len(files),
                "notes": release.get("body") or "",
                "github_release": release,
            }
        )
    return sorted(found, key=lambda item: item["confirmed_at"])


def _job_matches(actual: str, expected: str) -> bool:
    return actual == expected or actual.endswith(f" / {expected}")


def assess_release_green(
    sha: str,
    *,
    master_gate_runs: list[dict[str, Any]],
    full_ci_runs: list[dict[str, Any]],
    release_runs: list[dict[str, Any]],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate exact-SHA evidence using the checked-in N1 blocking inventory."""
    target = sha.lower()
    if not _SHA_RE.fullmatch(target):
        raise MetricsError("sha must be a full git commit SHA")

    def matching(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if str(row.get("sha") or "").lower() == target]

    gate = [
        row for row in matching(master_gate_runs) if row.get("conclusion") == "success"
    ]
    full = [row for row in matching(full_ci_runs) if row.get("conclusion") == "success"]
    release = matching(release_runs)
    evidence: list[dict[str, Any]] = []
    all_checks_pass = True
    for check in inventory["checks"]:
        candidates = {"ci.yml": full, "release.yml": release}.get(check["workflow"], [])
        if check["workflow"] == "release.yml":
            expected_count = len(check.get("required_legs") or []) or 1
            matching_jobs = [
                job
                for run in candidates
                for job in run.get("jobs") or []
                if isinstance(job, dict)
                and str(job.get("name") or "").startswith(f"{check['job_name']} (")
                and job.get("conclusion") == "success"
            ]
            passed = len(matching_jobs) >= expected_count
            evidence.append(
                {
                    "id": check["id"],
                    "workflow": check["workflow"],
                    "job": check["job_name"],
                    "required": expected_count,
                    "passed": len(matching_jobs),
                    "conclusion": "success" if passed else "missing_or_red",
                }
            )
        elif check["workflow"] == "ci.yml":
            matching_jobs = [
                job
                for run in candidates
                for job in run.get("jobs") or []
                if isinstance(job, dict)
                and _job_matches(str(job.get("name") or ""), check["job_name"])
                and job.get("conclusion") == "success"
            ]
            passed = bool(matching_jobs)
            evidence.append(
                {
                    "id": check["id"],
                    "workflow": check["workflow"],
                    "job": check["job_name"],
                    "required": 1,
                    "passed": len(matching_jobs),
                    "conclusion": "success" if passed else "missing_or_red",
                }
            )
        else:
            passed = False
            evidence.append(
                {
                    "id": check["id"],
                    "workflow": check["workflow"],
                    "job": check["job_name"],
                    "required": 1,
                    "passed": 0,
                    "conclusion": "unsupported_workflow",
                }
            )
        all_checks_pass = all_checks_pass and passed
    gate_ok = bool(gate)
    full_ok = bool(full)
    release_green = bool(gate_ok and full_ok and all_checks_pass)
    return {
        "sha": target,
        "release_green": release_green,
        "evidence": {
            "master_gate": gate,
            "full_ci": full,
            "n1_blocking_jobs": evidence,
        },
        "missing": [
            name
            for name, ok in (
                ("master_gate", gate_ok),
                ("full_ci", full_ok),
                ("n1_blocking_jobs", all_checks_pass),
            )
            if not ok
        ],
    }


def _nearest_rank(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(percentile / 100 * len(ordered)) - 1, 0)
    return ordered[index]


def _distribution(
    values: list[float], unit: str, start: datetime, end: datetime
) -> dict[str, Any]:
    count = len(values)
    return {
        "unit": unit,
        "p50": _nearest_rank(values, 50),
        "p90": _nearest_rank(values, 90),
        "numerator": {"samples": sorted(values), "sample_unit": unit},
        "denominator": {"count": count, "unit": "completed observations"},
        "display": (
            f"p50 {_nearest_rank(values, 50):.2f} {unit}, "
            f"p90 {_nearest_rank(values, 90):.2f} {unit} ({count} samples)"
            if count
            else "n/a (0 of 0)"
        ),
        "window": {"start": _iso(start), "end": _iso(end)},
    }


def _ratio(
    numerator: float,
    denominator: float,
    *,
    unit: str,
    start: datetime,
    end: datetime,
    precision: int = 2,
) -> dict[str, Any]:
    value = numerator / denominator if denominator else None
    display = (
        f"{value:.{precision}f} {unit} ({numerator:g} of {denominator:g})"
        if value is not None
        else "n/a (0 of 0)"
    )
    return {
        "value": value,
        "unit": unit,
        "numerator": numerator,
        "denominator": denominator,
        "display": display,
        "window": {"start": _iso(start), "end": _iso(end)},
    }


def _ancestor(candidate: str, original: str, parents: dict[str, list[str]]) -> bool:
    pending = list(parents.get(candidate, []))
    seen: set[str] = set()
    while pending:
        parent = pending.pop()
        if parent == original:
            return True
        if parent not in seen:
            seen.add(parent)
            pending.extend(parents.get(parent, []))
    return candidate == original


def _version_mentions_fix(notes: str, version: str) -> bool:
    matches = list(_VERSION_RE.finditer(notes))
    for match in matches:
        if match.group(1) != version:
            continue
        left = max(0, match.start() - 100)
        right = min(len(notes), match.end() + 100)
        if _FIX_WORD_RE.search(notes[left:right]):
            return True
    return False


def _attach_jobs(
    runs: list[dict[str, Any]],
    commit_shas: set[str],
    facts: ReleaseFactsReader,
) -> list[dict[str, Any]]:
    """Read exact-SHA workflow jobs concurrently while retaining run order."""
    result = list(runs)
    targets = [
        (index, row) for index, row in enumerate(runs) if row["sha"] in commit_shas
    ]
    if not targets:
        return result

    def read_jobs(run: dict[str, Any]) -> list[dict[str, Any]]:
        for attempt in range(3):
            try:
                return facts.read_jobs(run["run_id"], run["attempt"])
            except ReleaseTransportError as exc:
                transient = any(
                    marker in str(exc)
                    for marker in ("HTTP 429", "HTTP 502", "HTTP 503", "HTTP 504")
                )
                if not transient or attempt == 2:
                    raise
                time.sleep(0.25 * (2**attempt))
        raise AssertionError("job read retry loop exhausted")

    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        pending = {pool.submit(read_jobs, row): index for index, row in targets}
        for future in as_completed(pending):
            index = pending[future]
            result[index] = {**result[index], "jobs": future.result()}
    return result


def calculate_metrics(
    snapshot: dict[str, Any],
    *,
    inventory: dict[str, Any],
    now: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any]:
    """Calculate every release figure from a fully read-only fact snapshot."""
    del inventory
    if window_days < 1:
        raise ValueError("window_days must be positive")
    end = now.astimezone(UTC)
    start = end - timedelta(days=window_days)
    commits = [
        row
        for row in snapshot.get("commits") or []
        if start <= _instant(row["committed_at"], "commit.committed_at") <= end
    ]
    parents = {row["sha"]: row.get("parents") or [] for row in commits}
    releases = [
        row
        for row in snapshot.get("confirmed_releases") or []
        if _instant(row["confirmed_at"], "release.confirmed_at") <= end
    ]
    window_releases = [
        row
        for row in releases
        if start <= _instant(row["confirmed_at"], "release.confirmed_at") <= end
    ]
    metrics: dict[str, Any] = {}
    last_release = max(releases, key=lambda item: item["confirmed_at"], default=None)
    if last_release is None:
        metrics["days_since_last_confirmed_release"] = {
            **_ratio(0, 0, unit="days", start=start, end=end),
            "numerator": None,
            "denominator": None,
            "display": "n/a (0 of 0)",
            "evidence": None,
        }
    else:
        seconds = max(
            0,
            (
                end - _instant(last_release["confirmed_at"], "release.confirmed_at")
            ).total_seconds(),
        )
        metrics["days_since_last_confirmed_release"] = {
            **_ratio(seconds, 86400, unit="days", start=start, end=end),
            "evidence": {
                "version": last_release["version"],
                "confirmed_at": last_release["confirmed_at"],
            },
        }

    lead_times: list[float] = []
    for item in snapshot.get("release_commits") or []:
        published = _instant(item["published_at"], "release_commits.published_at")
        for commit in item.get("commits") or []:
            arrived = _instant(commit["committed_at"], "release_commits.committed_at")
            if not (start <= arrived <= end):
                continue
            if arrived <= published:
                lead_times.append((published - arrived).total_seconds() / 3600)
    metrics["landing_to_pypi_lead_time"] = _distribution(
        lead_times, "hours", start, end
    )

    green = snapshot.get("green_by_sha") or {}
    durations: list[float] = []
    ordered = sorted(commits, key=lambda item: item["committed_at"])
    for commit in ordered:
        arrival = _instant(commit["committed_at"], "commit.committed_at")
        successors = [
            candidate
            for candidate in ordered
            if green.get(candidate["sha"], {}).get("release_green")
            and _ancestor(candidate["sha"], commit["sha"], parents)
            and _instant(candidate["committed_at"], "commit.committed_at") >= arrival
        ]
        if not successors:
            continue
        first_green = min(successors, key=lambda item: item["committed_at"])
        durations.append(
            max(
                0,
                (
                    _instant(first_green["committed_at"], "green commit time") - arrival
                ).total_seconds()
                / 3600,
            )
        )
    green_metric = _distribution(durations, "hours", start, end)
    green_metric["target_hours"] = 6
    green_metric["censored_commits"] = len(commits) - len(durations)
    green_metric["arrival_basis"] = "Git commit committer timestamp"
    metrics["time_to_release_green"] = green_metric
    metrics["landing_to_pypi_lead_time"]["arrival_basis"] = (
        "Git commit committer timestamp"
    )

    lag_seconds = float(snapshot.get("core_lag_seconds") or 0)
    lag_intervals = int(snapshot.get("core_lag_intervals") or 0)
    metrics["core_lag_hours"] = {
        **_ratio(lag_seconds, 3600, unit="hours", start=start, end=end),
        "intervals": lag_intervals,
        "unverifiable_versions": snapshot.get("core_unverifiable_versions") or [],
        "unverifiable_pins": snapshot.get("core_unverifiable_pins") or [],
        "basis": (
            "total uncontained pin seconds divided by seconds per hour; "
            "core tags without an EXPECTED_DIST_SUFFIXES completeness "
            "contract are treated as incomplete and listed as unverifiable"
        ),
    }

    burned: dict[str, dict[str, Any]] = {}
    published_versions = {
        item["version"] for item in snapshot.get("pypi_sase_files") or []
    }
    for tag in snapshot.get("tags") or []:
        match = _VERSION_TAG_RE.fullmatch(str(tag.get("name") or ""))
        if not match:
            continue
        if match.group("version") in published_versions:
            continue
        committed = _instant(tag["committed_at"], "tag.committed_at")
        if not (start <= committed <= end):
            continue
        burned[match.group("version")] = {
            "version": match.group("version"),
            "reason": "tag has no PyPI files",
            "at": tag["committed_at"],
        }
    for release in snapshot.get("github_releases") or []:
        has_abandoned = any(
            asset.get("kind") == "abandoned" for asset in release.get("assets") or []
        )
        match = _VERSION_TAG_RE.fullmatch(str(release.get("tag") or ""))
        if not match or not has_abandoned:
            continue
        created = _instant(release["created_at"], "release.created_at")
        if not (start <= created <= end):
            continue
        burned[match.group("version")] = {
            "version": match.group("version"),
            "reason": "abandoned draft",
            "at": release["created_at"],
        }
    weeks = window_days / 7
    burn_metric = _ratio(
        len(burned),
        weeks,
        unit="versions/week",
        start=start,
        end=end,
        precision=2,
    )
    burn_metric["versions"] = [burned[key] for key in sorted(burned)]
    metrics["burned_versions_per_week"] = burn_metric

    eligible = [
        row
        for row in window_releases
        if _instant(row["confirmed_at"], "release.confirmed_at") + timedelta(days=7)
        <= end
    ]
    yanked_versions = {
        item["version"]
        for item in snapshot.get("pypi_sase_files") or []
        if item.get("yanked")
    }
    issue_events: list[dict[str, Any]] = []
    for issue in snapshot.get("issues") or []:
        if str(issue.get("family") or "").upper() != "INSTALL_BROKEN":
            continue
        opened = _instant(issue["opened_at"], "issue.opened_at")
        if not (start <= opened <= end):
            continue
        text = str(issue.get("title") or "")
        issue_events.append(
            {
                "opened_at": opened,
                "versions": set(_VERSION_RE.findall(text)),
            }
        )
    failure_evidence: dict[str, list[str]] = defaultdict(list)
    for release in eligible:
        version = release["version"]
        if version in yanked_versions:
            failure_evidence[version].append("currently yanked on PyPI")
        release_at = _instant(release["confirmed_at"], "release.confirmed_at")
        if any(
            version in event["versions"]
            and release_at <= event["opened_at"] <= release_at + timedelta(days=7)
            for event in issue_events
        ):
            failure_evidence[version].append(
                "INSTALL_BROKEN issue opened within seven days"
            )
        for later in releases:
            delta = _instant(later["confirmed_at"], "release.confirmed_at") - _instant(
                release["confirmed_at"], "release.confirmed_at"
            )
            if not (timedelta(0) < delta <= timedelta(days=7)):
                continue
            if _version_mentions_fix(str(later.get("notes") or ""), version):
                failure_evidence[version].append(
                    f"{later['version']} release notes reference a fix"
                )
    failed = sorted(failure_evidence)
    change_fail = _ratio(
        len(failed),
        len(eligible),
        unit="rate",
        start=start,
        end=end,
        precision=4,
    )
    change_fail["percent"] = (len(failed) / len(eligible) * 100) if eligible else None
    change_fail["display"] = (
        f"{change_fail['percent']:.2f}% ({len(failed)} of {len(eligible)})"
        if eligible
        else "n/a (0 of 0)"
    )
    change_fail["releases"] = [
        {"version": version, "reasons": failure_evidence[version]} for version in failed
    ]
    change_fail["maturity_days"] = 7
    change_fail["yank_time"] = "PyPI exposes current yanked state, not yank timestamp"
    metrics["change_fail_rate"] = change_fail
    return {
        "schema_version": 1,
        "observed_at": _iso(end),
        "window": {"days": window_days, "start": _iso(start), "end": _iso(end)},
        "release_green_definition": (
            "Master Gate success and exact-SHA Full CI success on every "
            "blocking N1 job; release.yml exercise legs are also required "
            "when listed in N1."
        ),
        "metrics": metrics,
    }


def _core_lag_for_window(
    facts: ReleaseFactsReader,
    health: ReleaseHealthReader,
    *,
    start: datetime,
    end: datetime,
    core_payload: dict[str, Any],
    core_files: list[dict[str, Any]],
) -> tuple[float, int, list[str], list[dict[str, str]]]:
    """Measure pin intervals until a complete published core contains each pin."""
    changes = facts.read_commits(
        since=start,
        until=end,
        branch="master",
        path="sase-core-revision.txt",
    )
    current_sha = facts.read_ref_sha("heads/master")
    current_pin = facts.read_source_pin(current_sha)
    intervals: list[tuple[str, datetime, datetime]] = []
    cursor = start
    pin = current_pin
    if changes:
        first_parent = changes[0].get("parents") or []
        if first_parent:
            pin = facts.read_source_pin(first_parent[0])
        else:
            pin = current_pin
        for change in changes:
            when = max(start, _instant(change["committed_at"], "pin commit time"))
            if when > cursor:
                intervals.append((pin, cursor, when))
            after = facts.read_source_pin(change["sha"])
            if after != pin:
                pin = after
            cursor = when
    if cursor < end:
        intervals.append((pin, cursor, end))
    elif not intervals and not changes:
        intervals.append((current_pin, start, end))

    total = 0.0
    counted = 0
    raw_releases = core_payload.get("releases")
    if not isinstance(raw_releases, dict):
        raise MetricsError("PyPI sase-core-rs response is missing releases")
    upload_times = {
        item["filename"]: _instant(item["uploaded_at"], "core upload time")
        for item in core_files
    }
    workflow_cache: dict[str, str] = {}
    unverifiable_versions: set[str] = set()
    unverifiable_cutoff: tuple[int, ...] | None = None
    unverifiable_pins: dict[str, str] = {}

    def workflow_at(version: str) -> str:
        if version not in workflow_cache:
            workflow_cache[version] = health._core_workflow_text(version)
        return workflow_cache[version]

    completion_cache: dict[str, datetime | None] = {}

    def completion_time(version: str) -> datetime | None:
        nonlocal unverifiable_cutoff
        if version in completion_cache:
            return completion_cache[version]
        version_key = tuple(int(part) for part in version.split("."))
        if unverifiable_cutoff is not None and version_key < unverifiable_cutoff:
            unverifiable_versions.add(version)
            completion_cache[version] = None
            return None
        try:
            entries = raw_releases.get(version)
            if not isinstance(entries, list):
                entries = []
            suffixes = parse_expected_suffixes(workflow_at(version))
        except CoreEnsureError as exc:
            if "cannot find EXPECTED_DIST_SUFFIXES" in str(exc):
                unverifiable_cutoff = version_key
                unverifiable_versions.add(version)
                completion_cache[version] = None
                return None
            raise MetricsError(
                f"cannot read core completeness contract at v{version}: {exc}"
            ) from exc
        filenames = complete_files_for_version(version, entries, suffixes)
        if filenames is None or any(
            filename not in upload_times for filename in filenames
        ):
            completion_cache[version] = None
            return None
        result = max(upload_times[filename] for filename in filenames)
        completion_cache[version] = result
        return result

    def result_for_pin(source_pin: str, version: str) -> Pinned | CoreLag:
        if version not in raw_releases:
            return CoreLag(source_pin, None)
        one_release = {**core_payload, "releases": {version: raw_releases[version]}}
        try:
            return ensure_core(
                source_pin,
                pypi_metadata=one_release,
                compare_fn=health._core_compare,
                workflow_fn=workflow_at,
            )
        except CoreEnsureError as exc:
            if "unreadable compare" in str(exc):
                unverifiable_pins[source_pin] = "unreadable compare"
                return CoreLag(source_pin, None)
            raise MetricsError(
                f"cannot evaluate historical core pin {source_pin}: {exc}"
            ) from exc

    versions = sorted(
        (version for version in raw_releases if isinstance(version, str)),
        key=lambda version: tuple(
            int(part) for part in version.split(".") if part.isdigit()
        ),
        reverse=True,
    )
    for source_pin, interval_start, interval_end in intervals:
        if interval_start >= interval_end:
            continue
        counted += 1
        prior_checked = False
        prior_contained = False
        for version in versions:
            published_at = completion_time(version)
            if published_at is None or published_at > interval_start:
                continue
            prior_result = result_for_pin(source_pin, version)
            prior_checked = True
            prior_contained = isinstance(prior_result, Pinned)
            break
        if prior_checked and prior_contained:
            continue
        end_of_lag: datetime | None = None
        future = [
            (version, published_at)
            for version in versions
            if (published_at := completion_time(version)) is not None
        ]
        for version, published_at in sorted(future, key=lambda item: item[1]):
            if not (interval_start < published_at <= interval_end):
                continue
            result = result_for_pin(source_pin, version)
            if isinstance(result, Pinned):
                end_of_lag = published_at
                break
        total += ((end_of_lag or interval_end) - interval_start).total_seconds()
    return (
        total,
        counted,
        sorted(
            unverifiable_versions,
            key=lambda version: tuple(
                int(part) for part in version.split(".") if part.isdigit()
            ),
        ),
        [
            {"pin": pin, "reason": reason}
            for pin, reason in sorted(unverifiable_pins.items())
        ],
    )


def collect_snapshot(
    *,
    repo: str = DEFAULT_REPO,
    start: datetime,
    end: datetime,
    facts: ReleaseFactsReader | None = None,
    health: ReleaseHealthReader | None = None,
) -> tuple[dict[str, Any], ReleaseFactsReader, ReleaseHealthReader]:
    """Collect a read-only metrics snapshot using steward facts/health readers."""
    facts = facts or ReleaseFactsReader(
        repo,
        github=GithubTransport(repo, timeout=GITHUB_HISTORY_TIMEOUT_SECONDS),
    )
    health = health or ReleaseHealthReader(
        facts,
        core_github=GithubTransport(
            "sase-org/sase-core", timeout=GITHUB_HISTORY_TIMEOUT_SECONDS
        ),
    )
    commits = facts.read_commits(since=start, until=end, branch="master")
    gate_runs = facts.read_runs(
        "master-gate.yml", since=start, until=end, include_jobs=False
    )
    full_runs = facts.read_runs("full.yml", since=start, until=end, include_jobs=False)
    release_runs = facts.read_runs(
        "release.yml", since=start, until=end, include_jobs=False
    )
    github_releases = facts.read_release_history()
    tags = facts.read_tags(since=start, until=end)
    pypi_sase = pypi_history(facts.pypi.project("sase"), "sase")
    pypi_core_payload = facts.pypi.project("sase-core-rs")
    pypi_core = pypi_history(pypi_core_payload, "sase-core-rs")
    release_list = confirmed_releases(pypi_sase, github_releases)
    release_commits: list[dict[str, Any]] = []
    for index, release in enumerate(release_list):
        published_at = _instant(release["confirmed_at"], "release.confirmed_at")
        if not (start <= published_at <= end) or index == 0:
            continue
        previous = release_list[index - 1]
        rows = facts.read_commits_between_refs(
            previous["tag"],
            release["tag"],
            since=start,
            until=published_at,
        )
        release_commits.append(
            {
                "version": release["version"],
                "published_at": release["confirmed_at"],
                "commits": rows,
            }
        )
    inventory = load_inventory(
        Path(__file__).resolve().parents[1] / ".github" / "release-qualification.json"
    )
    by_sha: dict[str, dict[str, Any]] = {}
    commit_shas = {row["sha"] for row in commits}
    full_runs = _attach_jobs(full_runs, commit_shas, facts)
    release_runs = _attach_jobs(release_runs, commit_shas, facts)
    for row in commits:
        sha = row["sha"]
        assessment = assess_release_green(
            sha,
            master_gate_runs=gate_runs,
            full_ci_runs=full_runs,
            release_runs=release_runs,
            inventory=inventory,
        )
        by_sha[sha] = assessment
    issues = health.read_issues()
    (
        core_lag_seconds,
        core_lag_intervals,
        core_unverifiable_versions,
        core_unverifiable_pins,
    ) = _core_lag_for_window(
        facts,
        health,
        start=start,
        end=end,
        core_payload=pypi_core_payload,
        core_files=pypi_core,
    )
    snapshot = {
        "commits": commits,
        "release_commits": release_commits,
        "green_by_sha": by_sha,
        "confirmed_releases": release_list,
        "github_releases": github_releases,
        "tags": tags,
        "pypi_sase_files": pypi_sase,
        "issues": issues,
        "core_lag_seconds": core_lag_seconds,
        "core_lag_intervals": core_lag_intervals,
        "core_unverifiable_versions": core_unverifiable_versions,
        "core_unverifiable_pins": core_unverifiable_pins,
    }
    return snapshot, facts, health


def collect_green(
    sha: str,
    *,
    repo: str = DEFAULT_REPO,
    inventory_path: Path = _DEFAULT_INVENTORY,
    facts: ReleaseFactsReader | None = None,
) -> dict[str, Any]:
    """Read exact-SHA Master Gate, Full CI and N1 job evidence."""
    if not _SHA_RE.fullmatch(sha.strip().lower()):
        raise MetricsError("sha must be a full git commit SHA")
    reader = facts or ReleaseFactsReader(
        repo,
        github=GithubTransport(repo, timeout=GITHUB_HISTORY_TIMEOUT_SECONDS),
    )
    inventory = load_inventory(inventory_path)
    return assess_release_green(
        sha,
        master_gate_runs=reader.read_runs_for_sha("master-gate.yml", sha),
        full_ci_runs=reader.read_runs_for_sha("full.yml", sha),
        release_runs=reader.read_runs_for_sha("release.yml", sha),
        inventory=inventory,
    )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Release metrics",
        "",
        f"Observed: {report['observed_at']}",
        (
            f"Window: {report['window']['days']} days "
            f"({report['window']['start']} to {report['window']['end']})"
        ),
        "",
        report["release_green_definition"],
        "",
        "| Figure | Result | Numerator | Denominator |",
        "| --- | --- | ---: | ---: |",
    ]
    labels = {
        "days_since_last_confirmed_release": "Days since last confirmed release",
        "landing_to_pypi_lead_time": "Landing to PyPI lead time",
        "time_to_release_green": "Time to release-green",
        "core_lag_hours": "Core lag",
        "burned_versions_per_week": "Burned versions per week",
        "change_fail_rate": "Change-fail rate",
    }
    for key, title in labels.items():
        item = report["metrics"][key]
        den = item.get("denominator")
        if isinstance(den, dict):
            den = den.get("count", den)
        num = item.get("numerator")
        if isinstance(num, dict):
            num = len(num.get("samples") or [])
        lines.append(f"| {title} | {item.get('display', 'n/a')} | {num} | {den} |")
    lines.append("")
    if any(
        key in report["metrics"]
        for key in ("landing_to_pypi_lead_time", "time_to_release_green")
    ):
        lines.extend(
            [
                "",
                "Percentiles use nearest-rank selection. Empty samples are shown as `n/a (0 of 0)`.",
                "The change-fail numerator uses PyPI's current yank flag because PyPI does not expose yank timestamps.",
                "",
            ]
        )
    return "\n".join(lines)


__all__ = (
    "DEFAULT_REPO",
    "DEFAULT_WINDOW_DAYS",
    "MetricsError",
    "assess_release_green",
    "calculate_metrics",
    "collect_green",
    "collect_snapshot",
    "confirmed_releases",
    "load_inventory",
    "pypi_history",
    "render_markdown",
)
