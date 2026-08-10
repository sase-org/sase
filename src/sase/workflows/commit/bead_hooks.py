"""Commit-time bead tagging, synchronization, and autoclose handling."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.bead.project import BEADS_DIRNAME
from sase.output import print_status
from sase.workflows.commit.hook_utils import get_repo_root

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_AUTOCLOSE_METHODS = frozenset({"create_commit", "create_pull_request"})
_SDD_REPO_ENV_VARS = (
    "SASE_SDD_DIR",
    "SASE_SDD_PLANS_DIR",
    "SASE_SDD_BEADS_DIR",
    "SASE_SDD_RESEARCH_DIR",
)


@dataclass(frozen=True)
class _AutocloseDecision:
    """Decision for commit-time task bead autoclose."""

    bead_id: str | None
    should_close: bool
    reason: str
    status: str | None = None
    issue_type: str | None = None
    warn: bool = False


def apply_bead_commit_tag(
    payload: dict,
    *,
    store: SddStore | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> None:
    """Append or update the payload's linked ``SASE_BEAD`` footer tag."""

    bead_id = payload.get("bead_id")
    if not bead_id:
        return

    from sase.bead_pages.links import resolve_bead_commit_tag
    from sase.workflows.commit.runtime_tags import (
        parse_trailing_commit_tag_values,
        update_trailing_commit_tags,
    )

    message = str(payload.get("message", "") or "")
    bead_value = resolve_bead_commit_tag(str(bead_id), store=store, cwd=cwd)
    existing = parse_trailing_commit_tag_values(message)
    updates = {
        "BEAD": bead_value,
        **{key: value for key, value in existing.items() if key != "BEAD"},
    }
    payload["message"] = update_trailing_commit_tags(
        message,
        updates,
        remove_keys=set(existing) | {"BEAD"},
    )


def handle_beads(payload: dict, cwd: str, *, method: str = "create_commit") -> None:
    """Sync beads best-effort and report assigned beads that will not auto-close.

    Only an ``in_progress`` task bead assigned to a commit in this workspace's
    primary repo is eligible for post-dispatch autoclose. Phase, plan, epic, linked-repo,
    and SDD-sidecar commits stay warning-only so a mid-flight commit cannot close the
    wrong lifecycle object.
    """
    bead_id = payload.get("bead_id")
    has_bead_dir = (
        os.path.isdir(os.path.join(cwd, BEADS_DIRNAME))
        or os.path.isdir(os.path.join(cwd, ".beads"))
        or os.path.isdir(os.path.join(cwd, "sase", "repos", "beads"))
    )

    if bead_id:
        decision = _resolve_task_bead_autoclose(payload, cwd, method=method)
        if not decision.should_close:
            _report_unclosed_bead(decision)

    if bead_id or has_bead_dir:
        # Sync beads (best effort)
        _run_bead_command(["sase", "bead", "sync"], cwd)


def _run_bead_command(
    args: list[str], cwd: str
) -> subprocess.CompletedProcess[bytes] | None:
    """Run a bead command best-effort, tolerating missing sase binary."""
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        print_status("Skipping bead command: `sase` CLI not found.", "warning")
        return None


def _resolve_task_bead_autoclose(
    payload: dict,
    cwd: str,
    *,
    method: str = "create_commit",
) -> _AutocloseDecision:
    """Return whether the assigned task bead should auto-close after commit."""
    raw_bead_id = payload.get("bead_id")
    bead_id = str(raw_bead_id).strip() if raw_bead_id else ""
    if not bead_id:
        return _AutocloseDecision(None, False, "no bead is assigned")
    if method not in _AUTOCLOSE_METHODS:
        return _AutocloseDecision(
            bead_id,
            False,
            f"{method} does not create a landed commit",
        )

    issue = _resolve_bead_issue(bead_id, cwd)
    if issue is None:
        return _AutocloseDecision(
            bead_id,
            False,
            "the bead status could not be read",
            warn=True,
        )

    status = _issue_text(issue, "status")
    issue_type = _issue_text(issue, "issue_type")
    if status is None:
        return _AutocloseDecision(
            bead_id,
            False,
            "the bead status could not be read",
            issue_type=issue_type,
            warn=True,
        )

    warn = status != "closed"
    if payload.get("do_not_close_bead"):
        return _AutocloseDecision(
            bead_id,
            False,
            "the do-not-close opt-out was used",
            status=status,
            issue_type=issue_type,
            warn=warn,
        )
    if issue_type != "task":
        return _AutocloseDecision(
            bead_id,
            False,
            _not_task_reason(issue_type),
            status=status,
            issue_type=issue_type,
            warn=warn,
        )
    if status != "in_progress":
        return _AutocloseDecision(
            bead_id,
            False,
            f"it is {status}",
            status=status,
            issue_type=issue_type,
            warn=warn,
        )

    repo_skip_reason = _repo_autoclose_skip_reason(cwd)
    if repo_skip_reason is not None:
        return _AutocloseDecision(
            bead_id,
            False,
            repo_skip_reason,
            status=status,
            issue_type=issue_type,
            warn=warn,
        )

    return _AutocloseDecision(
        bead_id,
        True,
        "eligible in-progress task bead in the primary repo",
        status=status,
        issue_type=issue_type,
    )


