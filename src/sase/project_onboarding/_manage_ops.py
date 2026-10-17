"""Shared helpers for journaled SASE management setup."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import subprocess
from typing import Any

from sase.config import set_key
from sase.project_management import enable_sase_management, project_management_status
from sase.project_onboarding.journal import update_management
from sase.project_onboarding.manage_git import (
    CONFIG_RELATIVE,
    GIT_TIMEOUT_SECONDS,
    ManagementError,
    PUSH_TIMEOUT_SECONDS,
    failure_message,
    read_config,
    run_git,
    sha256,
)

MANAGEMENT_COMMIT_MESSAGE = "chore: mark repository as SASE-managed"


def write_evidence(
    identity_key: str,
    fingerprint: str,
    display: str,
    *,
    stage: str,
    **updates: Any,
) -> None:
    update_management(
        identity_key,
        fingerprint,
        display=display,
        stage=stage,
        **updates,
    )


def prepare_and_write_marker(
    checkout: Path,
    config_path: Path,
    state: Mapping[str, Any],
    *,
    journal_key: str,
    intent_fingerprint: str,
    display: str,
) -> tuple[str, str, str]:
    current_bytes = read_config(config_path)
    current_hash = sha256(current_bytes)
    try:
        current_text = current_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManagementError("sase/sase.yml is not valid UTF-8") from exc
    try:
        expected_bytes = set_key(current_text, ("is_sase_managed",), True).encode(
            "utf-8"
        )
    except Exception as exc:
        raise ManagementError(f"could not prepare sase/sase.yml: {exc}") from exc
    expected_hash = sha256(expected_bytes)
    baseline_hash = str(state.get("baseline_config_hash") or "")
    stored_expected_hash = str(state.get("expected_config_hash") or "")
    if stored_expected_hash:
        if expected_hash != stored_expected_hash:
            raise ManagementError(
                "sase/sase.yml changed after the recorded marker write; "
                "preserve the edit and resolve it before retrying"
            )
        baseline_hash = baseline_hash or current_hash
        if current_hash not in {baseline_hash, stored_expected_hash}:
            raise ManagementError(
                "sase/sase.yml no longer matches the recorded recovery bytes"
            )
        expected_hash = stored_expected_hash
    else:
        if _path_is_dirty(checkout):
            raise ManagementError(
                "sase/sase.yml has local edits; commit or stash them, then retry"
            )
        baseline_hash = current_hash
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="prepared",
            baseline_config_hash=baseline_hash,
            expected_config_hash=expected_hash,
            current_config_hash=current_hash,
            marker_write_stage="prepared",
        )

    # A prior response may have been lost after the file write. Exact expected
    # bytes are sufficient to advance; anything else is treated as user work.
    if current_hash != expected_hash:
        if current_hash != baseline_hash:
            raise ManagementError(
                "sase/sase.yml has edits outside this onboarding marker"
            )
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="write_started",
            marker_write_stage="write_started",
        )
        marker_update = enable_sase_management(config_path)
        current_bytes = read_config(config_path)
        current_hash = sha256(current_bytes)
        if current_hash != expected_hash:
            detail = f": {marker_update.error}" if marker_update.error else ""
            raise ManagementError("failed to write the expected SASE marker" + detail)
    else:
        current_bytes = read_config(config_path)
        current_hash = sha256(current_bytes)

    if not project_management_status(config_path).is_sase_managed:
        raise ManagementError("the local SASE management marker is not valid")
    write_evidence(
        journal_key,
        intent_fingerprint,
        display,
        stage="marker_written",
        marker_written=True,
        marker_write_stage="written",
        current_config_hash=current_hash,
    )
    return expected_hash, baseline_hash, current_hash


def stage_config(checkout: Path, config_path: Path, expected_hash: str) -> None:
    if _path_is_dirty(checkout) and sha256(read_config(config_path)) != expected_hash:
        raise ManagementError("sase/sase.yml changed before it could be staged")
    _run_checked(checkout, "stage SASE marker", "add", "--", str(CONFIG_RELATIVE))
    staged = run_git(
        checkout,
        "show",
        f":{CONFIG_RELATIVE.as_posix()}",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if staged.returncode != 0 or sha256(staged.stdout.encode("utf-8")) != expected_hash:
        raise ManagementError("the staged SASE marker does not match the journal")


def find_expected_commit(
    checkout: Path,
    parent: str,
    content_hash: str,
    message: str,
    preferred: str,
) -> str:
    if preferred and valid_expected_commit(
        checkout, preferred, parent, content_hash, message
    ):
        return preferred
    result = run_git(
        checkout,
        "log",
        "--all",
        "--format=%H%x00%P%x00%s",
        "-n",
        "100",
        "--",
        str(CONFIG_RELATIVE),
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return ""
    for row in result.stdout.splitlines():
        parts = row.split("\x00", 2)
        if len(parts) != 3:
            continue
        commit_id, parents, subject = parts
        if (
            parents == parent
            and subject == message
            and valid_expected_commit(
                checkout, commit_id, parent, content_hash, message
            )
        ):
            return commit_id
    return ""


def valid_expected_commit(
    checkout: Path,
    commit_id: str,
    parent: str,
    content_hash: str,
    message: str,
) -> bool:
    if not commit_id:
        return False
    metadata = run_git(
        checkout,
        "show",
        "-s",
        "--format=%P%x00%s",
        commit_id,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if metadata.returncode != 0:
        return False
    fields = metadata.stdout.rstrip("\n").split("\x00", 1)
    if fields != [parent, message]:
        return False
    paths = run_git(
        checkout,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit_id,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if paths.returncode != 0 or paths.stdout.splitlines() != [
        CONFIG_RELATIVE.as_posix()
    ]:
        return False
    content = run_git(
        checkout,
        "show",
        f"{commit_id}:{CONFIG_RELATIVE.as_posix()}",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    return (
        content.returncode == 0
        and sha256(content.stdout.encode("utf-8")) == content_hash
    )


def git_output(checkout: Path, *args: str, action: str) -> str:
    result = run_git(checkout, *args, timeout=GIT_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise ManagementError(failure_message(action, result))
    return result.stdout.strip()


def commit_management_marker(checkout: Path) -> subprocess.CompletedProcess[str]:
    return run_git(
        checkout,
        "commit",
        "--only",
        "-m",
        MANAGEMENT_COMMIT_MESSAGE,
        "--",
        str(CONFIG_RELATIVE),
        timeout=GIT_TIMEOUT_SECONDS,
    )


def push_management_marker(
    checkout: Path, commit_id: str, branch: str
) -> subprocess.CompletedProcess[str]:
    return run_git(
        checkout,
        "push",
        "origin",
        f"{commit_id}:refs/heads/{branch}",
        timeout=PUSH_TIMEOUT_SECONDS,
    )


def success(commit_id: str, *, changed: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "changed": changed,
        "commit_id": commit_id,
        "pushed": True,
        "message": "repository is SASE-managed",
    }


def _path_is_dirty(checkout: Path) -> bool:
    result = run_git(
        checkout,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        str(CONFIG_RELATIVE),
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ManagementError(failure_message("inspect SASE config status", result))
    return bool(result.stdout.strip())


def _run_checked(
    checkout: Path, label: str, *args: str
) -> subprocess.CompletedProcess[str]:
    result = run_git(checkout, *args, timeout=GIT_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise ManagementError(failure_message(label, result))
    return result


__all__ = [
    "MANAGEMENT_COMMIT_MESSAGE",
    "commit_management_marker",
    "find_expected_commit",
    "git_output",
    "prepare_and_write_marker",
    "push_management_marker",
    "stage_config",
    "success",
    "valid_expected_commit",
    "write_evidence",
]
