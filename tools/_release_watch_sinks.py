#!/usr/bin/env python3
"""Write the one Rust-selected release-steward issue operation.

All issue, label, comment, and closure decisions come from the Rust policy.
This module only validates the target again, writes its machine-readable
markers, and reports whether the operation executed or was already satisfied.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from typing import Any

from _release_watch_actions import ActionExecutionError, _gh_env
from _release_watch_transport import GH_TIMEOUT_SECONDS


_ISSUE_MARKER_RE = re.compile(
    r"release-steward:family=(\S+)\s+identity=(\S+)((?:\s+[A-Za-z_]+=\S+)*)"
)
_TICK_RE = re.compile(r"release-steward:tick=(\S+)")
STEWARD_LABEL = "release-steward"


def _run_with_input(
    argv: list[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
    input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = None if env is None else {**os.environ, **env}
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=merged_env,
        input=input,
    )


class ReleaseWatchIssueSink:
    """Apply one preselected issue open, comment, or close operation."""

    def __init__(
        self,
        *,
        github: Any,
        runner: Any = _run_with_input,
        repo: str = "sase-org/sase",
        timeout: float = GH_TIMEOUT_SECONDS,
    ) -> None:
        self.github = github
        self.runner = runner
        self.repo = repo
        self.timeout = timeout

    def execute(
        self,
        escalation: Mapping[str, Any],
        request: Mapping[str, Any],
        decision: Mapping[str, Any],
        *,
        live: bool,
    ) -> tuple[str, str]:
        """Apply one operation and return its disposition and explanation."""
        if not live:
            return "proposed", "observe-only mode does not write issue state"
        if escalation.get("disposition") != "proposed":
            return str(
                escalation.get("disposition", "suppressed")
            ), "operation is not proposed"
        operation = escalation.get("operation")
        if not isinstance(operation, dict) or not isinstance(
            operation.get("kind"), str
        ):
            raise ActionExecutionError(
                "issue_operation", "escalation operation is malformed"
            )

        kind = operation["kind"]
        try:
            if kind == "open":
                return self._open(operation, request, decision)
            if kind == "comment":
                return self._comment(operation, request, decision)
            if kind == "close":
                return self._close(operation, request)
        except ActionExecutionError:
            raise
        except Exception as exc:
            raise ActionExecutionError(
                "issue_sink",
                f"issue operation could not be reconciled: {type(exc).__name__}: {exc}",
            ) from exc
        raise ActionExecutionError(
            "issue_operation", f"unsupported escalation operation {kind!r}"
        )

    def _open(
        self,
        operation: Mapping[str, Any],
        request: Mapping[str, Any],
        decision: Mapping[str, Any],
    ) -> tuple[str, str]:
        family = _text(operation.get("family"), "family")
        title = _text(operation.get("title"), "title")
        identity_marker = _text(operation.get("identity_marker"), "identity_marker")
        fields = _parse_marker(identity_marker)
        if fields is None or fields[0] != family:
            raise ActionExecutionError(
                "issue_identity", "open operation identity marker is malformed"
            )
        labels = operation.get("labels")
        if not isinstance(labels, list) or not all(
            isinstance(item, str) for item in labels
        ):
            raise ActionExecutionError(
                "issue_labels", "open operation labels are malformed"
            )
        if STEWARD_LABEL not in labels:
            raise ActionExecutionError(
                "issue_labels", "open operation omitted release-steward label"
            )
        expected_title = f"release-steward: {family} ({fields[1]})"
        if title != expected_title:
            raise ActionExecutionError(
                "issue_title", "open operation title does not match its identity"
            )

        for issue in self._list_issues():
            if (
                issue.get("state") == "open"
                and "pull_request" not in issue
                and _marker_from_body(issue.get("body")) == identity_marker
            ):
                return (
                    "already_satisfied",
                    f"matching escalation issue #{issue.get('number')} is already open",
                )

        body = _append_issue_marker(
            _text(operation.get("body"), "body"),
            identity_marker,
            _marker_context(decision, request, family, fields[1]),
        )
        payload = {"title": title, "body": body, "labels": labels}
        self._write("POST", f"repos/{self.repo}/issues", payload)
        return "executed", "opened the matching escalation issue"

    def _comment(
        self,
        operation: Mapping[str, Any],
        request: Mapping[str, Any],
        decision: Mapping[str, Any],
    ) -> tuple[str, str]:
        family = _text(operation.get("family"), "family")
        issue_number = _positive_int(operation.get("issue_number"), "issue_number")
        tick_identity = _text(operation.get("tick_identity"), "tick_identity")
        issue = self._issue(issue_number)
        identity_marker = self._expected_issue_marker(request, issue_number, family)
        if issue.get("state") != "open":
            return "suppressed", f"issue #{issue_number} is no longer open"
        if "pull_request" in issue or not _has_label(issue, STEWARD_LABEL):
            return (
                "suppressed",
                f"issue #{issue_number} is not a steward escalation issue",
            )
        if _marker_from_body(issue.get("body")) != identity_marker:
            return (
                "suppressed",
                f"issue #{issue_number} identity changed before comment",
            )
        try:
            comments = self.github.pages(
                f"repos/{self.repo}/issues/{issue_number}/comments",
                params={"per_page": "100"},
            )
        except Exception as exc:
            raise ActionExecutionError(
                "issue_comments",
                f"cannot re-read issue #{issue_number} comments before mutation: {exc}",
            ) from exc
        if any(
            isinstance(comment, dict)
            and isinstance(comment.get("body"), str)
            and _TICK_RE.search(comment["body"])
            and _TICK_RE.search(comment["body"]).group(1) == tick_identity
            for comment in comments
        ):
            return (
                "already_satisfied",
                f"issue #{issue_number} already has tick {tick_identity}",
            )
        body = _append_comment_markers(
            _text(operation.get("body"), "body"),
            tick_identity,
            identity_marker,
            _marker_context(
                decision, request, family, _parse_marker(identity_marker)[1]
            ),
        )
        self._write(
            "POST",
            f"repos/{self.repo}/issues/{issue_number}/comments",
            {"body": body},
        )
        return "executed", f"commented on escalation issue #{issue_number}"

    def _close(
        self,
        operation: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> tuple[str, str]:
        family = _text(operation.get("family"), "family")
        issue_number = _positive_int(operation.get("issue_number"), "issue_number")
        issue = self._issue(issue_number)
        expected_marker = self._expected_issue_marker(request, issue_number, family)
        if "pull_request" in issue or not _has_label(issue, STEWARD_LABEL):
            return (
                "suppressed",
                f"issue #{issue_number} is not a steward escalation issue",
            )
        if _marker_from_body(issue.get("body")) != expected_marker:
            return (
                "suppressed",
                f"issue #{issue_number} identity changed; it was left open",
            )
        if issue.get("state") == "closed":
            return "already_satisfied", f"issue #{issue_number} is already closed"
        if issue.get("state") != "open":
            return "suppressed", f"issue #{issue_number} has an unknown state"
        self._write(
            "PATCH",
            f"repos/{self.repo}/issues/{issue_number}",
            {"state": "closed", "state_reason": "completed"},
        )
        return "executed", f"closed recovered escalation issue #{issue_number}"

    def _list_issues(self) -> list[Any]:
        try:
            return self.github.pages(
                f"repos/{self.repo}/issues",
                params={
                    "labels": STEWARD_LABEL,
                    "state": "all",
                    "sort": "created",
                    "direction": "asc",
                    "per_page": "100",
                },
            )
        except Exception as exc:
            raise ActionExecutionError(
                "issue_read", f"cannot re-read steward issues before mutation: {exc}"
            ) from exc

    def _issue(self, number: int) -> dict[str, Any]:
        try:
            issue = self.github.json(f"repos/{self.repo}/issues/{number}")
        except Exception as exc:
            raise ActionExecutionError(
                "issue_read", f"cannot re-read issue #{number} before mutation: {exc}"
            ) from exc
        if not isinstance(issue, dict) or issue.get("number") != number:
            raise ActionExecutionError(
                "issue_read", f"issue #{number} returned a malformed record"
            )
        return issue

    def _expected_issue_marker(
        self, request: Mapping[str, Any], number: int, family: str
    ) -> str:
        snapshot = request.get("snapshot")
        issue_fact = snapshot.get("issues") if isinstance(snapshot, dict) else None
        rows = issue_fact.get("value") if isinstance(issue_fact, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("number") == number:
                    marker = row.get("identity_marker")
                    marker_fields = _parse_marker(marker)
                    if marker_fields is not None and marker_fields[0] == family:
                        return marker
        raise ActionExecutionError(
            "issue_revalidation",
            f"fresh snapshot does not identify issue #{number} as {family}",
        )

    def _write(self, method: str, endpoint: str, payload: dict[str, Any]) -> None:
        argv = ["gh", "api", "--method", method, endpoint, "--input", "-"]
        try:
            proc = self.runner(
                argv,
                timeout=self.timeout,
                env=_gh_env(self.repo),
                input=json.dumps(payload, sort_keys=True),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ActionExecutionError(
                "issue_acknowledgement",
                f"issue mutation acknowledgement is uncertain: {exc}",
                uncertain=True,
            ) from exc
        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "").strip().replace("\n", " ")
            raise ActionExecutionError(
                "issue_acknowledgement",
                "issue mutation returned an uncertain failure"
                + (f": {details[:300]}" if details else ""),
                uncertain=True,
            )


def _marker_context(
    decision: Mapping[str, Any],
    request: Mapping[str, Any],
    family: str,
    identity: str,
) -> dict[str, str]:
    states = [decision.get("primary")]
    secondary = decision.get("secondary")
    if isinstance(secondary, list):
        states.extend(item.get("state") for item in secondary if isinstance(item, dict))
    state = next(
        (
            item
            for item in states
            if isinstance(item, dict) and item.get("kind") == family
        ),
        {},
    )
    snapshot = request.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    context: dict[str, str] = {}
    candidate_fact = snapshot.get("candidate")
    candidate = (
        candidate_fact.get("value")
        if isinstance(candidate_fact, dict) and candidate_fact.get("status") == "ready"
        else None
    )
    candidate_id = state.get("candidate_id") if isinstance(state, dict) else None
    if not isinstance(candidate_id, str) and isinstance(candidate, dict):
        candidate_id = candidate.get("candidate_id")
    trains_fact = snapshot.get("trains")
    trains = trains_fact.get("value") if isinstance(trains_fact, dict) else None
    if isinstance(trains, list) and isinstance(candidate_id, str):
        candidate = next(
            (
                item
                for item in trains
                if isinstance(item, dict) and item.get("candidate_id") == candidate_id
            ),
            candidate,
        )
    if isinstance(candidate_id, str) and candidate_id:
        context["candidate"] = candidate_id
    if isinstance(candidate, dict):
        version = candidate.get("version")
        if (
            isinstance(version, str)
            and version
            and not any(ch.isspace() for ch in version)
        ):
            context["version"] = version
    pin = state.get("pin") if isinstance(state, dict) else None
    sha = state.get("sha") if isinstance(state, dict) else None
    signature = state.get("signature") if isinstance(state, dict) else None
    release_pr = snapshot.get("release_pr")
    pr = release_pr.get("value") if isinstance(release_pr, dict) else None
    if isinstance(pr, dict):
        pin = pin or pr.get("source_pin")
        sha = sha or pr.get("head_sha")
    master_fact = snapshot.get("master")
    master = master_fact.get("value") if isinstance(master_fact, dict) else None
    if isinstance(master, dict):
        sha = sha or master.get("sha")
    for key, value in (("pin", pin), ("sha", sha), ("signature", signature)):
        if isinstance(value, str) and value and not any(ch.isspace() for ch in value):
            context[key] = value
    observed = request.get("observed_at")
    if isinstance(observed, str) and observed:
        context["observed_at"] = observed
    started = decision.get("blocker_started_at")
    if isinstance(started, str) and started:
        context["blocker_started_at"] = started
    evidence = decision.get("evidence")
    if isinstance(evidence, list) and evidence:
        context["evidence_count"] = str(len(evidence))
    # The state identity is always retained for a marker even when no extra
    # source has a candidate, pin, or SHA to attach.
    context.setdefault("family", family)
    context.setdefault("identity", identity)
    return context


def _append_issue_marker(body: str, marker: str, context: Mapping[str, str]) -> str:
    family, identity = _parse_marker(marker) or ("unknown", "unknown")
    values = {"family": family, "identity": identity, **context}
    rendered = " ".join(f"{key}={value}" for key, value in values.items())
    return f"{body.rstrip()}\n\n<!-- release-steward:{rendered} -->"


def _append_comment_markers(
    body: str,
    tick: str,
    marker: str,
    context: Mapping[str, str],
) -> str:
    family, identity = _parse_marker(marker) or ("unknown", "unknown")
    values = {"family": family, "identity": identity, **context}
    rendered = " ".join(f"{key}={value}" for key, value in values.items())
    return (
        f"{body.rstrip()}\n\n<!-- release-steward:tick={tick} -->"
        f"\n<!-- release-steward:{rendered} -->"
    )


def _marker_from_body(body: object) -> str | None:
    if not isinstance(body, str):
        return None
    match = _ISSUE_MARKER_RE.search(body)
    if not match:
        return None
    return f"release-steward:{match.group(1)}:{match.group(2)}"


def _parse_marker(marker: object) -> tuple[str, str] | None:
    if not isinstance(marker, str):
        return None
    match = re.fullmatch(r"release-steward:([^:\s]+):([^\s]+)", marker)
    if not match:
        return None
    return match.group(1), match.group(2)


def _has_label(issue: Mapping[str, Any], label: str) -> bool:
    labels = issue.get("labels")
    return isinstance(labels, list) and any(
        isinstance(item, dict)
        and item.get("name") == label
        or isinstance(item, str)
        and item == label
        for item in labels
    )


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ActionExecutionError(name, f"{name} must be a positive integer")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ActionExecutionError(name, f"{name} must be a non-empty string")
    return value


__all__ = ["ReleaseWatchIssueSink"]
