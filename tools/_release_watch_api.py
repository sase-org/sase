#!/usr/bin/env python3
"""Implementation for the stdlib-only release watcher executable."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any
from collections.abc import Callable, Mapping, Sequence


EXIT_CODES = {
    "RELEASED": 0,
    "FULL_CI_RED": 10,
    "PUBLISH_FAILED": 11,
    "CORE_FLOOR_BLOCKED": 12,
    "RELEASE_PR_GONE": 13,
    "INSTALL_FAILED": 14,
    "DEADLINE": 15,
    "WATCHER_BROKEN": 16,
}
IN_FLIGHT = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
BAD_CONCLUSIONS = frozenset(
    {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}
)
GOOD_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})
SIGNALS = ("pypi", "release_pr", "full_ci", "master_gate", "publish", "core_pypi")
GH_TIMEOUT = 30
HTTP_TIMEOUT = 20
PROCESS_TIMEOUT = 300
LOG_EXCERPT_LIMIT = 1800


class WatcherError(Exception):
    """An actionable watcher failure with a concise diagnostic."""


class _WatchArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise WatcherError(message)


class WatcherSignal(Exception):
    """Raised by the signal boundary to enter normal verdict finalization."""

    def __init__(self, signum: int) -> None:
        super().__init__(f"received signal {signum}")
        self.signum = signum


@dataclass(frozen=True)
class WatchOptions:
    repo: str
    version: str
    fixed_sha: str
    deadline: float
    poll: float
    max_red_full_ci: int
    dry_run: bool = False
    once: bool = False
    verdict_file: str | None = None
    close_bead: str | None = None


@dataclass(frozen=True)
class WorkflowRun:
    run_id: int
    sha: str
    status: str
    conclusion: str | None
    created_at: datetime
    updated_at: datetime
    url: str
    jobs: tuple[tuple[str, str | None], ...] = ()
    failed_excerpt: str = ""
    visual_golden_drift: bool = False

    @property
    def is_in_flight(self) -> bool:
        return self.status in IN_FLIGHT

    @property
    def is_red(self) -> bool:
        return self.conclusion not in GOOD_CONCLUSIONS and self.conclusion is not None

    @property
    def failed_jobs(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, conclusion in self.jobs
            if conclusion is not None and conclusion not in GOOD_CONCLUSIONS
        )

    @property
    def deterministic_failure(self) -> bool:
        return any("lint" in name.lower() for name in self.failed_jobs) or (
            self.visual_golden_drift
        )


@dataclass(frozen=True)
class ReleasePullRequest:
    number: int
    title: str
    state: str
    merged_at: datetime | None
    merge_state: str
    head_sha: str
    head_created_at: datetime
    url: str
    checks: Mapping[str, str]

    @property
    def is_merged(self) -> bool:
        return self.merged_at is not None

    @property
    def floor_failed(self) -> bool:
        return any(
            "release-core-floor-smoke" in name.lower() and status == "failure"
            for name, status in self.checks.items()
        )


@dataclass(frozen=True)
class Snapshot:
    pypi_versions: tuple[str, ...]
    release_pr: ReleasePullRequest | None
    full_runs: tuple[WorkflowRun, ...]
    master_sha: str
    master_gate: WorkflowRun | None
    publish_runs: tuple[WorkflowRun, ...]
    core_version: str
    core_uploaded_at: datetime
    ci_watch_reason: str

    @property
    def fixed_runs(self) -> tuple[WorkflowRun, ...]:
        return tuple(run for run in self.full_runs if not run.is_in_flight)

    @property
    def full_in_flight(self) -> bool:
        return any(run.is_in_flight for run in self.full_runs)

    @property
    def publish_in_flight(self) -> bool:
        return any(run.is_in_flight for run in self.publish_runs)

    @property
    def newest_publish(self) -> WorkflowRun | None:
        return max(self.publish_runs, key=lambda run: run.created_at, default=None)

    def state_values(self, version: str) -> dict[str, str]:
        pr = self.release_pr
        fixed = self.fixed_runs
        full_latest = max(fixed, key=lambda run: run.updated_at, default=None)
        gate = self.master_gate
        pub = self.newest_publish
        return {
            "pypi": "present" if version in self.pypi_versions else "absent",
            "release_pr": (
                "gone"
                if pr is None
                else f"#{pr.number}:{'merged' if pr.is_merged else pr.state.lower()}:{pr.merge_state}"
            ),
            "full_ci": (
                f"in_flight:{sum(run.is_in_flight for run in self.full_runs)}"
                if self.full_in_flight
                else "none"
                if full_latest is None
                else f"{full_latest.run_id}:{full_latest.conclusion}:{full_latest.sha[:12]}"
            ),
            "master_gate": (
                f"{gate.run_id}:{gate.conclusion}:{gate.sha[:12]}"
                if gate
                else f"no_run:{self.master_sha[:12]}"
            ),
            "publish": (
                f"in_flight:{sum(run.is_in_flight for run in self.publish_runs)}"
                if self.publish_in_flight
                else "none"
                if pub is None
                else f"{pub.run_id}:{pub.conclusion}"
            ),
            "core_pypi": f"{self.core_version}@{iso_utc(self.core_uploaded_at)}",
        }


@dataclass(frozen=True)
class SignalFailure:
    name: str
    message: str


def iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} is not an ISO timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _parse_duration(value: str) -> float:
    match = re.fullmatch(r"([1-9][0-9]*)(s|m|h|d)", value.strip(), re.IGNORECASE)
    if not match:
        raise argparse.ArgumentTypeError(
            "duration must be a positive value such as 5m or 12h"
        )
    amount = int(match.group(1))
    scale = {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2).lower()]
    return float(amount * scale)


def parse_args(argv: Sequence[str] | None = None) -> WatchOptions:
    parser = _WatchArgumentParser(
        description=(
            "Poll the sase release signals, dispatch only the guarded CI/Publish actions, "
            "and write a final evidence verdict."
        ),
    )
    parser.add_argument(
        "--repo",
        default="sase-org/sase",
        help="GitHub owner/repository (default: sase-org/sase)",
    )
    parser.add_argument(
        "--version", default="0.18.0", help="PyPI version to confirm (default: 0.18.0)"
    )
    parser.add_argument(
        "--fixed-sha", required=True, help="Commit whose Full CI coverage is required"
    )
    parser.add_argument(
        "--deadline",
        type=_parse_duration,
        default=_parse_duration("12h"),
        help="Watch duration, for example 12h (default: 12h)",
    )
    parser.add_argument(
        "--poll",
        type=_parse_duration,
        default=_parse_duration("5m"),
        help="Poll interval, for example 5m (default: 5m)",
    )
    parser.add_argument(
        "--max-red-full-ci",
        type=int,
        default=2,
        help="Stop after this many red fixed-code Full CI runs (default: 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Describe actions without dispatching or closing",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read and print one fully parsed state without dispatching or closing",
    )
    parser.add_argument(
        "--verdict-file",
        help="Evidence path (default: monitor diagnostics dir or fresh temp directory)",
    )
    parser.add_argument(
        "--close-bead", help="Close this bead after writing the verdict"
    )
    ns = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", ns.repo):
        parser.error("--repo must be owner/repository")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", ns.version):
        parser.error("--version must be a semantic version")
    if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", ns.fixed_sha):
        parser.error("--fixed-sha must be a 40- or 64-character Git SHA")
    if ns.max_red_full_ci < 1:
        parser.error("--max-red-full-ci must be at least 1")
    return WatchOptions(
        repo=ns.repo,
        version=ns.version,
        fixed_sha=ns.fixed_sha.lower(),
        deadline=ns.deadline,
        poll=ns.poll,
        max_red_full_ci=ns.max_red_full_ci,
        dry_run=ns.dry_run,
        once=ns.once,
        verdict_file=ns.verdict_file,
        close_bead=ns.close_bead,
    )


def default_verdict_path() -> Path:
    diagnostics = os.environ.get("SASE_MONITOR_DIAGNOSTICS_DIR")
    if diagnostics:
        return Path(diagnostics) / "release_verdict.md"
    return Path(tempfile.mkdtemp(prefix="release-watch-")) / "release_verdict.md"


def run_process(
    argv: Sequence[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = None if env is None else {**os.environ, **env}
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=merged_env,
    )


@dataclass
class GhClient:
    repo: str
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_process
    executable: str = "gh"
    timeout: float = GH_TIMEOUT

    def _call(self, args: Sequence[str], *, json_output: bool) -> object | str:
        path = shutil.which(self.executable)
        if path is None:
            raise WatcherError(f"{self.executable!r} is not installed or not on PATH")
        argv = [path, *args]
        env: dict[str, str] | None = None
        if args and args[0] == "api":
            env = {"GH_REPO": self.repo}
        elif not (args and args[0] == "auth"):
            argv.extend(["--repo", self.repo])
        try:
            result = self.runner(argv, timeout=self.timeout, env=env)
        except (OSError, subprocess.SubprocessError) as exc:
            raise WatcherError(f"gh call failed: {exc}") from exc
        if result.returncode:
            details = (result.stderr or result.stdout or "").strip()[:500]
            raise WatcherError(
                f"gh {' '.join(args)} exited {result.returncode}: {details}"
            )
        if not json_output:
            return result.stdout or ""
        try:
            return json.loads(result.stdout or "")
        except json.JSONDecodeError as exc:
            raise WatcherError(
                f"gh {' '.join(args)} returned malformed JSON: {exc.msg}"
            ) from exc

    def json(self, *args: str) -> object:
        return self._call(args, json_output=True)

    def text(self, *args: str) -> str:
        result = self._call(args, json_output=False)
        assert isinstance(result, str)
        return result

    def validate(self) -> None:
        if shutil.which(self.executable) is None:
            raise WatcherError(f"{self.executable!r} is not installed or not on PATH")
        self.text("auth", "status", "--hostname", "github.com")
        for workflow in ("full.yml", "master-gate.yml", "publish.yml"):
            self.text("workflow", "view", workflow)


def _http_json(url: str, timeout: float = HTTP_TIMEOUT) -> object:
    request = urllib.request.Request(
        url, headers={"User-Agent": "sase-release-watch/1"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        http.client.HTTPException,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise WatcherError(f"HTTP read {url} failed: {exc}") from exc


def _mapping(value: object, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    return value


def _list(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a list")
    return value


def _required_str(obj: Mapping[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}.{key} must be a non-empty string")
    return value


def _optional_str(value: object, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{where} must be a string or null")
    return value


def _parse_job_list(payload: object, where: str) -> tuple[tuple[str, str | None], ...]:
    obj = _mapping(payload, where)
    jobs = _list(obj.get("jobs"), f"{where}.jobs")
    parsed: list[tuple[str, str | None]] = []
    for index, raw in enumerate(jobs):
        job = _mapping(raw, f"{where}.jobs[{index}]")
        name = _required_str(job, "name", f"{where}.jobs[{index}]")
        conclusion = _optional_str(
            job.get("conclusion"), f"{where}.jobs[{index}].conclusion"
        )
        parsed.append((name, conclusion.lower() if conclusion else None))
    return tuple(parsed)


def parse_run(raw: object, where: str) -> WorkflowRun:
    obj = _mapping(raw, where)
    run_id = obj.get("databaseId", obj.get("id"))
    if not isinstance(run_id, int) or isinstance(run_id, bool):
        raise ValueError(f"{where}.databaseId must be an integer")
    sha = _required_str(obj, "headSha", where).lower()
    status = _required_str(obj, "status", where).lower()
    conclusion = _optional_str(obj.get("conclusion"), f"{where}.conclusion")
    if status not in IN_FLIGHT | {"completed"}:
        raise ValueError(f"{where}.status is not recognized: {status}")
    if status == "completed" and conclusion is None:
        raise ValueError(f"{where}.conclusion is required for a completed run")
    created = _parse_datetime(
        obj.get("createdAt", obj.get("created_at")), f"{where}.created_at"
    )
    updated = _parse_datetime(
        obj.get("updatedAt", obj.get("updated_at")), f"{where}.updated_at"
    )
    url = _required_str(obj, "url", where)
    return WorkflowRun(
        run_id,
        sha,
        status,
        conclusion.lower() if conclusion else None,
        created,
        updated,
        url,
    )


def _parse_pypi(payload: object, package: str) -> tuple[tuple[str, ...], str, datetime]:
    obj = _mapping(payload, f"PyPI {package}")
    info = _mapping(obj.get("info"), f"PyPI {package}.info")
    version = _required_str(info, "version", f"PyPI {package}.info")
    releases = _mapping(obj.get("releases"), f"PyPI {package}.releases")
    timestamps: list[datetime] = []
    for index, raw in enumerate(
        _list(releases.get(version), f"PyPI {package}.releases[{version}]")
    ):
        item = _mapping(raw, f"PyPI {package}.releases[{version}][{index}]")
        timestamps.append(
            _parse_datetime(item.get("upload_time_iso_8601"), "upload_time_iso_8601")
        )
    if not timestamps:
        raise ValueError(
            f"PyPI {package} has no upload timestamp for latest version {version}"
        )
    return tuple(str(key) for key in releases), version, max(timestamps)


def _parse_release_pr(
    payload: object, version: str, gh: GhClient
) -> ReleasePullRequest | None:
    rows = _list(payload, "release PR list")
    version_pattern = re.compile(rf"(?<![0-9.]){re.escape(version)}(?![0-9.])")
    candidates: list[Mapping[str, Any]] = []
    for index, raw in enumerate(rows):
        pr = _mapping(raw, f"release PR list[{index}]")
        title = _required_str(pr, "title", f"release PR list[{index}]")
        head = (
            _mapping(pr.get("headRefName"), f"release PR list[{index}].headRefName")
            if isinstance(pr.get("headRefName"), dict)
            else None
        )
        # gh emits headRefName as a string; accept headRefName.name only for API-shaped fixtures.
        branch_value: object = pr.get("headRefName")
        if head is not None:
            branch_value = head.get("name")
        if not isinstance(branch_value, str):
            raise ValueError(f"release PR list[{index}].headRefName must be a string")
        if not branch_value.startswith(
            "release-please--"
        ) or not version_pattern.search(title):
            continue
        state = _required_str(pr, "state", f"release PR list[{index}]").upper()
        merged_value = pr.get("mergedAt")
        merged_at = (
            _parse_datetime(merged_value, "release PR mergedAt")
            if merged_value
            else None
        )
        if state == "OPEN" or merged_at is not None:
            candidates.append(pr)
    if len(candidates) > 1:
        raise ValueError(
            f"found {len(candidates)} open or merged release PRs for {version}"
        )
    if not candidates:
        return None
    pr = candidates[0]
    number = pr.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ValueError("release PR number must be an integer")
    title = _required_str(pr, "title", "release PR")
    state = _required_str(pr, "state", "release PR").upper()
    merged_value = pr.get("mergedAt")
    merged_at = (
        _parse_datetime(merged_value, "release PR mergedAt") if merged_value else None
    )
    merge_state = _required_str(pr, "mergeStateStatus", "release PR").upper()
    head_sha = _required_str(pr, "headRefOid", "release PR").lower()
    url = _required_str(pr, "url", "release PR")
    raw_checks_value = pr.get("statusCheckRollup")
    raw_checks = (
        []
        if raw_checks_value is None
        else _list(raw_checks_value, "release PR statusCheckRollup")
    )
    checks: dict[str, str] = {}
    for index, raw_check in enumerate(raw_checks):
        check = _mapping(raw_check, f"release PR statusCheckRollup[{index}]")
        name = check.get("name", check.get("context"))
        if not isinstance(name, str) or not name:
            raise ValueError(f"release PR statusCheckRollup[{index}] has no name")
        conclusion = check.get("conclusion")
        if conclusion is None and isinstance(check.get("state"), str):
            conclusion = {
                "SUCCESS": "success",
                "FAILURE": "failure",
                "ERROR": "failure",
                "PENDING": "pending",
                "EXPECTED": "pending",
            }.get(check["state"].upper(), "unknown")
        if conclusion is not None and not isinstance(conclusion, str):
            raise ValueError(f"release PR check {name} has invalid conclusion")
        checks[name] = conclusion.lower() if conclusion else "pending"
    commit_payload = gh.json("api", f"repos/{gh.repo}/commits/{head_sha}")
    commit = _mapping(commit_payload, "release PR head commit")
    commit_data = _mapping(commit.get("commit"), "release PR head commit.commit")
    committer = _mapping(
        commit_data.get("committer"), "release PR head commit.commit.committer"
    )
    head_created_at = _parse_datetime(
        committer.get("date"), "release PR head commit date"
    )
    return ReleasePullRequest(
        number,
        title,
        state,
        merged_at,
        merge_state,
        head_sha,
        head_created_at,
        url,
        checks,
    )


def failed_excerpt(text: str) -> str:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if len(cleaned) > LOG_EXCERPT_LIMIT:
        cleaned = "…[truncated]…\n" + cleaned[-LOG_EXCERPT_LIMIT:]
    return cleaned or "FAILED output was empty"


def _is_visual_golden_drift(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "snapshot mismatch",
            "golden drift",
            "golden mismatch",
            "snapshot differs",
            "snapshot is different",
            "visual snapshot",
            "png snapshot differs",
        )
    )


def _scan_release_reason(value: object) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "release_reason" and isinstance(item, str):
                return item
            found = _scan_release_reason(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _scan_release_reason(item)
            if found:
                return found
    return None


def read_ci_watch_reason(home: Path | None = None) -> str:
    root = (home or Path.home()) / ".sase/axe/lumberjacks/ci_watch/chops/ci_watch/runs"
    try:
        files = sorted(
            root.glob("*.result.decisions.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in files:
            try:
                found = _scan_release_reason(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                if found:
                    return found.replace("\n", " ")
            except (OSError, json.JSONDecodeError):
                continue
    except OSError:
        pass
    return "unknown"


@dataclass
class GithubReader:
    repo: str
    version: str
    fixed_sha: str
    gh: GhClient
    get_json: Callable[[str, float], object] = _http_json
    http_timeout: float = HTTP_TIMEOUT

    def validate(self) -> None:
        self.gh.validate()

    def _pypi(self) -> tuple[str, ...]:
        data = self.get_json("https://pypi.org/pypi/sase/json", self.http_timeout)
        releases, _version, _upload = _parse_pypi(data, "sase")
        return releases

    def _core_pypi(self) -> tuple[str, datetime]:
        data = self.get_json(
            "https://pypi.org/pypi/sase-core-rs/json", self.http_timeout
        )
        _releases, version, upload = _parse_pypi(data, "sase-core-rs")
        return version, upload

    def _run_list(
        self, workflow: str, *, branch: str | None = None, limit: int = 100
    ) -> list[WorkflowRun]:
        args = [
            "run",
            "list",
            "--workflow",
            workflow,
            "--limit",
            str(limit),
            "--json",
            "databaseId,headSha,status,conclusion,createdAt,updatedAt,url",
        ]
        if branch:
            args.extend(["--branch", branch])
        payload = self.gh.json(*args)
        return [
            parse_run(row, f"{workflow} run[{index}]")
            for index, row in enumerate(_list(payload, f"{workflow} runs"))
        ]

    def _jobs(self, run: WorkflowRun) -> tuple[tuple[str, str | None], ...]:
        return _parse_job_list(
            self.gh.json("run", "view", str(run.run_id), "--json", "jobs"),
            f"run {run.run_id}",
        )

    def _failed_log(self, run: WorkflowRun) -> str:
        return self.gh.text("run", "view", str(run.run_id), "--log-failed")

    def full_ci(self) -> tuple[WorkflowRun, ...]:
        raw_runs = self._run_list("full.yml", branch="master")
        fixed: list[WorkflowRun] = []
        for run in raw_runs:
            if run.is_in_flight:
                fixed.append(run)
                continue
            if run.sha == self.fixed_sha:
                contains = True
            else:
                comparison = _mapping(
                    self.gh.json(
                        "api", f"repos/{self.repo}/compare/{self.fixed_sha}...{run.sha}"
                    ),
                    f"compare {self.fixed_sha}...{run.sha}",
                )
                status = _required_str(comparison, "status", "compare result").lower()
                if status not in {"ahead", "identical", "behind", "diverged"}:
                    raise ValueError(f"unknown compare status {status!r}")
                contains = status in {"ahead", "identical"}
            if not contains:
                continue
            jobs = self._jobs(run)
            excerpt = ""
            drift = False
            if run.is_red:
                try:
                    raw_log = self._failed_log(run)
                except WatcherError as exc:
                    raw_log = f"FAILED log unavailable: {exc}"
                excerpt = failed_excerpt(raw_log)
                drift = any(
                    "visual-test" in name.lower()
                    for name, conclusion in jobs
                    if conclusion and conclusion not in GOOD_CONCLUSIONS
                ) and _is_visual_golden_drift(raw_log)
            fixed.append(
                WorkflowRun(
                    run.run_id,
                    run.sha,
                    run.status,
                    run.conclusion,
                    run.created_at,
                    run.updated_at,
                    run.url,
                    jobs,
                    excerpt,
                    drift,
                )
            )
        return tuple(sorted(fixed, key=lambda run: run.updated_at, reverse=True))

    def _master_gate(self) -> tuple[str, WorkflowRun | None]:
        ref = _mapping(
            self.gh.json("api", f"repos/{self.repo}/git/ref/heads/master"), "master ref"
        )
        target = _mapping(ref.get("object"), "master ref.object")
        master_sha = _required_str(target, "sha", "master ref").lower()
        runs = self._run_list("master-gate.yml", branch="master")
        matches = [run for run in runs if run.sha == master_sha]
        if not matches:
            return master_sha, None
        latest = max(matches, key=lambda run: run.updated_at)
        if not latest.is_in_flight:
            jobs = self._jobs(latest)
            latest = WorkflowRun(
                latest.run_id,
                latest.sha,
                latest.status,
                latest.conclusion,
                latest.created_at,
                latest.updated_at,
                latest.url,
                jobs,
            )
        return master_sha, latest

    def _release_pr(self) -> ReleasePullRequest | None:
        payload = self.gh.json(
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            "100",
            "--json",
            "number,title,headRefName,state,mergedAt,mergeStateStatus,headRefOid,url,statusCheckRollup",
        )
        return _parse_release_pr(payload, self.version, self.gh)

    def read_signal(self, name: str) -> object:
        if name == "pypi":
            return self._pypi()
        if name == "release_pr":
            return self._release_pr()
        if name == "full_ci":
            return self.full_ci()
        if name == "master_gate":
            return self._master_gate()
        if name == "publish":
            # The upload time is a separately validated required signal; this read can use it next poll.
            return self._run_list("publish.yml", limit=100)
        if name == "core_pypi":
            return self._core_pypi()
        raise ValueError(f"unknown signal {name}")

    def read_signals(self) -> dict[str, object | SignalFailure]:
        result: dict[str, object | SignalFailure] = {}
        for name in SIGNALS:
            try:
                result[name] = self.read_signal(name)
            except WatcherSignal:
                raise
            except Exception as exc:
                result[name] = SignalFailure(name, str(exc))
        # Publish parsing uses the core upload from this same poll. Keep failures attributed to publish.
        core = result.get("core_pypi")
        publish = result.get("publish")
        if (
            isinstance(core, tuple)
            and len(core) == 2
            and not isinstance(publish, SignalFailure)
        ):
            try:
                raw_runs = publish
                if not isinstance(raw_runs, list):
                    raise ValueError("publish workflow result must be a run list")
                relevant: list[WorkflowRun] = []
                newest_ids = {
                    run.run_id
                    for run in sorted(
                        raw_runs, key=lambda item: item.created_at, reverse=True
                    )[:5]
                }
                for run in raw_runs:
                    jobs = (
                        self._jobs(run)
                        if run.is_in_flight or run.run_id in newest_ids
                        else ()
                    )
                    relevant.append(
                        WorkflowRun(
                            run.run_id,
                            run.sha,
                            run.status,
                            run.conclusion,
                            run.created_at,
                            run.updated_at,
                            run.url,
                            jobs,
                        )
                    )
                result["publish"] = tuple(
                    sorted(relevant, key=lambda run: run.created_at, reverse=True)
                )
            except WatcherSignal:
                raise
            except Exception as exc:
                result["publish"] = SignalFailure("publish", str(exc))
        return result
