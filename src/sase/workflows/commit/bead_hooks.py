"""Commit-time bead tagging, synchronization, and explicit close handling."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.bead.project import BEADS_DIRNAME
from sase.core.bead_action_facade import (
    bead_action_wire_schema_version,
    decide_bead_action,
    parse_bead_action_field,
)
from sase.env_contracts import WORKSPACE_PIN_ENV_VARS
from sase.output import print_status
from sase.workflows.commit.hook_utils import get_repo_root

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_SDD_REPO_ENV_VARS = (
    "SASE_SDD_DIR",
    "SASE_SDD_PLANS_DIR",
    "SASE_SDD_BEADS_DIR",
    "SASE_SDD_RESEARCH_DIR",
)


@dataclass(frozen=True)
class _RepositoryPolicyFacts:
    """Repository facts passed into the core bead-action policy."""

    scope: str
    primary_identified: bool


class BeadActionPolicyError(RuntimeError):
    """Raised when explicit bead-action policy refuses the workflow."""


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
    """Sync beads best-effort after the workflow-level bead-action preflight."""
    del method
    bead_id = payload.get("bead_id")
    has_bead_dir = (
        os.path.isdir(os.path.join(cwd, BEADS_DIRNAME))
        or os.path.isdir(os.path.join(cwd, ".beads"))
        or os.path.isdir(os.path.join(cwd, "sase", "repos", "beads"))
    )

    if bead_id or has_bead_dir:
        _run_bead_command(["sase", "bead", "sync"], cwd)


def validate_bead_action_before_commit(
    payload: dict,
    cwd: str,
    *,
    method: str = "create_commit",
) -> bool:
    """Return whether bead-action policy allows this workflow to start."""

    try:
        decision = _bead_action_decision(payload, cwd, method=method)
    except (TypeError, ValueError, BeadActionPolicyError) as exc:
        print_status(str(exc), "error")
        return False

    disposition = str(decision.get("disposition") or "")
    bead_id = decision.get("bead_id")
    if disposition == "keep" and isinstance(bead_id, str) and bead_id:
        print_status(
            f"Bead {bead_id} will be left unchanged by explicit -B keep.",
            "info",
        )
    elif disposition == "close" and isinstance(bead_id, str) and bead_id:
        print_status(
            f"Bead {bead_id} will be closed after the commit because -B close "
            "was requested.",
            "info",
        )
    elif disposition == "close_idempotent" and isinstance(bead_id, str) and bead_id:
        print_status(
            f"Bead {bead_id} is already closed; explicit -B close is idempotent.",
            "info",
        )
    return True


def close_assigned_bead_after_commit(
    payload: dict,
    cwd: str,
    *,
    method: str,
    strict: bool = False,
) -> bool:
    """Close the assigned bead only for an explicit allowed ``-B close``."""

    try:
        decision = _bead_action_decision(payload, cwd, method=method)
    except (TypeError, ValueError, BeadActionPolicyError) as exc:
        message = f"Bead close refused: {exc}"
        if strict:
            raise BeadActionPolicyError(message) from exc
        print_status(message, "warning")
        return False

    bead_id = decision.get("bead_id")
    if decision.get("disposition") == "close_idempotent" and isinstance(bead_id, str):
        print_status(
            f"Explicit bead close for {bead_id} is already satisfied.",
            "info",
        )
        return True
    if not decision.get("close_bead") or not isinstance(bead_id, str) or not bead_id:
        return False

    note = _explicit_close_note(bead_id, payload, cwd, method=method)
    result = _run_bead_command(
        [
            "sase",
            "bead",
            "close",
            bead_id,
            "--resolution",
            "done",
            "--note",
            note,
        ],
        cwd,
    )
    if result is not None and result.returncode == 0:
        print_status(
            f"Closed assigned bead {bead_id} after explicit -B close.",
            "success",
        )
        return True

    message = _close_failed_message(bead_id, result)
    print_status(message, "warning")
    if strict:
        raise BeadActionPolicyError(message)
    return False


def _bead_action_decision(
    payload: dict,
    cwd: str,
    *,
    method: str,
) -> dict[str, object]:
    """Collect Python facts and delegate bead-action policy to Rust."""

    raw_bead_id = payload.get("bead_id")
    bead_id = str(raw_bead_id).strip() if raw_bead_id else ""
    facts = _repository_policy_facts(cwd)
    request: dict[str, object] = {
        "schema_version": bead_action_wire_schema_version(),
        "commit_method": method,
        "repository_scope": facts.scope,
        "primary_repository_identified": facts.primary_identified,
        "legacy_do_not_close_bead": "do_not_close_bead" in payload,
    }
    if bead_id:
        request["assigned_bead_id"] = bead_id
    bead_action = parse_bead_action_field(payload)
    if "bead_action" in payload:
        request["bead_action"] = bead_action
    if bead_action == "close":
        request["bead_status"] = _bead_status_fact(bead_id, cwd)
    return decide_bead_action(request)


def _bead_status_fact(bead_id: str, cwd: str) -> str:
    if not bead_id:
        return "unchecked"
    issue = _resolve_bead_issue(bead_id, cwd)
    if issue is None:
        return "unreadable"
    status = _issue_text(issue, "status")
    if status == "in_progress":
        return "in_progress"
    if status == "closed":
        return "closed"
    if status:
        return "other"
    return "unreadable"


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


def _repository_policy_facts(cwd: str) -> _RepositoryPolicyFacts:
    try:
        repo_root = get_repo_root(cwd)
        if not repo_root:
            return _RepositoryPolicyFacts("unknown", False)
        repo_real = os.path.realpath(repo_root)
        for path, scope in _non_primary_scope_paths():
            if os.path.realpath(path) == repo_real:
                return _RepositoryPolicyFacts(scope, False)
        for path in _primary_workspace_paths():
            if os.path.realpath(path) == repo_real:
                return _RepositoryPolicyFacts("primary", True)
    except Exception:
        return _RepositoryPolicyFacts("unknown", False)
    return _RepositoryPolicyFacts("unknown", False)


def _primary_workspace_paths() -> list[str]:
    return [
        value.strip()
        for key in WORKSPACE_PIN_ENV_VARS
        if (value := os.environ.get(key, "")).strip()
    ]


def _non_primary_scope_paths() -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    from sase._linked_repo_env import (
        LINKED_REPO_ENV_PREFIX,
        LINKED_REPO_ENV_SUFFIXES,
        SIBLING_REPO_ENV_PREFIX,
        SIBLING_REPO_ENV_SUFFIXES,
        linked_repo_metadata_from_env,
    )

    for item in linked_repo_metadata_from_env():
        scope = "sdd" if item.get("kind") == "sidecar" else "linked"
        for key in ("workspace_dir", "primary_dir"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                paths.append((value.strip(), scope))
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
            paths.append((value.strip(), "linked"))

    for key in _SDD_REPO_ENV_VARS:
        value = os.environ.get(key, "").strip()
        if value:
            paths.append((value, "sdd"))
    return paths


def _explicit_close_note(
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
        f"Closed by explicit `sase stitch create -B close` after {landed}. "
        "The commit author requested bead completion after verifying the bead scope. "
        f"Reopen with `sase bead open {bead_id}` if more work remains."
    )


def _close_failed_message(
    bead_id: str,
    result: subprocess.CompletedProcess[bytes] | None,
) -> str:
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
    return (
        f"Explicit close failed for bead {bead_id}: {detail}{output}. The commit "
        "may already exist; fix the bead close failure, then run "
        "`sase stitch create --resume`."
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
