#!/usr/bin/env python3
"""Health, canary, and escalation evidence for the release steward.

This module owns the health third of the per-tick snapshot: ``core``,
``canary``, ``core_ensure``, ``issues``, ``core_actions_access``, and
``blocker_lineage``. It reuses the read-only transports and wire helpers from
the train-facts phase (``_release_watch_transport``,
``_release_watch_facts``) and the shared core-ensure rule
(``_release_core.ensure_core``). It performs shape and transport conversion
only; shared eligibility, precedence, idempotency, and escalation policy
live in the ``sase_core`` Rust policy and are never recomputed here.

Conventions honored by this reader:

* Absent evidence is distinct from an unreadable API response. A missing
  canary artifact or a run with no typed failure is an install-health or
  cut finding, never a pass. Only a failed read forbids authorizing an
  action.
* The source pin is always read at a remote identity (the open release
  PR head, else master HEAD) through the train reader. The local
  checkout's pin is never substituted.
* ``EXPECTED_DIST_SUFFIXES`` is never copied here: ``ensure_core`` reads
  it from sase-core's ``release-plz.yml`` at each candidate tag, fetched
  through the same core transport via an injected workflow reader.
* Core-cut ``source_pin`` is the cut run's own head SHA: a completed
  green cut at core commit X covers a sase source pin of X. Equality
  matching against the lagging pin is the Rust policy's job.
* A core cut is a run that could merge the release PR: a ``schedule`` or
  ``workflow_dispatch`` run whose "Merge release PR" job ran (was not
  skipped). ``push`` runs and merge-skipped heal or dry-run dispatches
  are never cuts, so a green push at the lagging pin neither satisfies
  ``CORE_LAG`` nor supersedes a failed cut. In-flight schedule and
  dispatch runs count as in-flight cuts, which conservatively blocks a
  second dispatch. Each cut also carries the run ``event`` and
  ``started_at`` (``run_started_at``, falling back to ``created_at``)
  so the Rust daily dispatch cap can derive UTC days.
* Canary verdicts normalize the install-smoke schema-v1 ``green``/``red``
  to the policy wire's ``pass``/``fail``. Anything else is an explicit
  marker (``unparsable``, ``unexpected_identity``), never a pass.
* Typed core-cut evidence is exactly one first line of a check-run
  annotation: ``CORE_CUT_RED check=<check> run=<url> attempt=<n>`` or
  ``CHECKS_NEVER_REGISTERED check=checks run=unknown attempt=0``, the two
  lines ``release_plz_merge.py`` emits through ``::error::``. A red cut
  with no such annotation fails closed (``diagnostic_available`` false);
  a cancelled or skipped cut is not a cut failure.
* Escalation issues are read with the ``release-steward`` label, open and
  closed. The machine-readable contract this reader parses (written by the
  effects phase) is one HTML comment in the issue body::

      <!-- release-steward:family=<family> identity=<identity>
           [candidate=<id>] [pin=<sha>] [sha=<sha>] [signature=<sig>] -->

  plus one ``release-steward:tick=<tick-identity>`` marker per steward
  comment for +1 de-duplication. Issues without a marker fall back to the
  ``release-steward: <family> (<identity>)`` title shape, then to an
  ``unknown`` family that never matches an active marker.
* Blocker lineage names the oldest open marker-bearing issue. The Rust
  policy validates the family/identity match and treats a mismatch as
  uncertainty, so this reader never invents 24-hour ages and never uses
  the process start time. Close/reopen cycles are not tracked: continuity
  means an open issue with this marker exists now.
* The core Actions-access probe is one tiny read (``actions/runs`` with
  ``per_page=1``) through the host credential. Success proves read access
  only; workflow-dispatch write permission is never claimed and never
  tested with a production dispatch.
* A read-only live fact collection may be used for debugging. It never
  mutates production and never satisfies the scheduled-tick proof.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from _release_core import (
    CORE_REPO,
    WORKFLOW_PATH as CORE_CUT_WORKFLOW_PATH,
    CoreEnsureError,
    CoreLag,
    Pinned,
    ensure_core,
)
from _release_watch_facts import (
    HISTORY_LOOKBACK,
    ReleaseFactsError,
    ReleaseFactsReader,
    absent,
    ready,
    unreadable,
)
from _release_watch_transport import (
    GH_TIMEOUT_SECONDS,
    GithubTransport,
    ReleaseTransportError,
    run_process,
)

CORE_CI_WORKFLOW = "ci.yml"
CORE_CUT_WORKFLOW = "release-plz.yml"
CANARY_WORKFLOW = "install-smoke.yml"
STEWARD_LABEL = "release-steward"
# Newest completed core-cut runs retained per tick; every in-flight cut is
# always retained so lag matching never misses a live run.
CUT_HISTORY_LIMIT = 20
_ARTIFACT_MEMBER = {"ubuntu-latest": "linux", "macos-latest": "macos"}
_FLIGHT_STATUSES = {
    "queued",
    "pending",
    "in_progress",
    "waiting",
    "requested",
    "waiting_for_deploy",
}
# Only runs that could merge the core release PR are cuts. Push runs never
# merge it; the six-hourly heal schedule and dry-run dispatches skip the
# merge job too. The merge job's display name in release-plz.yml.
_MERGE_JOB_NAME = "Merge release PR"
# Run events that can carry a merge-capable cut.
_CUT_EVENTS = {"schedule", "workflow_dispatch"}
_CUT_FAILURE_CONCLUSIONS = {
    "failure",
    "timed_out",
    "action_required",
    "startup_failure",
}
_TYPED_CUT_RE = re.compile(r"^CORE_CUT_RED check=\S+ run=\S+ attempt=\d+$")
_TYPED_NEVER_REGISTERED = "CHECKS_NEVER_REGISTERED check=checks run=unknown attempt=0"
_MARKER_RE = re.compile(
    r"release-steward:family=(\S+)\s+identity=(\S+)((?:\s+[A-Za-z_]+=\S+)*)"
)
_MARKER_FIELD_RE = re.compile(r"([A-Za-z_]+)=(\S+)")
_TICK_RE = re.compile(r"release-steward:tick=(\S+)")
_TITLE_RE = re.compile(r"^release-steward:\s*([A-Za-z0-9_]+)\s*\(([^)]+)\)\s*$")
_CHECK_RUN_ID_RE = re.compile(r"/check-runs/(\d+)\s*$")
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseFactsError(f"{where} must be a non-empty string")
    return value.strip()


def _count(value: object, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReleaseFactsError(f"{where} must be an integer >= {minimum}")
    return value


def _moment(value: object, where: str) -> str:
    """Validate an RFC 3339 timestamp and normalize it to ``Z`` form."""
    if not isinstance(value, str) or not value.strip():
        raise ReleaseFactsError(f"{where} must be an RFC 3339 timestamp")
    raw = value.strip()
    text = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReleaseFactsError(f"{where} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseFactsError(f"{where} must include a UTC offset")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_text(value: object, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ReleaseFactsError(f"{where} must be a string or null")
    return value.strip()


def _flatten_pages(pages: list[Any]) -> list[Any]:
    """Normalize transport array-endpoint payloads to one row list.

    The transport flattens ``--slurp`` list pages, so production
    payloads are already one flat row list; nested page lists are
    accepted too so fixture and caller shapes cannot silently drop rows.
    """
    if pages and isinstance(pages[0], list):
        return [item for page in pages for item in page]
    return list(pages)


def _labels(value: object, where: str) -> list[str]:
    names = []
    if not isinstance(value, list):
        raise ReleaseFactsError(f"{where} must be a list")
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ReleaseFactsError(f"{where}[{index}] must be an object")
        names.append(_text(raw.get("name"), f"{where}[{index}].name"))
    return sorted(set(names))


def _coerce_observed_at(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReleaseFactsError("observed_at is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseFactsError("observed_at must include a UTC offset")
    return parsed.astimezone(UTC)


def _download_artifact_text(repo: str, run_id: str, name: str) -> str:
    """Download one workflow artifact's JSON file with a read-only command."""
    with tempfile.TemporaryDirectory(prefix="release-watch-canary-") as tmp:
        try:
            result = run_process(
                [
                    "gh",
                    "run",
                    "download",
                    str(run_id),
                    "--repo",
                    repo,
                    "-n",
                    name,
                    "-D",
                    tmp,
                ],
                timeout=GH_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseTransportError(
                f"canary artifact {name}", f"download failed: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            lowered = detail.lower()
            if (
                "not found" in lowered
                or "no artifact" in lowered
                or "expired" in lowered
                or "404" in lowered
            ):
                raise ReleaseTransportError(
                    f"canary artifact {name}",
                    f"artifact is missing or expired: {detail[:200]}",
                )
            raise ReleaseTransportError(
                f"canary artifact {name}",
                f"gh run download exited {result.returncode}"
                + (f": {detail[:300]}" if detail else ""),
            )
        candidates = sorted(Path(tmp).rglob("*.json"), key=lambda p: p.name)
        if not candidates:
            raise ReleaseTransportError(
                f"canary artifact {name}", "artifact contains no JSON file"
            )
        try:
            return candidates[0].read_text(encoding="utf-8")
        except OSError as exc:
            raise ReleaseTransportError(
                f"canary artifact {name}", f"artifact is unreadable: {exc}"
            ) from exc


class ReleaseHealthReader:
    """Read health, canary, and escalation evidence per tick."""

    def __init__(
        self,
        facts: ReleaseFactsReader,
        *,
        core_github: GithubTransport | None = None,
        artifact_text: Any = None,
    ) -> None:
        self._facts = facts
        self._core_transport = core_github or GithubTransport(CORE_REPO)
        self._core = ReleaseFactsReader(
            repo=CORE_REPO,
            github=self._core_transport,
            pypi=facts.pypi,
        )
        self._artifact_text = artifact_text or _download_artifact_text

    # -- core-ensure --------------------------------------------------------

    def _core_compare(self, pin: str, version: str) -> str:
        try:
            payload = self._core_transport.json(
                f"repos/{CORE_REPO}/compare/{pin}...v{version}"
            )
        except ReleaseTransportError as exc:
            # Fail closed without a local-git substitute: a transient
            # read becomes the Error variant, which the policy treats as
            # WATCHER_BROKEN and retries next tick.
            raise CoreEnsureError(f"unreadable compare {pin}...v{version}") from exc
        if not isinstance(payload, dict):
            raise CoreEnsureError(
                f"unreadable compare {pin}...v{version}: not an object"
            )
        status = payload.get("status")
        if not isinstance(status, str) or not status.strip():
            raise CoreEnsureError(
                f"unreadable compare {pin}...v{version}: missing status"
            )
        return status.strip().lower()

    def _core_workflow_text(self, version: str) -> str:
        try:
            payload = self._core_transport.json(
                f"repos/{CORE_REPO}/contents/{CORE_CUT_WORKFLOW_PATH}",
                params={"ref": f"v{version}"},
            )
        except ReleaseTransportError as exc:
            raise CoreEnsureError(
                f"unreadable {CORE_CUT_WORKFLOW_PATH} at v{version}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            raise CoreEnsureError(
                f"unreadable {CORE_CUT_WORKFLOW_PATH} at v{version}: not base64"
            )
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            raise CoreEnsureError(
                f"unreadable {CORE_CUT_WORKFLOW_PATH} at v{version}: empty content"
            )
        try:
            # The contents API wraps base64 at 60 columns; strip wrapping
            # before the strict decode.
            return base64.b64decode("".join(content.split()), validate=True).decode(
                "utf-8"
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise CoreEnsureError(
                f"unreadable {CORE_CUT_WORKFLOW_PATH} at v{version}: {exc}"
            ) from exc

    def read_core_ensure(
        self,
        release_pr: dict[str, Any] | None,
        master_sha: str,
    ) -> dict[str, Any]:
        """Map ``ensure_core`` over freshly read PyPI metadata and the pin.

        The pin comes from the open release PR head when one is selected,
        else from master HEAD. Both are remote identities; the local
        checkout's pin is never substituted.
        """
        if release_pr is not None:
            pin = _text(release_pr.get("source_pin"), "release_pr.source_pin").lower()
        else:
            pin = self._facts.read_source_pin(master_sha)
        metadata = self._facts.pypi.project("sase-core-rs")
        if not isinstance(metadata, dict):
            raise ReleaseFactsError("PyPI sase-core-rs metadata must be an object")
        try:
            result = ensure_core(
                pin,
                pypi_metadata=metadata,
                compare_fn=self._core_compare,
                workflow_fn=self._core_workflow_text,
            )
        except CoreEnsureError as exc:
            return {"kind": "error", "message": str(exc)}
        if isinstance(result, Pinned):
            return {"kind": "pinned", "version": result.version, "files": result.files}
        if isinstance(result, CoreLag):
            wire: dict[str, Any] = {"kind": "core_lag", "pin": result.pin}
            if result.newest_complete is not None:
                wire["newest_complete"] = result.newest_complete
            return wire
        raise ReleaseFactsError("ensure_core returned an unknown result")

    # -- core CI / release PR / cuts ----------------------------------------

    def _core_master_sha(self) -> str:
        return self._core.read_ref_sha("heads/master")

    def read_core_facts(self, observed_at: datetime) -> dict[str, Any]:
        """Read core master CI, the open core release PR, and core-cut runs."""
        since = observed_at - HISTORY_LOOKBACK
        until = observed_at + timedelta(minutes=1)
        sha = self._core_master_sha()
        runs = self._core.read_runs(
            CORE_CI_WORKFLOW, since=since, until=until, branch="master"
        )
        gate_run: dict[str, Any] | None = None
        for run in runs:
            if run["sha"] == sha:
                gate_run = dict(run)
                gate_run["jobs"] = self._core.read_jobs(
                    gate_run["run_id"], gate_run["attempt"]
                )
                gate_run.pop("created_at", None)
                break
        cuts = self._read_cuts(since, until)
        return {
            "master_ci": gate_run,
            "open_release_pr": self._read_core_release_pr(),
            "cuts": cuts,
        }

    def _raw_jobs(self, run_id: str, attempt: int) -> list[dict[str, Any]]:
        pages = self._core_transport.pages(
            f"repos/{CORE_REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs"
        )
        rows: list[Any] = []
        for page in _flatten_pages(pages):
            if isinstance(page, dict) and isinstance(page.get("jobs"), list):
                rows.extend(page["jobs"])
            else:
                rows.append(page)
        for row in rows:
            if not isinstance(row, dict):
                raise ReleaseFactsError(f"run {run_id} jobs page has an odd shape")
        found = []
        for index, raw in enumerate(rows):
            if not isinstance(raw, dict):
                raise ReleaseFactsError(f"run {run_id} jobs[{index}] must be an object")
            job_id = raw.get("id")
            if isinstance(job_id, bool) or not isinstance(job_id, (str, int)):
                raise ReleaseFactsError(f"run {run_id} jobs[{index}].id is invalid")
            conclusion = raw.get("conclusion")
            if conclusion is not None and not isinstance(conclusion, str):
                raise ReleaseFactsError(
                    f"run {run_id} jobs[{index}].conclusion must be a string or null"
                )
            check_url = raw.get("check_run_url")
            found.append(
                {
                    "id": str(job_id),
                    "name": _text(raw.get("name"), f"run {run_id} jobs[{index}]"),
                    "conclusion": (conclusion or "").strip().lower() or None,
                    "check_run_url": check_url if isinstance(check_url, str) else None,
                }
            )
        found.sort(key=lambda item: (item["name"], item["id"]))
        return found

    def _typed_cut_evidence(self, run_id: str, attempt: int) -> str | None:
        """Return the typed merge-helper line bound to this cut run.

        Only an exact first line of a failed job's check-run annotation
        counts. Anything else fails closed at the call site.
        """
        for job in self._raw_jobs(run_id, attempt):
            if job["conclusion"] not in _CUT_FAILURE_CONCLUSIONS:
                continue
            check_url = job["check_run_url"] or ""
            match = _CHECK_RUN_ID_RE.search(check_url)
            if not match:
                continue
            annotations = self._core_transport.json(
                f"repos/{CORE_REPO}/check-runs/{match.group(1)}/annotations"
            )
            if not isinstance(annotations, list):
                raise ReleaseFactsError(f"run {run_id} annotations must be a list")
            for raw in annotations:
                if not isinstance(raw, dict):
                    raise ReleaseFactsError(
                        f"run {run_id} annotation must be an object"
                    )
                message = raw.get("message")
                if not isinstance(message, str):
                    continue
                first = (
                    message.strip().splitlines()[0].strip() if message.strip() else ""
                )
                if _TYPED_CUT_RE.fullmatch(first) or first == _TYPED_NEVER_REGISTERED:
                    return first
        return None

    def _merge_job_ran(self, run_id: str, attempt: int) -> bool:
        """Whether the run's "Merge release PR" job ran (was not skipped).

        Push runs never reach this check: the caller only asks about
        ``schedule`` and ``workflow_dispatch`` runs. A skipped merge job
        means a heal schedule or a dry-run dispatch, neither of which is
        a cut. Anything else (success, failure, cancelled, even a queued
        job with no conclusion yet) counts as ran; completion of the run
        itself is the caller's concern.
        """
        for job in self._raw_jobs(run_id, attempt):
            if job["name"] != _MERGE_JOB_NAME:
                continue
            conclusion = (job["conclusion"] or "").strip().lower()
            if conclusion and conclusion != "skipped":
                return True
        return False

    def _cut_wire(
        self, run: dict[str, Any], typed: str | None, diagnostic: bool
    ) -> dict[str, Any]:
        wire: dict[str, Any] = {
            "run_id": str(run["run_id"]),
            "attempt": _count(
                run["attempt"], f"run {run['run_id']}.attempt", minimum=1
            ),
            "source_pin": _text(run["sha"], f"run {run['run_id']}.sha").lower(),
            "status": _text(run["status"], f"run {run['run_id']}.status"),
            "conclusion": run["conclusion"],
            "diagnostic_available": diagnostic,
            "event": run.get("event"),
            # The daily dispatch cap derives UTC days from run timestamps;
            # a queued run has no start yet, so fall back to creation.
            "started_at": run.get("started_at") or run.get("created_at"),
        }
        if typed is not None:
            wire["typed_failure"] = typed
        return wire

    def _read_cuts(self, since: datetime, until: datetime) -> list[dict[str, Any]]:
        """Return cuts newest first: in-flight plus newest completed.

        Only merge-capable runs are cuts: ``push`` runs never merge the
        release PR, and a completed ``schedule`` or ``workflow_dispatch``
        run is a cut only when its "Merge release PR" job ran. In-flight
        schedule and dispatch runs count as in-flight cuts without a job
        read, which conservatively blocks a second dispatch.
        """
        runs = self._core.read_runs(CORE_CUT_WORKFLOW, since=since, until=until)
        in_flight: list[dict[str, Any]] = []
        completed: list[dict[str, Any]] = []
        for run in runs:
            if (run.get("event") or "") not in _CUT_EVENTS:
                # Push (and any unknown event): never a cut.
                continue
            if run["status"] in _FLIGHT_STATUSES:
                in_flight.append(run)
            elif run["status"] == "completed" and len(completed) < CUT_HISTORY_LIMIT:
                if self._merge_job_ran(run["run_id"], run["attempt"]):
                    completed.append(run)
                # Merge-skipped heal and dry-run dispatches are not cuts
                # and do not consume history budget.
        kept = sorted(
            in_flight + completed,
            key=lambda item: (item["created_at"], item["attempt"], item["run_id"]),
            reverse=True,
        )
        cuts = []
        for run in kept:
            if run["status"] in _FLIGHT_STATUSES:
                cuts.append(self._cut_wire(run, None, True))
            elif run["conclusion"] in _CUT_FAILURE_CONCLUSIONS:
                typed = self._typed_cut_evidence(run["run_id"], run["attempt"])
                cuts.append(self._cut_wire(run, typed, typed is not None))
            else:
                # Success, cancelled, skipped, or neutral: not a cut
                # failure, so no typed diagnostic is required.
                cuts.append(self._cut_wire(run, None, True))
        return cuts

    def _read_core_release_pr(self) -> dict[str, Any] | None:
        rows = self._core_transport.pages(
            f"repos/{CORE_REPO}/pulls",
            params={
                "state": "open",
                "base": "master",
                "sort": "updated",
                "direction": "desc",
            },
        )
        matches = []
        for raw in _flatten_pages(rows):
            if not isinstance(raw, dict):
                raise ReleaseFactsError("core pull must be an object")
            head = raw.get("head")
            if not isinstance(head, dict):
                continue
            ref = head.get("ref")
            title = raw.get("title")
            if (
                isinstance(ref, str)
                and re.fullmatch(
                    r"release-plz-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z", ref
                )
                and isinstance(title, str)
                and re.fullmatch(r"chore: release v\d+\.\d+\.\d+", title)
            ):
                matches.append(raw)
        if len(matches) > 1:
            numbers = sorted(
                raw["number"] for raw in matches if isinstance(raw.get("number"), int)
            )
            raise ReleaseFactsError(f"multiple open core release PRs: {numbers}")
        if not matches:
            return None
        selected = matches[0]
        number = _count(selected.get("number"), "core release PR number", minimum=1)
        head = selected.get("head")
        assert isinstance(head, dict)
        head_sha = _text(head.get("sha"), "core release PR head").lower()
        if not _SHA_RE.fullmatch(head_sha):
            raise ReleaseFactsError("core release PR head SHA is invalid")
        return {
            "number": number,
            "head_sha": head_sha,
            "url": _text(selected.get("html_url"), "core release PR"),
        }

    # -- install canary ------------------------------------------------------

    def _canary_run(self, since: datetime, until: datetime) -> dict[str, Any] | None:
        runs = self._facts.read_runs(CANARY_WORKFLOW, since=since, until=until)
        for run in runs:
            if run.get("event") == "schedule":
                return run
        return None

    def _canary_member(
        self, member: str, run: dict[str, Any], payload: object
    ) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return self._unparsable(member, run, "canary result is not an object")
        schema = payload.get("schema_version")
        if schema != 1:
            return self._unparsable(member, run, "canary schema_version must be 1")
        os_name = payload.get("os")
        run_id = payload.get("run_id")
        attempt = payload.get("attempt")
        sha = payload.get("sha")
        verdict = payload.get("verdict")
        try:
            os_text = _text(os_name, "canary os")
            run_text = str(_count(int(str(run_id)), "canary run_id", minimum=1))
            attempt_number = _count(int(str(attempt)), "canary attempt", minimum=1)
            sha_text = _text(sha, "canary sha")
            if not _SHA_RE.fullmatch(sha_text):
                raise ReleaseFactsError("canary sha is invalid")
            verdict_text = _text(verdict, "canary verdict")
        except (ReleaseFactsError, ValueError, TypeError):
            return self._unparsable(member, run, "canary identity fields are invalid")
        if _ARTIFACT_MEMBER.get(os_text) != member or run_text != str(run["run_id"]):
            return self._unparsable(member, run, "canary artifact identity mismatch")
        packages = payload.get("packages")
        if not isinstance(packages, list):
            return self._unparsable(member, run, "canary packages must be a list")
        names = []
        for index, raw in enumerate(packages):
            if not isinstance(raw, dict):
                return self._unparsable(
                    member, run, f"canary packages[{index}] must be an object"
                )
            names.append(_text(raw.get("name"), f"canary packages[{index}].name"))
        if verdict_text == "green":
            normalized = "pass"
        elif verdict_text == "red":
            normalized = "fail"
        else:
            return self._unparsable(member, run, "canary verdict must be green or red")
        wire: dict[str, Any] = {
            "member": member,
            "run_id": run_text,
            "attempt": attempt_number,
            "sha": sha_text.lower(),
            "verdict": normalized,
            "packages": sorted(names),
            "scheduled": True,
        }
        failing_step = _optional_text(
            payload.get("failing_step"), "canary failing_step"
        )
        reason = _optional_text(payload.get("reason"), "canary reason")
        if failing_step is not None:
            wire["failing_step"] = failing_step
        if reason is not None:
            wire["reason"] = reason
        return wire

    def _unparsable(
        self, member: str, run: dict[str, Any], detail: str
    ) -> dict[str, Any]:
        return {
            "member": member,
            "run_id": str(run["run_id"]),
            "attempt": _count(run["attempt"], "canary run.attempt", minimum=1),
            "sha": _text(run["sha"], "canary run.sha").lower(),
            "verdict": "unparsable",
            "packages": [],
            "scheduled": True,
            "reason": detail,
        }

    def read_canary(self, observed_at: datetime) -> dict[str, Any]:
        """Read the newest scheduled install-smoke results per platform."""
        since = observed_at - HISTORY_LOOKBACK
        until = observed_at + timedelta(minutes=1)
        run = self._canary_run(since, until)
        if run is None:
            return {"linux": None, "macos": None}
        listing = self._facts.github.json(
            f"repos/{self._facts.repo}/actions/runs/{run['run_id']}/artifacts"
        )
        if not isinstance(listing, dict) or not isinstance(
            listing.get("artifacts"), list
        ):
            raise ReleaseFactsError("canary artifact listing must hold artifacts")
        by_name = {}
        for raw in listing["artifacts"]:
            if not isinstance(raw, dict):
                raise ReleaseFactsError("canary artifact must be an object")
            name = _text(raw.get("name"), "canary artifact.name")
            by_name[name] = raw
        members: dict[str, Any] = {}
        for artifact_name, member in sorted(
            (f"install-canary-{os_name}", member)
            for os_name, member in _ARTIFACT_MEMBER.items()
        ):
            row = by_name.get(artifact_name)
            if row is None or row.get("expired") is True:
                members[member] = None
                continue
            try:
                text = self._artifact_text(
                    self._facts.repo, str(run["run_id"]), artifact_name
                )
            except ReleaseTransportError:
                # A listed-but-undownloadable artifact (expired between
                # calls, retained-log gaps) is a missing contracted
                # result, not a transport outage for the whole tick.
                members[member] = None
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                members[member] = self._unparsable(
                    member, run, "canary result is not valid JSON"
                )
                continue
            members[member] = self._canary_member(member, run, payload)
        return members

    # -- escalation issues ---------------------------------------------------

    @staticmethod
    def _issue_marker(body: str) -> dict[str, str] | None:
        match = _MARKER_RE.search(body)
        if not match:
            return None
        fields = {"family": match.group(1), "identity": match.group(2)}
        for field in _MARKER_FIELD_RE.finditer(match.group(3) or ""):
            fields[field.group(1)] = field.group(2)
        return fields

    def _issue_wire(self, raw: dict[str, Any]) -> dict[str, Any]:
        number = _count(raw.get("number"), "issue number", minimum=1)
        title = _text(raw.get("title"), f"issue {number}.title")
        state = _text(raw.get("state"), f"issue {number}.state")
        if state not in {"open", "closed"}:
            raise ReleaseFactsError(f"issue {number}.state must be open or closed")
        body = raw.get("body") or ""
        if not isinstance(body, str):
            raise ReleaseFactsError(f"issue {number}.body must be a string or null")
        marker = self._issue_marker(body)
        family = identity = ""
        candidate = pin = sha = signature = None
        if marker is not None:
            family = marker["family"]
            identity = marker["identity"]
            candidate = marker.get("candidate")
            pin = marker.get("pin")
            sha = marker.get("sha")
            signature = marker.get("signature")
        else:
            titled = _TITLE_RE.fullmatch(title)
            if titled:
                family, identity = titled.group(1), titled.group(2)
            else:
                family, identity = "unknown", ""
        comments = self._issue_comments(number)
        wire: dict[str, Any] = {
            "number": number,
            "title": title,
            "state": state,
            "labels": _labels(raw.get("labels"), f"issue {number}.labels"),
            "identity_marker": f"release-steward:{family}:{identity}"
            if identity
            else "",
            "family": family,
            "comments": comments,
            "opened_at": _moment(raw.get("created_at"), f"issue {number}.created_at"),
            "updated_at": _moment(raw.get("updated_at"), f"issue {number}.updated_at"),
        }
        if candidate is not None:
            wire["candidate_id"] = candidate
        if pin is not None:
            wire["pin"] = pin
        if sha is not None:
            wire["sha"] = sha
        if signature is not None:
            wire["signature"] = signature
        closed_at = raw.get("closed_at")
        if closed_at is not None:
            wire["closed_at"] = _moment(closed_at, f"issue {number}.closed_at")
        return wire

    def _issue_comments(self, number: int) -> list[dict[str, Any]]:
        pages = self._facts.github.pages(
            f"repos/{self._facts.repo}/issues/{number}/comments",
            params={"per_page": "100"},
        )
        rows: list[Any] = _flatten_pages(pages)
        comments = []
        for index, raw in enumerate(rows):
            if not isinstance(raw, dict):
                raise ReleaseFactsError(
                    f"issue {number} comments[{index}] must be an object"
                )
            body = raw.get("body") or ""
            if not isinstance(body, str):
                raise ReleaseFactsError(
                    f"issue {number} comments[{index}].body must be a string or null"
                )
            tick = _TICK_RE.search(body)
            comments.append(
                {
                    "tick_identity": tick.group(1) if tick else "",
                    "created_at": _moment(
                        raw.get("created_at"),
                        f"issue {number} comments[{index}].created_at",
                    ),
                }
            )
        comments.sort(key=lambda item: (item["created_at"], item["tick_identity"]))
        return comments

    def read_issues(self) -> list[dict[str, Any]]:
        """Read every open and closed steward escalation issue, oldest first."""
        pages = self._facts.github.pages(
            f"repos/{self._facts.repo}/issues",
            params={
                "labels": STEWARD_LABEL,
                "state": "all",
                "sort": "created",
                "direction": "asc",
                "per_page": "100",
            },
        )
        issues = []
        for raw in _flatten_pages(pages):
            if not isinstance(raw, dict):
                raise ReleaseFactsError("escalation issue must be an object")
            if "pull_request" in raw:
                continue
            issues.append(self._issue_wire(raw))
        issues.sort(key=lambda item: (item["opened_at"], item["number"]))
        return issues

    # -- access probe and lineage --------------------------------------------

    def read_core_actions_access(self) -> dict[str, Any]:
        """Probe core Actions read access without claiming dispatch rights."""
        try:
            self._core_transport.json(
                f"repos/{CORE_REPO}/actions/runs", params={"per_page": "1"}
            )
        except ReleaseTransportError as exc:
            return {"readable": False, "detail": str(exc)[:300]}
        return {
            "readable": True,
            "detail": "core Actions run list is readable; "
            "workflow-dispatch scope was not tested",
        }

    @staticmethod
    def derive_blocker_lineage(
        issues: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Name the oldest open marker-bearing issue as the blocked lineage.

        The policy validates the family/identity match and treats any
        mismatch as uncertainty, so an unrelated open issue never invents
        a 24-hour age for the current state.
        """
        for issue in sorted(
            issues, key=lambda item: (item["opened_at"], item["number"])
        ):
            if issue["state"] == "open" and issue["identity_marker"]:
                return {
                    "family": issue["family"],
                    "identity": issue["identity_marker"].split(":", 2)[2],
                    "started_at": issue["opened_at"],
                    "continuous": True,
                    "identity_changed": False,
                }
        return None

    # -- composition ----------------------------------------------------------

    def _envelope(self, source: str, fn: Any, remedy: str) -> dict[str, Any]:
        try:
            return ready(fn())
        except ReleaseTransportError as exc:
            return unreadable(exc.source, str(exc), remedy)
        except (ReleaseFactsError, ValueError) as exc:
            return unreadable(source, str(exc), remedy)

    def collect_health_snapshot(
        self,
        *,
        observed_at: datetime | str,
        master: dict[str, Any] | None,
        release_pr: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the health-owned third of one snapshot from fresh reads.

        *master* and *release_pr* are the train snapshot's values (used
        only for source-pin selection, so both readers agree on the pin
        identity); every health wire is read fresh here.
        """
        now = _coerce_observed_at(observed_at)
        if master is None:
            core_ensure: dict[str, Any] = unreadable(
                "core_ensure",
                "master identity is unreadable",
                "restore the required master facts",
            )
        else:
            core_ensure = self._envelope(
                "core_ensure",
                lambda: self.read_core_ensure(release_pr, master["sha"]),
                "re-read PyPI metadata and the source pin",
            )
        core = self._envelope(
            "core",
            lambda: self.read_core_facts(now),
            "restore read access to sase-core CI, release PR, and core-cut runs",
        )
        canary = self._envelope(
            "canary",
            lambda: self.read_canary(now),
            "restore read access to scheduled install-smoke results",
        )
        issues = self._envelope(
            "issues",
            self.read_issues,
            "restore read access to steward escalation issues",
        )
        access = self._envelope(
            "core_actions_access",
            self.read_core_actions_access,
            "grant the release token read access to sase-core Actions",
        )
        if issues["status"] == "ready":
            lineage: dict[str, Any] = ready(
                self.derive_blocker_lineage(issues["value"])
            )
        else:
            lineage = unreadable(
                "issues",
                "escalation issues are unreadable",
                "restore read access to steward escalation issues",
            )
        return {
            "core": core,
            "canary": canary,
            "core_ensure": core_ensure,
            "issues": issues,
            "core_actions_access": access,
            "blocker_lineage": lineage,
        }


__all__ = [
    "CANARY_WORKFLOW",
    "CORE_CI_WORKFLOW",
    "CORE_CUT_WORKFLOW",
    "CUT_HISTORY_LIMIT",
    "STEWARD_LABEL",
    "ReleaseHealthReader",
    "absent",
    "ready",
    "unreadable",
]
