#!/usr/bin/env python3
"""Read and validate release-train facts for the stateless steward.

This module owns GitHub/PyPI shape conversion, not eligibility policy. It
returns the versioned snapshot wire's facts as plain dictionaries and uses the
existing ``release_candidate verify/evaluate`` CLI for candidate policy. The
health phase adds its own facts to the snapshot returned here; it must not
replace any of these reads with watcher-local verdict rules.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from _release_watch_transport import (
    GithubTransport,
    PypiTransport,
    ReleaseTransportError,
)


DEFAULT_REPO = "sase-org/sase"
RELEASE_WORKFLOW = "release.yml"
PUBLISH_WORKFLOW = "publish.yml"
MASTER_GATE_WORKFLOW = "master-gate.yml"
HISTORY_LOOKBACK = timedelta(days=365)
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)
_VERSION_TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")
_VERSION_RE = re.compile(r"(?<![0-9.])v?(\d+\.\d+\.\d+)(?![0-9.])")
_PIN_RE = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
_CORE_PIN_RE = re.compile(r"sase-core-rs\s*==\s*(\d+\.\d+\.\d+)")
_OBSERVATION_RE = re.compile(
    r"^candidate-gen(?P<generation>\d+)-"
    r"(?P<kind>qualification|exercise|publication|confirmation|abandoned|veto)-"
    r"run(?P<run_id>\d+)-attempt(?P<attempt>\d+)\.json$"
)
_KNOWN_CONCLUSIONS = {
    "success",
    "failure",
    "cancelled",
    "skipped",
    "neutral",
    "timed_out",
    "action_required",
    "startup_failure",
}
_RUN_STATUSES = {
    "queued": "queued",
    "pending": "pending",
    "in_progress": "in_progress",
    "waiting": "waiting",
    "requested": "requested",
    "waiting_for_deployment": "waiting_for_deploy",
    "completed": "completed",
}


class ReleaseFactsError(ValueError):
    """Remote facts were present but malformed or inconsistent."""


def ready(value: Any) -> dict[str, Any]:
    return {"status": "ready", "value": value}


def absent(reason: str) -> dict[str, Any]:
    return {"status": "absent", "reason": reason}


def unreadable(source: str, message: str, remedy: str) -> dict[str, Any]:
    return {
        "status": "unreadable",
        "source": source,
        "message": message,
        "remedy": remedy,
    }


def _mapping(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseFactsError(f"{where} must be an object")
    return value


def _list(value: object, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReleaseFactsError(f"{where} must be a list")
    return value


def _required_str(obj: dict[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReleaseFactsError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def _integer(value: object, where: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ReleaseFactsError(f"{where} must be an integer >= {minimum}")
    return value


def _utc(value: object, where: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseFactsError(f"{where} must be an RFC 3339 timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ReleaseFactsError(f"{where} is not a valid timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseFactsError(f"{where} must include a UTC offset")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bounds(since: datetime | str, until: datetime | str) -> tuple[datetime, datetime]:
    start = _utc(_iso(since) if isinstance(since, datetime) else since, "since")
    end = _utc(_iso(until) if isinstance(until, datetime) else until, "until")
    if start >= end:
        raise ValueError("since must be earlier than until")
    return start, end


def _version_key(version: str) -> tuple[int, int, int]:
    match = _VERSION_TAG_RE.fullmatch(f"v{version}")
    if not match:
        raise ReleaseFactsError(f"unsupported release version {version!r}")
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def _conclusion(value: object, *, completed: bool = False) -> str | None:
    if value is None:
        return "missing" if completed else None
    if not isinstance(value, str):
        raise ReleaseFactsError("workflow/check conclusion must be a string or null")
    normalized = value.strip().lower()
    if not normalized:
        return "missing" if completed else None
    return normalized if normalized in _KNOWN_CONCLUSIONS else "unknown"


def _run_status(value: object) -> str:
    if not isinstance(value, str):
        raise ReleaseFactsError("workflow run status must be a string")
    return _RUN_STATUSES.get(value.strip().lower(), "unknown")


def _check_kind(name: str) -> tuple[bool, bool]:
    lowered = name.lower()
    is_lint = any(word in lowered for word in ("lint", "format", "ruff", "clippy"))
    is_test = (
        any(
            word in lowered
            for word in ("test", "pytest", "smoke", "check", "build-core")
        )
        and not is_lint
    )
    return is_test, is_lint


def _check_facts(name: str, conclusion: str, url: str | None) -> dict[str, Any]:
    is_test, is_lint = _check_kind(name)
    return {
        "name": name,
        "conclusion": conclusion,
        "is_test": is_test,
        "is_lint": is_lint,
        "url": url,
    }


def parse_pypi_inventory(name: str, payload: object) -> dict[str, Any]:
    """Validate the complete PyPI release/file listing for one package."""
    root = _mapping(payload, f"PyPI {name}")
    releases = _mapping(root.get("releases"), f"PyPI {name}.releases")
    files: list[dict[str, Any]] = []
    for version, raw_files in releases.items():
        if not isinstance(version, str) or not version:
            raise ReleaseFactsError(f"PyPI {name} has an invalid release version key")
        for index, raw in enumerate(_list(raw_files, f"PyPI {name}.{version}")):
            item = _mapping(raw, f"PyPI {name}.{version}[{index}]")
            filename = _required_str(
                item, "filename", f"PyPI {name}.{version}[{index}]"
            )
            digests = _mapping(
                item.get("digests"), f"PyPI {name}.{version}[{index}].digests"
            )
            sha256 = _required_str(
                digests, "sha256", f"PyPI {name}.{version}[{index}].digests"
            ).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise ReleaseFactsError(
                    f"PyPI {name}.{version}[{index}] has an invalid SHA-256"
                )
            yanked = item.get("yanked")
            if not isinstance(yanked, bool):
                raise ReleaseFactsError(
                    f"PyPI {name}.{version}[{index}].yanked must be boolean"
                )
            files.append(
                {
                    "filename": filename,
                    "version": version,
                    "sha256": sha256,
                    "yanked": yanked,
                }
            )
    files.sort(key=lambda item: (item["version"], item["filename"]))
    return {"package": name, "files": files}


def _candidate_cli(
    manifest: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    runner: Any = subprocess.run,
    script: Path | None = None,
) -> dict[str, Any]:
    """Run and validate the existing verify/evaluate interface, without policy copies."""
    script_path = script or Path(__file__).with_name("release_candidate")
    candidate_id = _required_str(manifest, "candidate_id", "manifest")
    generation = _integer(manifest.get("generation"), "manifest.generation", minimum=1)
    version = _required_str(manifest, "version", "manifest")
    with tempfile.TemporaryDirectory(prefix="release-watch-candidate-") as directory:
        root = Path(directory)
        manifest_path = root / "manifest.json"
        observations_path = root / "observations.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        observations_path.write_text(
            json.dumps(observations, sort_keys=True), encoding="utf-8"
        )
        base = [sys.executable, str(script_path)]
        try:
            verified = runner(
                [*base, "verify", "--manifest", str(manifest_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            evaluated = runner(
                [
                    *base,
                    "evaluate",
                    "--manifest",
                    str(manifest_path),
                    "--observations",
                    str(observations_path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseFactsError(
                f"candidate evaluator could not run: {exc}"
            ) from exc
    if verified.returncode not in {0, 2}:
        raise ReleaseFactsError(
            f"candidate verify exited {verified.returncode}: "
            f"{(verified.stderr or verified.stdout or '').strip()[:300]}"
        )
    if (
        verified.returncode == 0
        and (verified.stdout or "").strip() != f"OK {candidate_id}"
    ):
        raise ReleaseFactsError(
            "candidate verify returned an unexpected success payload"
        )
    if evaluated.returncode not in {0, 2}:
        raise ReleaseFactsError(
            f"candidate evaluate exited {evaluated.returncode}: "
            f"{(evaluated.stderr or evaluated.stdout or '').strip()[:300]}"
        )
    try:
        report = json.loads(evaluated.stdout or "")
    except json.JSONDecodeError as exc:
        raise ReleaseFactsError(
            f"candidate evaluate returned malformed JSON at byte {exc.pos}"
        ) from exc
    report = _mapping(report, "candidate evaluate result")
    if report.get("candidate_id") != candidate_id:
        raise ReleaseFactsError("candidate evaluate changed the candidate identity")
    if not isinstance(report.get("publishable"), bool):
        raise ReleaseFactsError("candidate evaluate.publishable must be boolean")
    if not isinstance(report.get("rerun_eligible"), bool):
        raise ReleaseFactsError("candidate evaluate.rerun_eligible must be boolean")
    clauses: list[dict[str, Any]] = []
    for index, raw in enumerate(_list(report.get("clauses"), "candidate clauses")):
        clause = _mapping(raw, f"candidate clauses[{index}]")
        clauses.append(
            {
                "name": _required_str(clause, "name", f"candidate clauses[{index}]"),
                "ok": clause.get("ok")
                if isinstance(clause.get("ok"), bool)
                else _raise_clause_bool(index),
                "detail": _required_str(
                    clause, "detail", f"candidate clauses[{index}]"
                ),
            }
        )
    clause_names = [clause["name"] for clause in clauses]
    required_clause_names = {
        "source_and_version_identity_match",
        "public_dependency_contract_satisfied",
        "exact_expected_files_retained_and_hashed",
        "qualification",
        "exercise",
        "no_confirmed_release_veto",
    }
    if len(clause_names) != len(
        set(clause_names)
    ) or not required_clause_names.issubset(clause_names):
        raise ReleaseFactsError(
            "candidate evaluate returned an incomplete or duplicate clause set"
        )
    if evaluated.returncode == 0 and not report["publishable"]:
        raise ReleaseFactsError("candidate evaluator exit code contradicts its result")
    if evaluated.returncode == 2 and report["publishable"]:
        raise ReleaseFactsError("candidate evaluator exit code contradicts its result")
    if verified.returncode == 2 and report["publishable"]:
        raise ReleaseFactsError(
            "candidate verify refusal contradicts a publishable result"
        )
    by_name = {clause["name"]: clause for clause in clauses}
    qualification = by_name.get("qualification", {})
    exercise = by_name.get("exercise", {})
    qualify_detail = str(qualification.get("detail", ""))
    exercise_detail = str(exercise.get("detail", ""))
    qualify_red = (
        qualify_detail
        if not qualification.get("ok") and qualify_detail.startswith("QUALIFY_RED(")
        else None
    )
    exercise_red = (
        exercise_detail
        if not exercise.get("ok") and exercise_detail.startswith("exercise red:")
        else None
    )
    malformed_markers = (
        "malformed",
        "unverifiable",
        "disagrees",
        "incomplete",
        "ambiguous",
        "does not match",
        "history omits",
    )
    evidence_mismatch = any(
        not clause["ok"]
        and any(token in clause["detail"].lower() for token in malformed_markers)
        for clause in (qualification, exercise)
    )
    return {
        "candidate_id": candidate_id,
        "generation": generation,
        "version": version,
        "publishable": report["publishable"],
        "rerun_eligible": report["rerun_eligible"],
        "rerun_reason": report.get("rerun_reason")
        if isinstance(report.get("rerun_reason"), str)
        else _raise_rerun_reason(),
        "clauses": clauses,
        "active_veto": not by_name.get("no_confirmed_release_veto", {}).get("ok", True),
        "qualify_red": qualify_red,
        "exercise_red": exercise_red,
        "evidence_mismatch": evidence_mismatch,
        "manifest_valid": verified.returncode == 0,
    }


def _raise_clause_bool(index: int) -> Any:
    raise ReleaseFactsError(f"candidate clauses[{index}].ok must be boolean")


def _raise_rerun_reason() -> Any:
    raise ReleaseFactsError("candidate evaluate.rerun_reason must be a string")


class ReleaseFactsReader:
    """Reconstruct train facts from read-only GitHub and PyPI APIs per tick."""

    def __init__(
        self,
        repo: str = DEFAULT_REPO,
        *,
        github: Any | None = None,
        pypi: Any | None = None,
        candidate_runner: Any = subprocess.run,
        candidate_script: Path | None = None,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("repo must be owner/repository")
        self.repo = repo
        self.github = github or GithubTransport(repo)
        self.pypi = pypi or PypiTransport()
        self.candidate_runner = candidate_runner
        self.candidate_script = candidate_script

    def _api(self, path: str, params: dict[str, object] | None = None) -> object:
        base = f"repos/{self.repo}"
        # GitHub has no route for the trailing slash, so the repository
        # metadata read must not append one.
        return self.github.json(base if not path else f"{base}/{path}", params=params)

    def _pages(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
        collection: str | None = None,
    ) -> list[Any]:
        page_payloads = self.github.pages(f"repos/{self.repo}/{path}", params=params)
        if not page_payloads:
            return []
        if isinstance(page_payloads[0], list):
            if collection is not None:
                raise ReleaseFactsError(f"{path} unexpectedly returned list pages")
            return [item for page in page_payloads for item in page]
        if collection is None:
            # Array endpoints (pulls, tags, releases) arrive flattened by
            # the transport: every item is already a row. Page objects
            # without a collection stay a caller error downstream, where
            # row validation still fails closed.
            return [
                _mapping(item, f"{path}[{index}]")
                for index, item in enumerate(page_payloads)
            ]
        rows: list[Any] = []
        for index, payload in enumerate(page_payloads):
            page = _mapping(payload, f"{path} page[{index}]")
            rows.extend(
                _list(page.get(collection), f"{path} page[{index}].{collection}")
            )
        return rows

    def read_repository(self) -> dict[str, str]:
        """Read repository identity and default branch."""
        payload = _mapping(self._api(""), "repository")
        owner_obj = _mapping(payload.get("owner"), "repository.owner")
        owner = _required_str(owner_obj, "login", "repository.owner")
        name = _required_str(payload, "name", "repository")
        branch = _required_str(payload, "default_branch", "repository")
        return {"owner": owner, "name": name, "default_branch": branch}

    def _required_checks(self) -> tuple[list[dict[str, str]], bool]:
        source = f"repos/{self.repo}/branches/master/protection/required_status_checks"
        try:
            payload = _mapping(self.github.json(source), "required status checks")
        except Exception:
            # An unprotected branch or a credential without this read permission
            # cannot establish the authoritative expected set.
            return [], False
        names: set[str] = set()
        for context in _list(payload.get("contexts", []), "required checks.contexts"):
            if not isinstance(context, str) or not context.strip():
                raise ReleaseFactsError(
                    "required checks.contexts contains an invalid name"
                )
            names.add(context.strip())
        for index, raw in enumerate(
            _list(payload.get("checks", []), "required checks.checks")
        ):
            item = _mapping(raw, f"required checks.checks[{index}]")
            names.add(
                _required_str(item, "context", f"required checks.checks[{index}]")
            )
        ordered = [
            {"name": name, "source": "branch protection"} for name in sorted(names)
        ]
        return ordered, bool(ordered)

    def _git_file(self, path: str, ref: str) -> str:
        payload = _mapping(
            self._api(f"contents/{path}", {"ref": ref}), f"contents {path}@{ref}"
        )
        if payload.get("encoding") != "base64":
            raise ReleaseFactsError(f"contents {path}@{ref} is not base64 encoded")
        content = _required_str(payload, "content", f"contents {path}@{ref}")
        try:
            # The contents API wraps base64 at 60 columns; strip the
            # wrapping before the strict decode.
            return base64.b64decode("".join(content.split()), validate=True).decode(
                "utf-8"
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseFactsError(f"contents {path}@{ref} is malformed") from exc

    def read_source_pin(self, ref: str) -> str:
        """Read the sase-core source pin at a remote commit SHA.

        The ref is always a remote identity (a release PR head, a tagged
        release, or master HEAD); the local checkout's pin is never used.
        """
        return self._source_pin(ref)

    def read_ref_sha(self, ref: str = "heads/master") -> str:
        """Read the commit SHA a remote git ref points at."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", ref):
            raise ValueError("ref must look like heads/master")
        payload = _mapping(self._api(f"git/ref/{ref}"), f"ref {ref}")
        target = _mapping(payload.get("object"), f"ref {ref}.object")
        sha = _required_str(target, "sha", f"ref {ref}").lower()
        if not _SHA_RE.fullmatch(sha):
            raise ReleaseFactsError(f"ref {ref} SHA is invalid")
        return sha

    def read_jobs(self, run_id: str | int, attempt: int) -> list[dict[str, Any]]:
        """Read the wire-shaped jobs for one workflow run attempt."""
        if isinstance(run_id, bool) or not isinstance(run_id, (str, int)):
            raise ValueError("run_id must be a string or integer")
        if not str(run_id).strip():
            raise ValueError("run_id must be non-empty")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise ValueError("attempt must be an integer >= 1")
        return self._jobs(str(run_id).strip(), attempt)

    def _source_pin(self, ref: str) -> str:
        text = self._git_file("sase-core-revision.txt", ref)
        pin = text.strip().splitlines()[0].strip() if text.strip() else ""
        if not _PIN_RE.fullmatch(pin):
            raise ReleaseFactsError(f"source pin at {ref} is invalid")
        return pin.lower()

    def _core_pin(self, ref: str) -> str | None:
        text = self._git_file("pyproject.toml", ref)
        match = _CORE_PIN_RE.search(text)
        return match.group(1) if match else None

    def _workflow_run_rows(
        self,
        workflow: str,
        *,
        since: datetime,
        until: datetime,
        branch: str | None = None,
    ) -> list[dict[str, Any]]:
        start, end = _bounds(since, until)
        created = f"{_iso(start)}..{_iso(end)}"
        params: dict[str, object] = {"created": created}
        if branch:
            params["branch"] = branch
        return self._pages(
            f"actions/workflows/{workflow}/runs",
            params=params,
            collection="workflow_runs",
        )

    def _jobs(self, run_id: str, attempt: int) -> list[dict[str, Any]]:
        rows = self._pages(
            f"actions/runs/{run_id}/attempts/{attempt}/jobs",
            collection="jobs",
        )
        jobs = []
        for index, raw in enumerate(rows):
            item = _mapping(raw, f"run {run_id} jobs[{index}]")
            job_id = item.get("id")
            if isinstance(job_id, bool) or not isinstance(job_id, (str, int)):
                raise ReleaseFactsError(f"run {run_id} jobs[{index}].id is invalid")
            name = _required_str(item, "name", f"run {run_id} jobs[{index}]")
            conclusion = _conclusion(
                item.get("conclusion"),
                completed=item.get("status") == "completed",
            )
            is_test, is_lint = _check_kind(name)
            jobs.append(
                {
                    "id": str(job_id),
                    "name": name,
                    "conclusion": conclusion,
                    "is_test": is_test,
                    "is_lint": is_lint,
                    "attempt": attempt,
                }
            )
        jobs.sort(key=lambda item: (item["name"], item["id"]))
        return jobs

    def _run_wire(
        self, raw: object, workflow: str, *, with_jobs: bool = False
    ) -> dict[str, Any]:
        item = _mapping(raw, f"{workflow} run")
        run_id = _integer(item.get("id"), f"{workflow} run.id", minimum=1)
        attempt = _integer(
            item.get("run_attempt", 1), f"run {run_id}.run_attempt", minimum=1
        )
        sha = _required_str(item, "head_sha", f"run {run_id}").lower()
        if not _SHA_RE.fullmatch(sha):
            raise ReleaseFactsError(f"run {run_id}.head_sha is invalid")
        ref_name = _required_str(item, "head_branch", f"run {run_id}")
        status = _run_status(item.get("status"))
        conclusion = _conclusion(
            item.get("conclusion"), completed=status == "completed"
        )
        created = _iso(_utc(item.get("created_at"), f"run {run_id}.created_at"))
        updated = _iso(_utc(item.get("updated_at"), f"run {run_id}.updated_at"))
        started_raw = item.get("run_started_at")
        started = (
            _iso(_utc(started_raw, f"run {run_id}.run_started_at"))
            if started_raw
            else None
        )
        event = item.get("event")
        if event is not None and not isinstance(event, str):
            raise ReleaseFactsError(f"run {run_id}.event must be a string or null")
        url = _required_str(item, "html_url", f"run {run_id}")
        return {
            "workflow": workflow,
            "run_id": str(run_id),
            "attempt": attempt,
            "ref_name": ref_name,
            "sha": sha,
            "status": status,
            "conclusion": conclusion,
            "jobs": self._jobs(str(run_id), attempt) if with_jobs else [],
            "started_at": started,
            "updated_at": updated,
            "event": event,
            "url": url,
            "created_at": created,
        }

    def read_runs(
        self,
        workflow: str,
        *,
        since: datetime | str,
        until: datetime | str,
        branch: str | None = None,
        include_jobs: bool = False,
    ) -> list[dict[str, Any]]:
        """Read bounded workflow history; pagination and both bounds are required."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.yml", workflow):
            raise ValueError("workflow must be a workflow filename")
        start, end = _bounds(since, until)
        raw = self._workflow_run_rows(workflow, since=start, until=end, branch=branch)
        runs = [self._run_wire(row, workflow, with_jobs=include_jobs) for row in raw]
        runs = [
            run
            for run in runs
            if start <= _utc(run["created_at"], "run.created_at") <= end
        ]
        return sorted(
            runs,
            key=lambda item: (item["created_at"], item["attempt"], item["run_id"]),
            reverse=True,
        )

    def read_runs_for_sha(
        self,
        workflow: str,
        sha: str,
        *,
        branch: str | None = None,
        include_jobs: bool = True,
    ) -> list[dict[str, Any]]:
        """Read workflow attempts bound to one exact commit SHA."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.yml", workflow):
            raise ValueError("workflow must be a workflow filename")
        target = sha.strip().lower()
        if not _SHA_RE.fullmatch(target):
            raise ValueError("sha must be a full git commit SHA")
        params: dict[str, object] = {"head_sha": target}
        if branch:
            params["branch"] = branch
        rows = self._pages(
            f"actions/workflows/{workflow}/runs",
            params=params,
            collection="workflow_runs",
        )
        runs = [
            self._run_wire(row, workflow, with_jobs=include_jobs)
            for row in rows
            if str(row.get("head_sha") or "").lower() == target
        ]
        return sorted(
            runs,
            key=lambda item: (item["created_at"], item["attempt"], item["run_id"]),
            reverse=True,
        )

    def read_commits(
        self,
        *,
        since: datetime | str,
        until: datetime | str,
        branch: str = "master",
        path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read commits reachable from a branch in an explicit time interval.

        ``path`` narrows the history to commits that changed one repository
        path, as supported by GitHub's commits endpoint.
        """
        start, end = _bounds(since, until)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", branch):
            raise ValueError("branch must be a git ref name")
        params: dict[str, object] = {
            "sha": branch,
            "since": _iso(start),
            "until": _iso(end),
        }
        if path:
            params["path"] = path
        rows = self._pages("commits", params=params)
        found: list[dict[str, Any]] = []
        for index, raw in enumerate(rows):
            item = _mapping(raw, f"commit[{index}]")
            sha = _required_str(item, "sha", f"commit[{index}]").lower()
            if not _SHA_RE.fullmatch(sha):
                raise ReleaseFactsError(f"commit[{index}].sha is invalid")
            commit = _mapping(item.get("commit"), f"commit {sha}.commit")
            committer = _mapping(commit.get("committer"), f"commit {sha}.committer")
            committed_at = _iso(
                _utc(committer.get("date"), f"commit {sha}.committer.date")
            )
            parents: list[str] = []
            for parent_index, parent_raw in enumerate(
                _list(item.get("parents"), f"commit {sha}.parents")
            ):
                parent = _mapping(parent_raw, f"commit {sha}.parents[{parent_index}]")
                parent_sha = _required_str(
                    parent, "sha", f"commit {sha}.parents[{parent_index}]"
                ).lower()
                if not _SHA_RE.fullmatch(parent_sha):
                    raise ReleaseFactsError(
                        f"commit {sha}.parents[{parent_index}].sha is invalid"
                    )
                parents.append(parent_sha)
            if start <= _utc(committed_at, f"commit {sha}.committed_at") <= end:
                found.append(
                    {
                        "sha": sha,
                        "committed_at": committed_at,
                        "parents": parents,
                    }
                )
        return sorted(found, key=lambda item: item["committed_at"])

    def read_commits_between_refs(
        self,
        base: str,
        head: str,
        *,
        since: datetime | str,
        until: datetime | str,
    ) -> list[dict[str, Any]]:
        """Read date-bounded commits reachable from head but not base.

        The compare endpoint caps its commit list at 250 entries. Querying each
        ref through the paginated commits endpoint and subtracting the base's
        reachable SHAs preserves exact range membership for the requested
        time window without that cap.
        """
        for name, ref in (("base", base), ("head", head)):
            stripped = ref.strip()
            if not (
                _SHA_RE.fullmatch(stripped.lower())
                or _VERSION_TAG_RE.fullmatch(stripped)
            ):
                raise ValueError(f"{name} must be a full SHA or stable vX.Y.Z tag")
        base_rows = self.read_commits(since=since, until=until, branch=base.strip())
        base_shas = {row["sha"] for row in base_rows}
        head_rows = self.read_commits(since=since, until=until, branch=head.strip())
        return [
            {"sha": row["sha"], "committed_at": row["committed_at"]}
            for row in head_rows
            if row["sha"] not in base_shas
        ]

    def _release_rows(self) -> list[dict[str, Any]]:
        return [
            _mapping(row, f"release[{index}]")
            for index, row in enumerate(self._pages("releases"))
        ]

    def _release_wire(self, raw: dict[str, Any]) -> tuple[dict[str, Any], datetime]:
        tag = _required_str(raw, "tag_name", "release")
        draft = raw.get("draft")
        if not isinstance(draft, bool):
            raise ReleaseFactsError(f"release {tag}.draft must be boolean")
        name = raw.get("name")
        if name is None:
            name = tag
        if not isinstance(name, str):
            raise ReleaseFactsError(f"release {tag}.name must be a string")
        assets: list[dict[str, Any]] = []
        for index, value in enumerate(
            _list(raw.get("assets"), f"release {tag}.assets")
        ):
            asset = _mapping(value, f"release {tag}.assets[{index}]")
            asset_name = _required_str(asset, "name", f"release {tag}.assets[{index}]")
            asset_id = _integer(
                asset.get("id"), f"release {tag}.assets[{index}].id", minimum=1
            )
            match = _OBSERVATION_RE.fullmatch(asset_name)
            if match:
                kind = match.group("kind")
                generation = int(match.group("generation"))
            elif asset_name == "candidate-manifest.json":
                kind, generation = "manifest", 0
            else:
                kind, generation = "other", 0
            assets.append(
                {
                    "name": asset_name,
                    "kind": kind,
                    "generation": generation,
                    "id": asset_id,
                }
            )
        assets.sort(key=lambda item: item["name"])
        created_raw = raw.get("created_at") or raw.get("published_at")
        created = _utc(created_raw, f"release {tag}.created_at")
        url = _required_str(raw, "html_url", f"release {tag}")
        return (
            {"tag": tag, "draft": draft, "name": name, "assets": assets, "url": url},
            created,
        )

    def read_releases(
        self, *, since: datetime | str, until: datetime | str
    ) -> list[dict[str, Any]]:
        """Read releases created in an explicit UTC interval, including drafts."""
        start, end = _bounds(since, until)
        found = []
        for raw in self._release_rows():
            release, created = self._release_wire(raw)
            if start <= created <= end:
                found.append(release)
        return sorted(found, key=lambda item: item["tag"])

    def read_release_history(self) -> list[dict[str, Any]]:
        """Read GitHub release records with timestamps and release notes."""
        found: list[dict[str, Any]] = []
        for raw in self._release_rows():
            release, created = self._release_wire(raw)
            published = raw.get("published_at")
            if published is not None:
                published = _iso(
                    _utc(published, f"release {release['tag']}.published_at")
                )
            body = raw.get("body")
            if body is None:
                body = ""
            if not isinstance(body, str):
                raise ReleaseFactsError(f"release {release['tag']}.body must be text")
            found.append(
                {
                    **release,
                    "created_at": _iso(created),
                    "published_at": published,
                    "body": body,
                }
            )
        return sorted(found, key=lambda item: (item["created_at"], item["tag"]))

    def _all_release_records(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return [(self._release_wire(raw)[0], raw) for raw in self._release_rows()]

    def _tag_sha(self, name: str, payload: object) -> str:
        seen: set[str] = set()
        obj = _mapping(payload, f"tag ref {name}")
        target = _mapping(obj.get("object"), f"tag ref {name}.object")
        for _depth in range(5):
            sha = _required_str(target, "sha", f"tag {name} object").lower()
            if not _SHA_RE.fullmatch(sha) or sha in seen:
                raise ReleaseFactsError(f"tag {name} has an invalid or cyclic target")
            seen.add(sha)
            kind = _required_str(target, "type", f"tag {name} object")
            if kind == "commit":
                return sha
            if kind != "tag":
                raise ReleaseFactsError(
                    f"tag {name} points to unsupported object type {kind}"
                )
            tag_obj = _mapping(self._api(f"git/tags/{sha}"), f"annotated tag {name}")
            target = _mapping(tag_obj.get("object"), f"annotated tag {name}.object")
        raise ReleaseFactsError(f"tag {name} nesting exceeds the supported depth")

    def _tag_refs(self) -> list[tuple[str, str]]:
        rows = self._pages("git/matching-refs/tags/v")
        refs: list[tuple[str, str]] = []
        for index, raw in enumerate(rows):
            item = _mapping(raw, f"tag ref[{index}]")
            ref = _required_str(item, "ref", f"tag ref[{index}]")
            prefix = "refs/tags/"
            if not ref.startswith(prefix):
                raise ReleaseFactsError(f"tag ref has unexpected name {ref!r}")
            name = ref[len(prefix) :]
            if _VERSION_TAG_RE.fullmatch(name):
                refs.append((name, self._tag_sha(name, item)))
        refs.sort(key=lambda item: _version_key(item[0][1:]))
        return refs

    def read_tags(
        self, *, since: datetime | str, until: datetime | str
    ) -> list[dict[str, Any]]:
        """Read stable tags whose peeled commit dates fall in the UTC interval.

        Git refs have no creation timestamp. The bounded history view uses the
        peeled commit's committer timestamp and still returns the immutable tag
        name/SHA pair used by the policy snapshot.
        """
        start, end = _bounds(since, until)
        releases = {wire["tag"]: wire for wire, _raw in self._all_release_records()}
        result = []
        for name, sha in self._tag_refs():
            commit = _mapping(self._api(f"commits/{sha}"), f"tag {name} commit")
            commit_info = _mapping(commit.get("commit"), f"tag {name} commit.commit")
            committer = _mapping(
                commit_info.get("committer"), f"tag {name} commit.committer"
            )
            committed_at = _utc(committer.get("date"), f"tag {name} committer.date")
            if not start <= committed_at <= end:
                continue
            result.append(
                {
                    "name": name,
                    "peeled_sha": sha,
                    "committed_at": _iso(committed_at),
                    "has_manifest": any(
                        asset["name"] == "candidate-manifest.json"
                        for asset in releases.get(name, {}).get("assets", [])
                    ),
                }
            )
        return result

    def _pypi_payloads(self) -> dict[str, dict[str, Any]]:
        sase = parse_pypi_inventory("sase", self.pypi.project("sase"))
        core = parse_pypi_inventory("sase-core-rs", self.pypi.project("sase-core-rs"))
        return {"sase": sase, "core": core}

    def read_publication_history(
        self,
        *,
        since: datetime | str,
        until: datetime | str,
    ) -> list[dict[str, Any]]:
        """Read PyPI file publication history in an explicit UTC interval."""
        start, end = _bounds(since, until)
        history: list[dict[str, Any]] = []
        for package in ("sase", "sase-core-rs"):
            payload = _mapping(self.pypi.project(package), f"PyPI {package}")
            releases = _mapping(payload.get("releases"), f"PyPI {package}.releases")
            for version, raw_files in releases.items():
                for index, raw in enumerate(
                    _list(raw_files, f"PyPI {package}.{version}")
                ):
                    item = _mapping(raw, f"PyPI {package}.{version}[{index}]")
                    uploaded = _utc(
                        item.get("upload_time_iso_8601"),
                        f"PyPI {package}.{version}[{index}].upload_time_iso_8601",
                    )
                    if not (start <= uploaded <= end):
                        continue
                    file_record = parse_pypi_inventory(
                        package,
                        {"releases": {version: [item]}},
                    )["files"][0]
                    history.append(
                        {
                            "package": package,
                            **file_record,
                            "uploaded_at": _iso(uploaded),
                        }
                    )
        return sorted(
            history,
            key=lambda item: (item["uploaded_at"], item["package"], item["filename"]),
        )

    def _check_rows(self, sha: str) -> list[dict[str, Any]]:
        rows = self._pages(
            f"commits/{sha}/check-runs",
            params={"filter": "all"},
            collection="check_runs",
        )
        found: list[dict[str, Any]] = []
        for index, raw in enumerate(rows):
            check = _mapping(raw, f"check-runs[{index}]")
            name = _required_str(check, "name", f"check-runs[{index}]")
            status = check.get("status")
            if not isinstance(status, str):
                raise ReleaseFactsError(f"check-runs[{index}].status must be a string")
            conclusion = (
                _conclusion(
                    check.get("conclusion"), completed=status.lower() == "completed"
                )
                or "unknown"
            )
            if check.get("head_sha") and str(check["head_sha"]).lower() != sha:
                # A check endpoint must be bound to the exact requested commit.
                continue
            html_url = check.get("html_url")
            found.append(
                {
                    **_check_facts(
                        name,
                        conclusion,
                        html_url if isinstance(html_url, str) else None,
                    ),
                    "updated_at": _iso(
                        _utc(
                            check.get("completed_at") or check.get("started_at"),
                            f"check {name}.timestamp",
                        )
                    )
                    if check.get("completed_at") or check.get("started_at")
                    else "",
                    "id": _integer(check.get("id"), f"check {name}.id", minimum=1),
                }
            )
        status_payload = _mapping(
            self._api(f"commits/{sha}/status"), f"commit {sha} status"
        )
        for index, raw in enumerate(
            _list(status_payload.get("statuses"), f"commit {sha}.statuses")
        ):
            status = _mapping(raw, f"commit {sha}.statuses[{index}]")
            name = _required_str(status, "context", f"commit {sha}.statuses[{index}]")
            state = _required_str(
                status, "state", f"commit {sha}.statuses[{index}]"
            ).lower()
            conclusion = {
                "success": "success",
                "failure": "failure",
                "error": "failure",
                "pending": "unknown",
            }.get(state, "unknown")
            target_url = status.get("target_url")
            found.append(
                {
                    **_check_facts(
                        name,
                        conclusion,
                        target_url if isinstance(target_url, str) else None,
                    ),
                    "updated_at": _iso(
                        _utc(status.get("updated_at"), f"status {name}.updated_at")
                    ),
                    "id": _integer(status.get("id"), f"status {name}.id", minimum=0),
                }
            )
        newest: dict[str, dict[str, Any]] = {}
        for check in found:
            previous = newest.get(check["name"])
            if previous is None or (check["updated_at"], check["id"]) > (
                previous["updated_at"],
                previous["id"],
            ):
                newest[check["name"]] = check
        return [newest[name] for name in sorted(newest)]

    def _expected_checks(self) -> tuple[list[dict[str, str]], bool]:
        return self._required_checks()

    def _checks_for_head(
        self, sha: str, expected: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        checks = self._check_rows(sha)
        by_name = {check["name"]: check for check in checks}
        for required in expected:
            name = required["name"]
            if name not in by_name:
                by_name[name] = _check_facts(name, "missing", None)
        return [
            {
                key: value
                for key, value in by_name[name].items()
                if key in {"name", "conclusion", "is_test", "is_lint", "url"}
            }
            for name in sorted(by_name)
        ]

    def _master_facts(self, observed_at: datetime) -> dict[str, Any]:
        ref = _mapping(self._api("git/ref/heads/master"), "master ref")
        target = _mapping(ref.get("object"), "master ref.object")
        sha = _required_str(target, "sha", "master ref").lower()
        if not _SHA_RE.fullmatch(sha):
            raise ReleaseFactsError("master ref SHA is invalid")
        expected, expected_readable = self._expected_checks()
        raw_runs = self._workflow_run_rows(
            MASTER_GATE_WORKFLOW,
            since=observed_at - HISTORY_LOOKBACK,
            until=observed_at + timedelta(minutes=1),
            branch="master",
        )
        matching = [
            row for row in raw_runs if str(row.get("head_sha", "")).lower() == sha
        ]
        gate_run = None
        if matching:
            matching.sort(
                key=lambda row: (
                    _integer(
                        row.get("run_attempt", 1), "master gate run_attempt", minimum=1
                    ),
                    _utc(row.get("updated_at"), "master gate updated_at"),
                ),
                reverse=True,
            )
            gate_run = self._run_wire(matching[0], MASTER_GATE_WORKFLOW, with_jobs=True)
            gate_run.pop("created_at", None)
        return {
            "sha": sha,
            "gate_run": gate_run,
            "expected_required_checks": expected,
            "expected_checks_source": "branch protection",
            "expected_checks_readable": expected_readable,
        }

    def _pull_rows(self) -> list[dict[str, Any]]:
        return [
            _mapping(row, f"pull request[{index}]")
            for index, row in enumerate(
                self._pages(
                    "pulls",
                    params={"state": "all", "sort": "updated", "direction": "desc"},
                )
            )
        ]

    @staticmethod
    def _release_pr_version(pr: dict[str, Any]) -> str | None:
        head = pr.get("head")
        head_ref = head.get("ref") if isinstance(head, dict) else ""
        title = pr.get("title")
        text = f"{head_ref} {title}" if isinstance(title, str) else str(head_ref)
        if "release" not in text.lower() and not str(head_ref).startswith(
            "release-please"
        ):
            return None
        match = _VERSION_RE.search(text)
        return match.group(1) if match else None

    def _release_pr_context(
        self,
        master: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        pull_rows = self._pull_rows()
        candidates = [row for row in pull_rows if self._release_pr_version(row)]
        open_candidates = [row for row in candidates if row.get("state") == "open"]
        if len(open_candidates) > 1:
            numbers = sorted(
                _integer(row.get("number"), "release PR number", minimum=1)
                for row in open_candidates
            )
            raise ReleaseFactsError(f"multiple open release PRs: {numbers}")
        if open_candidates:
            selected = open_candidates[0]
        else:
            merged = [row for row in candidates if row.get("merged_at")]
            merged.sort(
                key=lambda row: _utc(row["merged_at"], "release PR merged_at"),
                reverse=True,
            )
            selected = merged[0] if merged else None
        merge_history = []
        for row in candidates:
            merged_at = row.get("merged_at")
            if not merged_at:
                continue
            number = _integer(row.get("number"), "release PR number", minimum=1)
            head = _mapping(row.get("head"), f"release PR {number}.head")
            head_sha = _required_str(head, "sha", f"release PR {number}.head").lower()
            if not _SHA_RE.fullmatch(head_sha):
                raise ReleaseFactsError(f"release PR {number} head SHA is invalid")
            merge_history.append(
                {
                    "pr_number": number,
                    "head_sha": head_sha,
                    "merged_at": _iso(
                        _utc(merged_at, f"release PR {number}.merged_at")
                    ),
                    "candidate_id": None,
                    "abandoned_after": False,
                }
            )
        merge_history.sort(key=lambda item: item["merged_at"])
        if selected is None:
            return None, merge_history
        number = _integer(selected.get("number"), "release PR number", minimum=1)
        head = _mapping(selected.get("head"), f"release PR {number}.head")
        head_sha = _required_str(head, "sha", f"release PR {number}.head").lower()
        if not _SHA_RE.fullmatch(head_sha):
            raise ReleaseFactsError(f"release PR {number} head SHA is invalid")
        source_pin = self._source_pin(head_sha)
        exact_pin = self._core_pin(head_sha)
        stale_compare = _mapping(
            self._api(f"compare/{head_sha}...{master['sha']}"),
            f"release PR {number} versus master",
        )
        compare_status = _required_str(
            stale_compare, "status", "PR/master compare"
        ).lower()
        if compare_status not in {"ahead", "behind", "identical", "diverged"}:
            raise ReleaseFactsError(
                f"PR/master compare has unknown status {compare_status!r}"
            )
        # Read both values at the relevant Git identities; local files are
        # never substituted for the PR or master revision.
        master_pin = self._source_pin(master["sha"])
        master_core_pin = self._core_pin(master["sha"])
        labels = []
        for index, raw in enumerate(
            _list(selected.get("labels"), f"release PR {number}.labels")
        ):
            label = _mapping(raw, f"release PR {number}.labels[{index}]")
            labels.append(
                _required_str(label, "name", f"release PR {number}.labels[{index}]")
            )
        expected = master["expected_required_checks"]
        checks = self._checks_for_head(head_sha, expected)
        core_smoke = next(
            (
                check
                for check in checks
                if "release-core-floor-smoke" in check["name"].lower()
            ),
            None,
        )
        merged_at = selected.get("merged_at")
        if merged_at is not None:
            merged_at = _iso(_utc(merged_at, f"release PR {number}.merged_at"))
        url = _required_str(selected, "html_url", f"release PR {number}")
        pr_history = [item for item in merge_history if item["pr_number"] == number]
        return (
            {
                "number": number,
                "head_sha": head_sha,
                "source_pin": source_pin,
                "exact_public_core_pin": exact_pin,
                "labels": sorted(set(labels)),
                "checks": checks,
                "merge_history": pr_history,
                "stale_head": compare_status in {"ahead", "diverged"},
                "pin_changed": source_pin != master_pin or exact_pin != master_core_pin,
                "merged": bool(merged_at),
                "merged_at": merged_at,
                "url": url,
                "core_smoke": core_smoke,
            },
            merge_history,
        )

    def _workflows(
        self, observed_at: datetime, tags: list[dict[str, Any]]
    ) -> dict[str, Any]:
        since = observed_at - HISTORY_LOOKBACK
        until = observed_at + timedelta(minutes=1)
        release_runs = self.read_runs(RELEASE_WORKFLOW, since=since, until=until)
        publish_runs = self.read_runs(PUBLISH_WORKFLOW, since=since, until=until)
        tagged_shas = {tag["name"]: tag["peeled_sha"] for tag in tags}
        relevant_release = []
        for run in release_runs:
            if run["ref_name"] in tagged_shas or run["status"] in {
                "queued",
                "pending",
                "in_progress",
                "waiting",
                "requested",
                "waiting_for_deploy",
            }:
                match = (
                    run["ref_name"] in tagged_shas
                    and run["sha"] == tagged_shas[run["ref_name"]]
                )
                # Matching tagged runs and all live runs carry attempt-aware jobs.
                if match or run["status"] != "completed":
                    run["jobs"] = self._jobs(run["run_id"], run["attempt"])
                relevant_release.append(run)
        relevant_publish = []
        for run in publish_runs:
            if run["status"] != "completed":
                run["jobs"] = self._jobs(run["run_id"], run["attempt"])
            relevant_publish.append(run)
        for run in (*relevant_release, *relevant_publish):
            run.pop("created_at", None)
        return {
            "release_yml": relevant_release,
            "publish_yml": relevant_publish,
        }

    @staticmethod
    def _release_version(tag: str) -> str | None:
        match = _VERSION_TAG_RE.fullmatch(tag)
        return match.group("version") if match else None

    def _load_manifest_bundle(
        self,
        release_wire: dict[str, Any],
        release_raw: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool, bool]:
        tag = release_wire["tag"]
        assets_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for asset in release_wire["assets"]:
            assets_by_name[asset["name"]].append(asset)
        manifest_assets = assets_by_name.get("candidate-manifest.json", [])
        if not manifest_assets:
            return None, [], False, False
        manifest_mismatch = len(manifest_assets) != 1
        raw_asset = next(
            item
            for item in _list(release_raw.get("assets"), f"release {tag}.assets")
            if isinstance(item, dict) and item.get("name") == "candidate-manifest.json"
        )
        try:
            manifest_payload = self.github.asset_json(
                _integer(
                    raw_asset.get("id"), f"release {tag} manifest asset id", minimum=1
                ),
                source=f"release {tag} candidate manifest",
            )
        except ReleaseTransportError as exc:
            if "not valid JSON" in str(exc):
                return None, [], True, False
            raise
        evidence_mismatch = False
        try:
            manifest = _mapping(manifest_payload, f"release {tag} candidate manifest")
            if not isinstance(manifest.get("observations"), list):
                raise ReleaseFactsError(
                    "candidate manifest observations must be a list"
                )
            generation = _integer(
                manifest.get("generation"), "manifest.generation", minimum=1
            )
        except ReleaseFactsError:
            return None, [], True, False
        manifest_dists = manifest.get("dists")
        if not isinstance(manifest_dists, list):
            manifest_dists = []
        for asset in release_wire["assets"]:
            if asset["name"] == "candidate-manifest.json":
                asset["generation"] = generation
            elif any(
                isinstance(dist, dict) and dist.get("filename") == asset["name"]
                for dist in manifest_dists
            ):
                asset["kind"] = "dist"
                asset["generation"] = generation
        observations: list[dict[str, Any]] = []
        for asset_name, duplicate_assets in sorted(assets_by_name.items()):
            match = _OBSERVATION_RE.fullmatch(asset_name)
            if match is None:
                continue
            if len(duplicate_assets) != 1:
                evidence_mismatch = True
                continue
            raw_observation = next(
                item
                for item in _list(release_raw.get("assets"), f"release {tag}.assets")
                if isinstance(item, dict) and item.get("name") == asset_name
            )
            try:
                try:
                    observation_payload = self.github.asset_json(
                        _integer(
                            raw_observation.get("id"),
                            f"release {tag} asset id",
                            minimum=1,
                        ),
                        source=f"release {tag} observation {asset_name}",
                    )
                except ReleaseTransportError as exc:
                    if "not valid JSON" in str(exc):
                        evidence_mismatch = True
                        continue
                    raise
                observation = _mapping(
                    observation_payload, f"release {tag} observation {asset_name}"
                )
                expected_identity = (
                    int(match.group("generation")),
                    match.group("kind"),
                    int(match.group("run_id")),
                    int(match.group("attempt")),
                )
                actual_identity = (
                    observation.get("generation"),
                    observation.get("kind"),
                    observation.get("run_id"),
                    observation.get("attempt"),
                )
                if (
                    actual_identity != expected_identity
                    or observation.get("asset") != asset_name
                ):
                    evidence_mismatch = True
                    continue
                if expected_identity[0] > generation:
                    evidence_mismatch = True
                    continue
                if expected_identity[0] == generation and observation.get(
                    "candidate_id"
                ) != manifest.get("candidate_id"):
                    evidence_mismatch = True
                    continue
                observations.append(observation)
            except ReleaseTransportError:
                raise
            except ReleaseFactsError:
                evidence_mismatch = True
        observations.sort(
            key=lambda item: (
                item.get("kind", ""),
                item.get("run_id", 0),
                item.get("attempt", 0),
            )
        )
        return manifest, observations, manifest_mismatch, evidence_mismatch

    def _fact_eval(
        self,
        manifest: dict[str, Any],
        observations: list[dict[str, Any]],
        release_wire: dict[str, Any],
        peeled_sha: str,
        observation_at_tag: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], bool, bool, bool]:
        candidate_id = manifest.get("candidate_id")
        generation = manifest.get("generation")
        version = manifest.get("version")
        tag = release_wire["tag"]
        manifest_mismatch = (
            not isinstance(candidate_id, str)
            or not candidate_id
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
            or version != self._release_version(tag)
            or manifest.get("tag") not in {tag, f"refs/tags/{tag}"}
            or str(manifest.get("sha", "")).lower() != peeled_sha
        )
        result = _candidate_cli(
            manifest,
            observations,
            runner=self.candidate_runner,
            script=self.candidate_script,
        )
        manifest_mismatch = manifest_mismatch or not result["manifest_valid"]
        assets = {asset["name"] for asset in release_wire["assets"]}
        dist_assets_missing = False
        dists = manifest.get("dists")
        if not isinstance(dists, list):
            manifest_mismatch = True
            dists = []
        for index, raw_dist in enumerate(dists):
            dist = _mapping(raw_dist, f"manifest.dists[{index}]")
            locator = dist.get("asset")
            filename = dist.get("filename")
            if not isinstance(locator, str) or not isinstance(filename, str):
                manifest_mismatch = True
                continue
            if locator.startswith(f"gh-release:{tag}/"):
                name = locator.split("/", 1)[1]
                if name != filename or name not in assets:
                    dist_assets_missing = True
        tag_runs = [
            run
            for run in observation_at_tag
            if run.get("ref_name") == tag and run.get("sha", "").lower() == peeled_sha
        ]
        workflow_broken = False
        if not tag_runs:
            try:
                self._git_file(".github/workflows/release.yml", tag)
            except ReleaseTransportError as exc:
                text = str(exc).lower()
                if "404" in text or "not found" in text:
                    workflow_broken = True
                else:
                    raise
        result_wire = {
            key: value
            for key, value in result.items()
            if key not in {"evidence_mismatch", "manifest_valid"}
        }
        result_wire["retained_asset_missing"] = dist_assets_missing
        result_wire["workflow_broken_at_tag"] = workflow_broken
        return (
            result_wire,
            manifest_mismatch,
            result["evidence_mismatch"],
            dist_assets_missing,
        )

    def _train_context(
        self,
        tags: list[dict[str, Any]],
        releases: list[tuple[dict[str, Any], dict[str, Any]]],
        pypi: dict[str, dict[str, Any]],
        workflows: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        release_by_tag = {wire["tag"]: (wire, raw) for wire, raw in releases}
        tag_by_name = {tag["name"]: tag for tag in tags}
        sase_files = pypi["sase"]["files"]
        runs = workflows["release_yml"]
        manifest_data: dict[
            str, tuple[dict[str, Any] | None, list[dict[str, Any]], bool, bool]
        ] = {}
        for tag, (release_wire, release_raw) in release_by_tag.items():
            if any(
                asset["name"] == "candidate-manifest.json"
                for asset in release_wire["assets"]
            ):
                manifest_data[tag] = self._load_manifest_bundle(
                    release_wire, release_raw
                )

        run_attempts: dict[str, int] = {}
        wrong_head_tags: set[str] = set()
        for run in runs:
            run_tag = run.get("ref_name")
            if (
                run_tag in tag_by_name
                and run.get("sha") != tag_by_name[run_tag]["peeled_sha"]
            ):
                wrong_head_tags.add(run_tag)
            elif run_tag in tag_by_name:
                run_attempts[str(run["run_id"])] = int(run["attempt"])

        evaluations: dict[str, tuple[dict[str, Any] | None, bool, bool, bool]] = {}
        for tag, bundle in manifest_data.items():
            (
                manifest,
                observations,
                bundle_manifest_mismatch,
                bundle_evidence_mismatch,
            ) = bundle
            if manifest is None:
                evaluations[tag] = (None, True, bundle_evidence_mismatch, True)
                continue
            wire = release_by_tag[tag][0]
            tag_fact = tag_by_name.get(tag, {})
            # A candidate's latest evidence must belong to the current attempt
            # of its release run. Older attempts are retained for the evaluator
            # to verify, but cannot stand in for a newer run attempt.
            grouped_attempts: dict[tuple[str, str], int] = {}
            attempt_mismatch = False
            generation = manifest.get("generation")
            candidate_id = manifest.get("candidate_id")
            for observation in observations:
                if (
                    observation.get("generation") != generation
                    or observation.get("candidate_id") != candidate_id
                ):
                    continue
                kind = str(observation.get("kind", ""))
                run_id = str(observation.get("run_id", ""))
                attempt = observation.get("attempt")
                if not isinstance(attempt, int) or isinstance(attempt, bool):
                    attempt_mismatch = True
                    continue
                grouped_attempts[(kind, run_id)] = max(
                    grouped_attempts.get((kind, run_id), 0), attempt
                )
            for (_kind, run_id), latest_attempt in grouped_attempts.items():
                if run_attempts.get(run_id) != latest_attempt:
                    attempt_mismatch = True
            required_manifest_fields = {
                "schema_version",
                "repository",
                "version",
                "tag",
                "sha",
                "tree",
                "generation",
                "builder_revision",
                "builder_run_id",
                "builder_attempt",
                "core_source_pin",
                "core_version",
                "core_files",
                "dists",
                "candidate_id",
            }
            valid_identity = (
                isinstance(manifest.get("candidate_id"), str)
                and bool(manifest.get("candidate_id"))
                and isinstance(manifest.get("version"), str)
                and isinstance(manifest.get("generation"), int)
                and not isinstance(manifest.get("generation"), bool)
                and manifest.get("generation", 0) > 0
            )
            if not required_manifest_fields.issubset(manifest) or not valid_identity:
                evaluations[tag] = (None, True, bundle_evidence_mismatch, True)
                continue
            eval_wire, manifest_mismatch, evidence_mismatch, missing_asset = (
                self._fact_eval(
                    manifest, observations, wire, tag_fact.get("peeled_sha", ""), runs
                )
            )
            evaluations[tag] = (
                eval_wire,
                bundle_manifest_mismatch or manifest_mismatch,
                bundle_evidence_mismatch
                or evidence_mismatch
                or attempt_mismatch
                or tag in wrong_head_tags,
                missing_asset,
            )

        complete_legacy: set[str] = set()
        first_manifest_key = min(
            (
                _version_key(version)
                for tag in manifest_data
                if (version := self._release_version(tag)) is not None
            ),
            default=None,
        )
        for tag, (release_wire, _raw) in release_by_tag.items():
            if any(
                asset["name"] == "candidate-manifest.json"
                for asset in release_wire["assets"]
            ):
                continue
            version = self._release_version(tag)
            if (
                version is None
                or release_wire["draft"]
                or (
                    first_manifest_key is not None
                    and _version_key(version) >= first_manifest_key
                )
            ):
                continue
            live = [
                file
                for file in sase_files
                if file["version"] == version and not file["yanked"]
            ]
            if any(file["filename"].endswith(".whl") for file in live) and any(
                file["filename"].endswith(".tar.gz") for file in live
            ):
                complete_legacy.add(tag)

        confirmed_versions: list[tuple[int, str]] = []
        for tag in complete_legacy:
            version = self._release_version(tag)
            if version:
                confirmed_versions.append((_version_key(version), version))
        for tag, (
            manifest,
            observations,
            _bundle_manifest_mismatch,
            _bundle_evidence_mismatch,
        ) in manifest_data.items():
            version = self._release_version(tag)
            if version is None or manifest is None:
                continue
            candidate, mismatch, evidence_mismatch, _missing = evaluations[tag]
            if candidate is None:
                continue
            confirmation = any(
                item.get("kind") == "confirmation"
                and item.get("candidate_id") == manifest.get("candidate_id")
                and item.get("generation") == manifest.get("generation")
                and item.get("verdict") == "pass"
                for item in observations
            )
            pypi_files = [file for file in sase_files if file["version"] == version]
            dist_records = (
                manifest.get("dists") if isinstance(manifest.get("dists"), list) else []
            )
            expected = {
                dist.get("filename"): dist.get("sha256")
                for dist in dist_records
                if isinstance(dist, dict)
            }
            matching = [
                file
                for file in pypi_files
                if file["filename"] in expected and not file["yanked"]
            ]
            digest_conflict = any(
                file["sha256"] != expected[file["filename"]] for file in matching
            )
            extras = any(file["filename"] not in expected for file in pypi_files)
            confirmation_complete = (
                confirmation
                and not release_wire["draft"]
                and not mismatch
                and not evidence_mismatch
                and not digest_conflict
                and not extras
                and len(matching) == len(expected)
            )
            if confirmation_complete:
                confirmed_versions.append((_version_key(version), version))

        baseline = max(confirmed_versions, default=(None, None))[1]
        trains: list[dict[str, Any]] = []
        candidate_by_tag: dict[str, dict[str, Any]] = {}
        for tag, tag_fact in sorted(
            tag_by_name.items(), key=lambda pair: _version_key(pair[0][1:])
        ):
            version = self._release_version(tag)
            if version is None:
                continue
            release_pair = release_by_tag.get(tag)
            release_wire, release_raw = release_pair if release_pair else (None, None)
            bundle = manifest_data.get(tag)
            if bundle is None and tag in complete_legacy:
                files = [file for file in sase_files if file["version"] == version]
                trains.append(
                    {
                        "candidate_id": f"legacy:{tag}",
                        "version": version,
                        "tag": tag,
                        "sha": tag_fact["peeled_sha"],
                        "generation": 0,
                        "confirmed": True,
                        "abandoned": False,
                        "pre_train_legacy": True,
                        "manifest_mismatch": False,
                        "evidence_mismatch": False,
                        "py_files_present": len(
                            [file for file in files if not file["yanked"]]
                        ),
                        "py_files_expected": 2,
                        "py_digest_conflict": False,
                        "py_extra_files": False,
                        "confirmation_complete": True,
                    }
                )
                continue
            if bundle is None:
                newer_than_baseline = baseline is None or _version_key(
                    version
                ) > _version_key(baseline)
                if not newer_than_baseline and not (
                    release_wire and release_wire["draft"]
                ):
                    continue
                trains.append(
                    {
                        "candidate_id": f"unsealed:{tag}:{tag_fact['peeled_sha']}",
                        "version": version,
                        "tag": tag,
                        "sha": tag_fact["peeled_sha"],
                        "generation": 0,
                        "confirmed": False,
                        "abandoned": False,
                        "pre_train_legacy": False,
                        "manifest_mismatch": True,
                        "evidence_mismatch": False,
                        "py_files_present": len(
                            [
                                file
                                for file in sase_files
                                if file["version"] == version and not file["yanked"]
                            ]
                        ),
                        "py_files_expected": 2,
                        "py_digest_conflict": False,
                        "py_extra_files": False,
                        "confirmation_complete": False,
                    }
                )
                continue
            if release_wire is None:
                continue
            (
                manifest,
                observations,
                bundle_manifest_mismatch,
                bundle_evidence_mismatch,
            ) = bundle
            eval_wire, manifest_mismatch, evidence_mismatch, _missing = evaluations[tag]
            if manifest is None:
                trains.append(
                    {
                        "candidate_id": f"unsealed:{tag}:{tag_fact['peeled_sha']}",
                        "version": version,
                        "tag": tag,
                        "sha": tag_fact["peeled_sha"],
                        "generation": 0,
                        "confirmed": False,
                        "abandoned": False,
                        "pre_train_legacy": False,
                        "manifest_mismatch": True,
                        "evidence_mismatch": bundle_evidence_mismatch,
                        "py_files_present": len(
                            [
                                file
                                for file in sase_files
                                if file["version"] == version and not file["yanked"]
                            ]
                        ),
                        "py_files_expected": 2,
                        "py_digest_conflict": False,
                        "py_extra_files": False,
                        "confirmation_complete": False,
                    }
                )
                continue
            version_files = [file for file in sase_files if file["version"] == version]
            dists = (
                manifest.get("dists") if isinstance(manifest.get("dists"), list) else []
            )
            expected = {
                dist.get("filename"): str(dist.get("sha256", "")).lower()
                for dist in dists
                if isinstance(dist, dict) and isinstance(dist.get("filename"), str)
            }
            matching = [
                file
                for file in version_files
                if file["filename"] in expected and not file["yanked"]
            ]
            digest_conflict = any(
                file["sha256"] != expected[file["filename"]] for file in matching
            )
            extras = any(file["filename"] not in expected for file in version_files)
            abandoned = any(
                item.get("kind") == "abandoned"
                and item.get("candidate_id") == manifest.get("candidate_id")
                and item.get("generation") == manifest.get("generation")
                for item in observations
            )
            confirmation = any(
                item.get("kind") == "confirmation"
                and item.get("candidate_id") == manifest.get("candidate_id")
                and item.get("generation") == manifest.get("generation")
                and item.get("verdict") == "pass"
                for item in observations
            )
            confirmation_complete = (
                confirmation
                and not release_wire["draft"]
                and not bundle_manifest_mismatch
                and not bundle_evidence_mismatch
                and not manifest_mismatch
                and not evidence_mismatch
                and not digest_conflict
                and not extras
                and len(matching) == len(expected)
            )
            train = {
                "candidate_id": (
                    manifest.get("candidate_id")
                    if isinstance(manifest.get("candidate_id"), str)
                    and manifest.get("candidate_id")
                    else f"unsealed:{tag}:{tag_fact['peeled_sha']}"
                ),
                "version": version,
                "tag": tag,
                "sha": tag_fact["peeled_sha"],
                "generation": (
                    manifest.get("generation")
                    if isinstance(manifest.get("generation"), int)
                    and not isinstance(manifest.get("generation"), bool)
                    and manifest.get("generation", 0) > 0
                    else 0
                ),
                "confirmed": confirmation_complete,
                "abandoned": abandoned,
                "pre_train_legacy": False,
                "manifest_mismatch": bundle_manifest_mismatch or manifest_mismatch,
                "evidence_mismatch": (
                    bundle_evidence_mismatch
                    or evidence_mismatch
                    or tag in wrong_head_tags
                ),
                "py_files_present": len(matching),
                "py_files_expected": len(expected),
                "py_digest_conflict": digest_conflict,
                "py_extra_files": extras,
                "confirmation_complete": confirmation_complete,
            }
            trains.append(train)
            if eval_wire is not None:
                candidate_by_tag[tag] = eval_wire

        active = [
            train
            for train in trains
            if not train["pre_train_legacy"]
            and not train["confirmed"]
            and not train["abandoned"]
        ]
        candidate = candidate_by_tag.get(active[0]["tag"]) if len(active) == 1 else None
        return trains, candidate

    def _fact(self, source: str, fn: Any, remedy: str) -> dict[str, Any]:
        try:
            value = fn()
        except Exception as exc:
            source_name = (
                exc.source if isinstance(exc, ReleaseTransportError) else source
            )
            return unreadable(source_name, str(exc), remedy)
        return ready(value)

    def collect_train_snapshot(self, *, observed_at: datetime | str) -> dict[str, Any]:
        """Build the train-owned subset of one snapshot from fresh remote reads.

        ``observed_at`` is explicit so test fixtures and the caller's policy
        clock cannot silently disagree. Health, canary, escalation, and core
        facts are intentionally left for the health reader phase.
        """
        now = _utc(
            _iso(observed_at) if isinstance(observed_at, datetime) else observed_at,
            "observed_at",
        )
        repository_fact = self._fact(
            "repository",
            self.read_repository,
            "restore read access to the repository metadata API",
        )
        master_fact = self._fact(
            "master",
            lambda: self._master_facts(now),
            "restore read access to master, branch protection, and Actions",
        )
        release_records_fact = self._fact(
            "releases",
            self._all_release_records,
            "restore read access to GitHub releases and assets",
        )
        if release_records_fact["status"] == "ready":
            release_records = release_records_fact["value"]
            release_wires = [wire for wire, _raw in release_records]
            release_fact = ready(release_wires)
        else:
            release_records = []
            release_wires = []
            release_fact = release_records_fact
        tags_fact = (
            self._fact(
                "tags",
                lambda: self._tags_with_releases(release_wires),
                "restore read access to GitHub tags and annotated tag objects",
            )
            if release_fact["status"] == "ready"
            else release_records_fact
        )
        pypi_fact = self._fact(
            "pypi", self._pypi_payloads, "restore read access to the PyPI JSON API"
        )
        workflows_fact = self._fact(
            "workflows",
            lambda: self._workflows(
                now, tags_fact["value"] if tags_fact["status"] == "ready" else []
            ),
            "restore read access to release.yml and publish.yml workflow history",
        )
        if master_fact["status"] == "ready":
            pr_context_fact = self._fact(
                "release_pr",
                lambda: self._release_pr_context(master_fact["value"]),
                "restore read access to release PRs, exact-head checks, and commit contents",
            )
        else:
            pr_context_fact = unreadable(
                "release_pr",
                "master identity is unreadable",
                "restore the required master facts",
            )
        if pr_context_fact["status"] == "ready":
            release_pr, merge_history = pr_context_fact["value"]
            release_pr_fact = ready(release_pr)
            merge_history_fact = ready(merge_history)
        else:
            release_pr_fact = pr_context_fact
            merge_history_fact = pr_context_fact
        if all(
            fact["status"] == "ready"
            for fact in (tags_fact, release_records_fact, pypi_fact, workflows_fact)
        ):
            trains_fact = self._fact(
                "trains",
                lambda: self._train_context(
                    tags_fact["value"],
                    release_records,
                    pypi_fact["value"],
                    workflows_fact["value"],
                ),
                "repair candidate manifest/evidence assets and retry the read-only evaluator",
            )
            if trains_fact["status"] == "ready":
                train_values, candidate_value = trains_fact["value"]
                trains_fact = ready(train_values)
                candidate_fact = ready(candidate_value)
            else:
                candidate_fact = trains_fact
        else:
            trains_fact = unreadable(
                "trains",
                "tags, releases, PyPI, or workflow facts needed to reconstruct trains are unreadable",
                "restore the source read and retry the tick",
            )
            candidate_fact = trains_fact
        # Tag facts are updated with manifest presence only after release assets
        # are known. This produces the exact Rust wire shape.
        return {
            "repository": repository_fact,
            "master": master_fact,
            "release_pr": release_pr_fact,
            "tags": tags_fact,
            "releases": release_fact,
            "pypi": pypi_fact,
            "trains": trains_fact,
            "workflows": workflows_fact,
            "candidate": candidate_fact,
            "merge_history": merge_history_fact,
        }

    def collect_snapshot(
        self,
        *,
        observed_at: datetime | str,
        health: Any = None,
    ) -> dict[str, Any]:
        """Build the complete per-tick snapshot from fresh remote reads.

        The train third comes from :meth:`collect_train_snapshot`; the
        health third (core, canary, core_ensure, issues, core Actions
        access, blocker lineage) comes from *health*, defaulting to a
        ``ReleaseHealthReader`` over this reader. The train snapshot's
        master and release PR values select the source-pin identity so
        both readers agree on it.
        """
        from _release_watch_health import ReleaseHealthReader

        train = self.collect_train_snapshot(observed_at=observed_at)
        reader = health if health is not None else ReleaseHealthReader(self)
        master_value = (
            train["master"]["value"] if train["master"]["status"] == "ready" else None
        )
        release_pr_value = (
            train["release_pr"]["value"]
            if train["release_pr"]["status"] == "ready"
            else None
        )
        health_snapshot = reader.collect_health_snapshot(
            observed_at=observed_at,
            master=master_value,
            release_pr=release_pr_value,
        )
        return {
            "repository": train["repository"],
            "master": train["master"],
            "release_pr": train["release_pr"],
            "tags": train["tags"],
            "releases": train["releases"],
            "pypi": train["pypi"],
            "trains": train["trains"],
            "workflows": train["workflows"],
            "core": health_snapshot["core"],
            "canary": health_snapshot["canary"],
            "candidate": train["candidate"],
            "core_ensure": health_snapshot["core_ensure"],
            "issues": health_snapshot["issues"],
            "core_actions_access": health_snapshot["core_actions_access"],
            "merge_history": train["merge_history"],
            "blocker_lineage": health_snapshot["blocker_lineage"],
        }

    def _tags_with_releases(
        self, releases: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        release_map = {release["tag"]: release for release in releases}
        tags = []
        for name, sha in self._tag_refs():
            release = release_map.get(name)
            has_manifest = bool(
                release
                and any(
                    asset["name"] == "candidate-manifest.json"
                    for asset in release["assets"]
                )
            )
            tags.append({"name": name, "peeled_sha": sha, "has_manifest": has_manifest})
        return tags


__all__ = [
    "DEFAULT_REPO",
    "MASTER_GATE_WORKFLOW",
    "PUBLISH_WORKFLOW",
    "RELEASE_WORKFLOW",
    "ReleaseFactsError",
    "ReleaseFactsReader",
    "absent",
    "parse_pypi_inventory",
    "ready",
    "unreadable",
]