def close_task_bead_after_commit(payload: dict, cwd: str, *, method: str) -> bool:
    """Best-effort close for an eligible assigned task bead after a commit lands."""
    decision = _resolve_task_bead_autoclose(payload, cwd, method=method)
    if not decision.should_close or not decision.bead_id:
        return False

    note = _autoclose_note(decision.bead_id, payload, cwd, method=method)
    result = _run_bead_command(
        [
            "sase",
            "bead",
            "close",
            decision.bead_id,
            "--resolution",
            "done",
            "--note",
            note,
        ],
        cwd,
    )
    if result is not None and result.returncode == 0:
        print_status(
            f"Auto-closed task bead {decision.bead_id}. Reopen with "
            f"`sase bead open {decision.bead_id}` if more work remains.",
            "success",
        )
        return True

    _report_autoclose_failed(decision, result)
    return False


def _report_unclosed_bead(decision: _AutocloseDecision) -> None:
    """Warn when an assigned bead remains open after autoclose was skipped."""
    if not decision.warn or not decision.bead_id:
        return
    status = f" is still {decision.status}" if decision.status else " status is unknown"
    print_status(
        f"Bead {decision.bead_id}{status}; this commit will not auto-close it "
        f"because {decision.reason}. Run "
        f'`sase bead close {decision.bead_id} --note "<what you verified>"` '
        "once the work is actually done.",
        "warning",
    )


def _report_autoclose_failed(
    decision: _AutocloseDecision,
    result: subprocess.CompletedProcess[bytes] | None,
) -> None:
    detail = (
        "the `sase` CLI was not found"
        if result is None
        else (f"`sase bead close` exited {result.returncode}")
    )
    output = ""
    if result is not None:
        output = _decoded_command_output(result.stderr) or _decoded_command_output(
            result.stdout
        )
        if output:
            output = f": {_truncate_for_status(output)}"
    print_status(
        f"Auto-close failed for task bead {decision.bead_id}: {detail}{output}. "
        f'Run `sase bead close {decision.bead_id} --note "<what you verified>"` '
        "once the work is actually done.",
        "warning",
    )


def _resolve_bead_issue(bead_id: str, cwd: str) -> dict[str, object] | None:
    """Return *bead_id*'s issue dict, or ``None`` when it cannot be determined."""
    result = _run_bead_command(
        ["sase", "bead", "show", bead_id, "--format", "json"], cwd
    )
    if result is None or result.returncode != 0:
        return None
    try:
        detail = json.loads(_decoded_command_output(result.stdout))
    except ValueError:
        return None
    issue = detail.get("issue") if isinstance(detail, dict) else None
    if not isinstance(issue, dict):
        return None
    return {str(key): value for key, value in issue.items()}


def _issue_text(issue: dict[str, object], key: str) -> str | None:
    value = issue.get(key)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _not_task_reason(issue_type: str | None) -> str:
    if issue_type:
        return f"it is a {issue_type} bead"
    return "it is not a task bead"


def _repo_autoclose_skip_reason(cwd: str) -> str | None:
    try:
        repo_root = get_repo_root(cwd)
        if not repo_root:
            return "the repository root could not be resolved"
        repo_real = os.path.realpath(repo_root)
        for denied in _autoclose_denylist_paths():
            if os.path.realpath(denied) == repo_real:
                return "the commit is in a linked repository or SDD sidecar"
    except Exception:
        return "the repository root could not be resolved"
    return None


def _autoclose_denylist_paths() -> list[str]:
    paths: list[str] = []
    from sase._linked_repo_env import (
        LINKED_REPO_ENV_PREFIX,
        LINKED_REPO_ENV_SUFFIXES,
        SIBLING_REPO_ENV_PREFIX,
        SIBLING_REPO_ENV_SUFFIXES,
        linked_repo_metadata_from_env,
    )

    for item in linked_repo_metadata_from_env():
        for key in ("workspace_dir", "primary_dir"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value.strip())
    for key, value in os.environ.items():
        if (
            (
                key.startswith(LINKED_REPO_ENV_PREFIX)
                and key.endswith(LINKED_REPO_ENV_SUFFIXES)
            )
            or (
                key.startswith(SIBLING_REPO_ENV_PREFIX)
                and key.endswith(SIBLING_REPO_ENV_SUFFIXES)
            )
        ) and value.strip():
            paths.append(value.strip())

    for key in _SDD_REPO_ENV_VARS:
        value = os.environ.get(key, "").strip()
        if value:
            paths.append(value)
    return paths


def _autoclose_note(
    bead_id: str,
    payload: dict,
    cwd: str,
    *,
    method: str,
) -> str:
    subject = _commit_subject(payload)
    sha = _resolve_short_head(cwd)
    landed = f"{method} landed"
    if sha:
        landed = f"{landed} {sha}"
    if subject:
        landed = f'{landed} ("{subject}")'
    return (
        f"Auto-closed by `sase stitch create` after {landed}. No verification is implied "
        f"by this note. Reopen with `sase bead open {bead_id}`, or pass "
        "`-B|--do-not-close-bead` on mid-flight commits."
    )


def _commit_subject(payload: dict) -> str:
    message = str(payload.get("message") or "")
    for line in message.splitlines():
        subject = line.strip()
        if subject:
            return subject
    return ""


def _resolve_short_head(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _truncate_for_status(text: str, *, limit: int = 240) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= limit:
        return flattened
    return f"{flattened[: limit - 3]}..."


def _decoded_command_output(output: bytes | str | object) -> str:
    if isinstance(output, bytes):
        return output.decode(errors="replace").strip()
    if isinstance(output, str):
        return output.strip()
    return ""
