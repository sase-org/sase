"""Empty-origin root-commit path for SASE management setup."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.project_onboarding._manage_ops import (
    MANAGEMENT_COMMIT_MESSAGE,
    commit_management_marker,
    find_expected_commit,
    git_output,
    prepare_and_write_marker,
    push_management_marker,
    stage_config,
    success,
    valid_expected_commit,
    write_evidence,
)
from sase.project_onboarding.manage_git import (
    ManagementError,
    align_unborn_head,
    born_head,
    choose_empty_origin_branch,
    ensure_upstream,
    failure_message,
    remote_heads,
)


def manage_empty_origin(
    checkout: Path,
    config_path: Path,
    remote: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    journal_key: str,
    intent_fingerprint: str,
    display: str,
) -> dict[str, Any]:
    branch = choose_empty_origin_branch(checkout, remote, state)
    align_unborn_head(checkout, branch)
    expected_hash, _baseline_hash, _current_hash = prepare_and_write_marker(
        checkout,
        config_path,
        state,
        journal_key=journal_key,
        intent_fingerprint=intent_fingerprint,
        display=display,
    )
    head = born_head(checkout)
    if head and not valid_expected_commit(
        checkout, head, "", expected_hash, MANAGEMENT_COMMIT_MESSAGE
    ):
        raise ManagementError(
            "the checkout already has local commits but origin is empty; "
            "push or remove them, then retry setup"
        )
    if str(state.get("commit_content_hash") or expected_hash) != expected_hash:
        raise ManagementError("the recorded marker commit content does not match")
    write_evidence(
        journal_key,
        intent_fingerprint,
        display,
        stage="prepared",
        root_commit=True,
        commit_branch=branch,
        commit_parent="",
        commit_content_hash=expected_hash,
        commit_message=MANAGEMENT_COMMIT_MESSAGE,
    )
    prior_commit = str(state.get("commit_id") or "")
    commit_id = find_expected_commit(
        checkout,
        "",
        expected_hash,
        str(state.get("commit_message") or MANAGEMENT_COMMIT_MESSAGE),
        prior_commit,
    )
    if not commit_id:
        if born_head(checkout):
            raise ManagementError(
                "the checkout branch changed before the marker commit; "
                "no replacement commit was created"
            )
        if remote_heads(checkout):
            raise ManagementError(
                "origin received commits while setup was creating the first commit; "
                "the local marker commit is preserved, and nothing was pushed"
            )
        stage_config(checkout, config_path, expected_hash)
        if remote_heads(checkout):
            raise ManagementError(
                "origin received commits while setup was creating the first commit; "
                "the local marker commit is preserved, and nothing was pushed"
            )
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="commit_started",
        )
        result = commit_management_marker(checkout)
        if result.returncode != 0:
            commit_id = find_expected_commit(
                checkout,
                "",
                expected_hash,
                MANAGEMENT_COMMIT_MESSAGE,
                "",
            )
            if not commit_id:
                raise ManagementError(
                    failure_message("commit SASE management marker", result)
                )
        else:
            commit_id = git_output(
                checkout, "rev-parse", "HEAD", action="read marker commit"
            )
            if not valid_expected_commit(
                checkout,
                commit_id,
                "",
                expected_hash,
                MANAGEMENT_COMMIT_MESSAGE,
            ):
                raise ManagementError(
                    "Git created a commit that does not contain only the expected marker"
                )
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="committed",
            commit_id=commit_id,
        )
    else:
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="committed",
            commit_id=commit_id,
        )

    heads = remote_heads(checkout)
    branch_ref = f"refs/heads/{branch}"
    if heads.get(branch_ref) == commit_id:
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="push_verified",
            push_expected_oid=commit_id,
            push_verified=True,
            pushed=True,
        )
        ensure_upstream(checkout, branch)
        return success(commit_id, changed=True)
    if heads:
        raise ManagementError(
            "origin received commits while setup was creating the first commit; "
            "the local marker commit is preserved, and nothing was pushed"
        )

    write_evidence(
        journal_key,
        intent_fingerprint,
        display,
        stage="push_started",
        push_expected_oid=commit_id,
    )
    result = push_management_marker(checkout, commit_id, branch)
    verified_oid = remote_heads(checkout).get(branch_ref, "")
    if verified_oid != commit_id:
        reason = failure_message("push SASE management marker", result)
        raise ManagementError(
            f"{reason}. The local marker commit is preserved. A protected default "
            "branch may require a pull request or a human to run `sase init -M`."
        )
    write_evidence(
        journal_key,
        intent_fingerprint,
        display,
        stage="push_verified",
        push_expected_oid=commit_id,
        push_verified=True,
        pushed=True,
    )
    ensure_upstream(checkout, branch)
    return success(commit_id, changed=True)


__all__ = ["manage_empty_origin"]
