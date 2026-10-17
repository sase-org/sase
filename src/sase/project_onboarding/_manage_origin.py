"""Non-empty origin path for journaled SASE management setup."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase import workspace_provider
from sase.project_management import project_management_status
from sase.project_onboarding import _manage_ops as manage_ops
from sase.project_onboarding._manage_empty import manage_empty_origin
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
from sase.project_onboarding.discovery import identity_for_origin, resolve_git_dir
from sase.project_onboarding.journal import lookup_journal
from sase.project_onboarding.manage_git import (
    CONFIG_RELATIVE,
    GIT_TIMEOUT_SECONDS,
    ManagementError,
    failure_message,
    normalize_branch,
    remote_oid,
    should_manage_empty_origin,
)


def manage_repository(
    target: Mapping[str, Any],
    remote: Mapping[str, Any],
    *,
    intent_fingerprint: str,
    journal_identity_key: str = "",
) -> dict[str, Any]:
    """Ensure the matching onboarding intent's management marker is pushed.

    Only ``sase/sase.yml`` is staged and committed. The journal records the
    expected bytes and commit parent before effects, so retries can identify a
    completed write, commit, or push without repeating it.
    """

    identity_key = str(target.get("identity_key") or "").strip()
    journal_key = journal_identity_key.strip() or identity_key
    display = str(target.get("display") or target.get("ref") or identity_key)
    workflow_type = str(target.get("workflow_type") or "")
    checkout_raw = str(target.get("checkout_dir") or "").strip()
    checkout = Path(checkout_raw).expanduser() if checkout_raw else None
    if not identity_key or not intent_fingerprint or checkout is None:
        raise ManagementError(
            "management requires a target identity, checkout, and intent"
        )
    if resolve_git_dir(checkout) is None:
        raise ManagementError(f"{checkout} is not a Git checkout")

    journal = lookup_journal(journal_key)
    if (
        journal is None
        or str(journal.get("intent_fingerprint") or "") != intent_fingerprint
    ):
        raise ManagementError("the matching onboarding intent journal is missing")
    if str(journal.get("status") or "") not in {"running", "failed"}:
        raise ManagementError("the onboarding intent journal is not active")
    if journal.get("setup_required") is not True:
        raise ManagementError("the onboarding intent did not resolve setup as required")
    if remote.get("can_push") is False:
        raise ManagementError(
            "cannot push the SASE-managed marker; run `sase init -M` on a machine "
            "with push rights"
        )

    config_path = checkout / CONFIG_RELATIVE
    management = journal.get("management")
    state = dict(management) if isinstance(management, dict) else {}
    expected_identity = identity_key.casefold()
    _verify_origin(checkout, workflow_type, expected_identity)
    if should_manage_empty_origin(checkout, remote, state):
        return manage_empty_origin(
            checkout,
            config_path,
            remote,
            state,
            journal_key=journal_key,
            intent_fingerprint=intent_fingerprint,
            display=display,
        )

    branch = normalize_branch(str(remote.get("default_branch") or ""))
    if not branch:
        raise ManagementError("the provider did not report a usable default branch")
    _verify_branch(checkout, branch)
    _verify_origin(checkout, workflow_type, expected_identity)

    head = git_output(checkout, "rev-parse", "HEAD", action="read checkout HEAD")
    current_remote_oid = remote_oid(checkout, branch)
    prior_parent = str(state.get("commit_parent") or "")
    prior_commit = str(state.get("commit_id") or "")
    if state.get("push_verified") or state.get("pushed"):
        if prior_commit and current_remote_oid == prior_commit:
            return success(prior_commit, changed=True)
        if (
            not prior_commit
            and remote.get("sase_managed") is True
            and project_management_status(config_path).is_sase_managed
        ):
            return success("", changed=False)
        else:
            raise ManagementError(
                "the journal says setup was pushed, but origin no longer points "
                "to the recorded marker commit"
            )
    if prior_parent:
        if current_remote_oid not in {prior_parent, prior_commit}:
            raise ManagementError(
                "origin's default branch changed during setup; the local marker commit "
                "is preserved, but no unrelated history was pushed"
            )
    elif head != current_remote_oid:
        raise ManagementError(
            "the checkout has commits that are not on origin's default branch; "
            "reconcile them before retrying setup"
        )

    expected_hash, baseline_hash, _current_hash = prepare_and_write_marker(
        checkout,
        config_path,
        state,
        journal_key=journal_key,
        intent_fingerprint=intent_fingerprint,
        display=display,
    )

    # A config that was already committed and identical to origin needs no
    # marker commit. This also handles an already-managed checkout idempotently.
    if expected_hash == baseline_hash and head == current_remote_oid:
        if remote.get("sase_managed") is not True:
            raise ManagementError(
                "the local marker is already committed, but the provider does not "
                "confirm that origin is SASE-managed"
            )
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="push_verified",
            push_expected_oid=current_remote_oid,
            push_verified=True,
            pushed=True,
        )
        return success("", changed=False)

    if not prior_parent:
        prior_parent = head
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="prepared",
            commit_parent=prior_parent,
            commit_content_hash=expected_hash,
            commit_message=MANAGEMENT_COMMIT_MESSAGE,
        )
    elif str(state.get("commit_content_hash") or expected_hash) != expected_hash:
        raise ManagementError("the recorded marker commit content does not match")

    if current_remote_oid == prior_commit and prior_commit:
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="push_verified",
            push_expected_oid=prior_commit,
            push_verified=True,
            pushed=True,
        )
        return success(prior_commit, changed=True)

    commit_id = find_expected_commit(
        checkout,
        prior_parent,
        expected_hash,
        str(state.get("commit_message") or MANAGEMENT_COMMIT_MESSAGE),
        prior_commit,
    )
    if not commit_id:
        current_head = git_output(
            checkout, "rev-parse", "HEAD", action="read checkout HEAD"
        )
        if current_head != prior_parent:
            raise ManagementError(
                "the checkout branch changed before the marker commit; "
                "no replacement commit was created"
            )
        _verify_branch(checkout, branch)
        _verify_origin(checkout, workflow_type, expected_identity)
        if remote_oid(checkout, branch) != prior_parent:
            raise ManagementError(
                "origin's default branch advanced before the marker commit; "
                "no stale commit was created"
            )
        stage_config(checkout, config_path, expected_hash)
        _verify_branch(checkout, branch)
        _verify_origin(checkout, workflow_type, expected_identity)
        if remote_oid(checkout, branch) != prior_parent:
            raise ManagementError(
                "origin's default branch advanced while staging; "
                "the staged marker is preserved without committing"
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
                prior_parent,
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
                prior_parent,
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

    _verify_branch(checkout, branch)
    _verify_origin(checkout, workflow_type, expected_identity)
    current_remote_oid = remote_oid(checkout, branch)
    if current_remote_oid == commit_id:
        write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="push_verified",
            push_expected_oid=commit_id,
            push_verified=True,
            pushed=True,
        )
        return success(commit_id, changed=True)
    if current_remote_oid != prior_parent:
        raise ManagementError(
            "origin's default branch advanced during setup; the marker commit is "
            "preserved locally and no unrelated history was pushed"
        )

    write_evidence(
        journal_key,
        intent_fingerprint,
        display,
        stage="push_started",
        push_expected_oid=commit_id,
    )
    result = push_management_marker(checkout, commit_id, branch)
    verified_oid = remote_oid(checkout, branch)
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
    return success(commit_id, changed=True)


def _verify_branch(checkout: Path, branch: str) -> None:
    current = git_output(
        checkout, "symbolic-ref", "--quiet", "--short", "HEAD", action="read branch"
    )
    if current != branch:
        raise ManagementError(
            f"checkout is on {current or 'detached HEAD'}, expected default branch {branch}"
        )


def _verify_origin(checkout: Path, workflow_type: str, identity_key: str) -> None:
    fetch = git_output(
        checkout, "remote", "get-url", "origin", action="read origin URL"
    )
    push_result = manage_ops.run_git(
        checkout,
        "remote",
        "get-url",
        "--push",
        "--all",
        "origin",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if push_result.returncode != 0:
        raise ManagementError(failure_message("read origin push URL", push_result))
    urls = [
        fetch,
        *(line.strip() for line in push_result.stdout.splitlines() if line.strip()),
    ]
    if not urls or any(
        _origin_identity(workflow_type, url).casefold() != identity_key for url in urls
    ):
        raise ManagementError(
            "origin changed or does not match the requested repository identity"
        )


def _origin_identity(workflow_type: str, origin: str) -> str:
    if workflow_type:
        try:
            parsed = workspace_provider.parse_repo_ref(workflow_type, origin)
        except Exception:
            parsed = None
        if parsed is not None and parsed.identity_key:
            return str(parsed.identity_key)
    return identity_for_origin(origin)


__all__ = ["manage_repository"]
