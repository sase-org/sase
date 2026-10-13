"""Recoverable commit-and-push of a repository's SASE management marker."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
import subprocess
from typing import Any

from sase import workspace_provider
from sase.config import set_key
from sase.project_management import enable_sase_management, project_management_status
from sase.project_onboarding.discovery import identity_for_origin, resolve_git_dir
from sase.project_onboarding.journal import lookup_journal, update_management
from sase.workspace_provider.utils import non_interactive_git_env
from sase.noninteractive_subprocess import run_noninteractive

_CONFIG_RELATIVE = Path("sase") / "sase.yml"
_MANAGEMENT_COMMIT_MESSAGE = "chore: mark repository as SASE-managed"
_GIT_TIMEOUT_SECONDS = 30.0
_PUSH_TIMEOUT_SECONDS = 60.0


class ManagementError(RuntimeError):
    """The management effect could not safely reach its postcondition."""


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

    config_path = checkout / _CONFIG_RELATIVE
    management = journal.get("management")
    state = dict(management) if isinstance(management, dict) else {}

    branch = _normalize_branch(str(remote.get("default_branch") or ""))
    if not branch:
        raise ManagementError("the provider did not report a usable default branch")
    _verify_branch(checkout, branch)
    expected_identity = identity_key.casefold()
    _verify_origin(checkout, workflow_type, expected_identity)

    head = _git_output(checkout, "rev-parse", "HEAD", action="read checkout HEAD")
    remote_oid = _remote_oid(checkout, branch)
    prior_parent = str(state.get("commit_parent") or "")
    prior_commit = str(state.get("commit_id") or "")
    if state.get("push_verified") or state.get("pushed"):
        if prior_commit and remote_oid == prior_commit:
            return _success(prior_commit, changed=True)
        if (
            not prior_commit
            and remote.get("sase_managed") is True
            and project_management_status(config_path).is_sase_managed
        ):
            return _success("", changed=False)
        else:
            raise ManagementError(
                "the journal says setup was pushed, but origin no longer points "
                "to the recorded marker commit"
            )
    if prior_parent:
        if remote_oid not in {prior_parent, prior_commit}:
            raise ManagementError(
                "origin's default branch changed during setup; the local marker commit "
                "is preserved, but no unrelated history was pushed"
            )
    elif head != remote_oid:
        raise ManagementError(
            "the checkout has commits that are not on origin's default branch; "
            "reconcile them before retrying setup"
        )

    current_bytes = _read_config(config_path)
    current_hash = _sha256(current_bytes)
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
    expected_hash = _sha256(expected_bytes)
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
        _write_evidence(
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
        _write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="write_started",
            marker_write_stage="write_started",
        )
        marker_update = enable_sase_management(config_path)
        current_bytes = _read_config(config_path)
        current_hash = _sha256(current_bytes)
        if current_hash != expected_hash:
            detail = f": {marker_update.error}" if marker_update.error else ""
            raise ManagementError("failed to write the expected SASE marker" + detail)
    else:
        current_bytes = _read_config(config_path)
        current_hash = _sha256(current_bytes)

    if not project_management_status(config_path).is_sase_managed:
        raise ManagementError("the local SASE management marker is not valid")
    _write_evidence(
        journal_key,
        intent_fingerprint,
        display,
        stage="marker_written",
        marker_written=True,
        marker_write_stage="written",
        current_config_hash=current_hash,
    )

    # A config that was already committed and identical to origin needs no
    # marker commit. This also handles an already-managed checkout idempotently.
    if expected_hash == baseline_hash and head == remote_oid:
        if remote.get("sase_managed") is not True:
            raise ManagementError(
                "the local marker is already committed, but the provider does not "
                "confirm that origin is SASE-managed"
            )
        _write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="push_verified",
            push_expected_oid=remote_oid,
            push_verified=True,
            pushed=True,
        )
        return _success("", changed=False)

    if not prior_parent:
        prior_parent = head
        _write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="prepared",
            commit_parent=prior_parent,
            commit_content_hash=expected_hash,
            commit_message=_MANAGEMENT_COMMIT_MESSAGE,
        )
    elif str(state.get("commit_content_hash") or expected_hash) != expected_hash:
        raise ManagementError("the recorded marker commit content does not match")

    if remote_oid == prior_commit and prior_commit:
        _write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="push_verified",
            push_expected_oid=prior_commit,
            push_verified=True,
            pushed=True,
        )
        return _success(prior_commit, changed=True)

    commit_id = _find_expected_commit(
        checkout,
        prior_parent,
        expected_hash,
        str(state.get("commit_message") or _MANAGEMENT_COMMIT_MESSAGE),
        prior_commit,
    )
    if not commit_id:
        current_head = _git_output(
            checkout, "rev-parse", "HEAD", action="read checkout HEAD"
        )
        if current_head != prior_parent:
            raise ManagementError(
                "the checkout branch changed before the marker commit; "
                "no replacement commit was created"
            )
        _verify_branch(checkout, branch)
        _verify_origin(checkout, workflow_type, expected_identity)
        if _remote_oid(checkout, branch) != prior_parent:
            raise ManagementError(
                "origin's default branch advanced before the marker commit; "
                "no stale commit was created"
            )
        _stage_config(checkout, config_path, expected_hash)
        _verify_branch(checkout, branch)
        _verify_origin(checkout, workflow_type, expected_identity)
        if _remote_oid(checkout, branch) != prior_parent:
            raise ManagementError(
                "origin's default branch advanced while staging; "
                "the staged marker is preserved without committing"
            )
        _write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="commit_started",
        )
        result = _run_git(
            checkout,
            "commit",
            "--only",
            "-m",
            _MANAGEMENT_COMMIT_MESSAGE,
            "--",
            str(_CONFIG_RELATIVE),
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            commit_id = _find_expected_commit(
                checkout,
                prior_parent,
                expected_hash,
                _MANAGEMENT_COMMIT_MESSAGE,
                "",
            )
            if not commit_id:
                raise ManagementError(
                    _failure_message("commit SASE management marker", result)
                )
        else:
            commit_id = _git_output(
                checkout, "rev-parse", "HEAD", action="read marker commit"
            )
            if not _valid_expected_commit(
                checkout,
                commit_id,
                prior_parent,
                expected_hash,
                _MANAGEMENT_COMMIT_MESSAGE,
            ):
                raise ManagementError(
                    "Git created a commit that does not contain only the expected marker"
                )
        _write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="committed",
            commit_id=commit_id,
        )
    else:
        _write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="committed",
            commit_id=commit_id,
        )

    _verify_branch(checkout, branch)
    _verify_origin(checkout, workflow_type, expected_identity)
    remote_oid = _remote_oid(checkout, branch)
    if remote_oid == commit_id:
        _write_evidence(
            journal_key,
            intent_fingerprint,
            display,
            stage="push_verified",
            push_expected_oid=commit_id,
            push_verified=True,
            pushed=True,
        )
        return _success(commit_id, changed=True)
    if remote_oid != prior_parent:
        raise ManagementError(
            "origin's default branch advanced during setup; the marker commit is "
            "preserved locally and no unrelated history was pushed"
        )

    _write_evidence(
        journal_key,
        intent_fingerprint,
        display,
        stage="push_started",
        push_expected_oid=commit_id,
    )
    result = _run_git(
        checkout,
        "push",
        "origin",
        f"{commit_id}:refs/heads/{branch}",
        timeout=_PUSH_TIMEOUT_SECONDS,
    )
    verified_oid = _remote_oid(checkout, branch)
    if verified_oid != commit_id:
        reason = _failure_message("push SASE management marker", result)
        raise ManagementError(
            f"{reason}. The local marker commit is preserved. A protected default "
            "branch may require a pull request or a human to run `sase init -M`."
        )
    _write_evidence(
        journal_key,
        intent_fingerprint,
        display,
        stage="push_verified",
        push_expected_oid=commit_id,
        push_verified=True,
        pushed=True,
    )
    return _success(commit_id, changed=True)


def _write_evidence(
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


def _stage_config(checkout: Path, config_path: Path, expected_hash: str) -> None:
    if _path_is_dirty(checkout) and _sha256(_read_config(config_path)) != expected_hash:
        raise ManagementError("sase/sase.yml changed before it could be staged")
    _run_checked(checkout, "stage SASE marker", "add", "--", str(_CONFIG_RELATIVE))
    staged = _run_git(
        checkout,
        "show",
        f":{_CONFIG_RELATIVE.as_posix()}",
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if (
        staged.returncode != 0
        or _sha256(staged.stdout.encode("utf-8")) != expected_hash
    ):
        raise ManagementError("the staged SASE marker does not match the journal")


def _find_expected_commit(
    checkout: Path,
    parent: str,
    content_hash: str,
    message: str,
    preferred: str,
) -> str:
    if preferred and _valid_expected_commit(
        checkout, preferred, parent, content_hash, message
    ):
        return preferred
    result = _run_git(
        checkout,
        "log",
        "--all",
        "--format=%H%x00%P%x00%s",
        "-n",
        "100",
        "--",
        str(_CONFIG_RELATIVE),
        timeout=_GIT_TIMEOUT_SECONDS,
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
            and _valid_expected_commit(
                checkout, commit_id, parent, content_hash, message
            )
        ):
            return commit_id
    return ""


def _valid_expected_commit(
    checkout: Path,
    commit_id: str,
    parent: str,
    content_hash: str,
    message: str,
) -> bool:
    if not commit_id:
        return False
    metadata = _run_git(
        checkout,
        "show",
        "-s",
        "--format=%P%x00%s",
        commit_id,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if metadata.returncode != 0:
        return False
    fields = metadata.stdout.rstrip("\n").split("\x00", 1)
    if fields != [parent, message]:
        return False
    paths = _run_git(
        checkout,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        commit_id,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if paths.returncode != 0 or paths.stdout.splitlines() != [
        _CONFIG_RELATIVE.as_posix()
    ]:
        return False
    content = _run_git(
        checkout,
        "show",
        f"{commit_id}:{_CONFIG_RELATIVE.as_posix()}",
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    return (
        content.returncode == 0
        and _sha256(content.stdout.encode("utf-8")) == content_hash
    )


def _verify_branch(checkout: Path, branch: str) -> None:
    current = _git_output(
        checkout, "symbolic-ref", "--quiet", "--short", "HEAD", action="read branch"
    )
    if current != branch:
        raise ManagementError(
            f"checkout is on {current or 'detached HEAD'}, expected default branch {branch}"
        )


def _verify_origin(checkout: Path, workflow_type: str, identity_key: str) -> None:
    fetch = _git_output(
        checkout, "remote", "get-url", "origin", action="read origin URL"
    )
    push_result = _run_git(
        checkout,
        "remote",
        "get-url",
        "--push",
        "--all",
        "origin",
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if push_result.returncode != 0:
        raise ManagementError(_failure_message("read origin push URL", push_result))
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


def _remote_oid(checkout: Path, branch: str) -> str:
    result = _run_git(
        checkout,
        "ls-remote",
        "--heads",
        "origin",
        f"refs/heads/{branch}",
        timeout=_PUSH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ManagementError(_failure_message("verify origin default branch", result))
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != f"refs/heads/{branch}":
        raise ManagementError(f"origin has no unique refs/heads/{branch} branch")
    return rows[0][0]


def _normalize_branch(branch: str) -> str:
    normalized = branch.strip()
    if normalized.startswith("refs/heads/"):
        normalized = normalized.removeprefix("refs/heads/")
    elif normalized.startswith("origin/"):
        normalized = normalized.removeprefix("origin/")
    if not normalized:
        return ""
    checked = _run_git(Path.cwd(), "check-ref-format", f"refs/heads/{normalized}")
    return normalized if checked.returncode == 0 else ""


def _path_is_dirty(checkout: Path) -> bool:
    result = _run_git(
        checkout,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        str(_CONFIG_RELATIVE),
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ManagementError(_failure_message("inspect SASE config status", result))
    return bool(result.stdout.strip())


def _read_config(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise ManagementError(f"could not read {path}: {exc}") from exc


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_output(checkout: Path, *args: str, action: str) -> str:
    result = _run_git(checkout, *args, timeout=_GIT_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise ManagementError(_failure_message(action, result))
    return result.stdout.strip()


def _run_checked(
    checkout: Path, label: str, *args: str
) -> subprocess.CompletedProcess[str]:
    result = _run_git(checkout, *args, timeout=_GIT_TIMEOUT_SECONDS)
    if result.returncode != 0:
        raise ManagementError(_failure_message(label, result))
    return result


def _run_git(
    checkout: Path,
    *args: str,
    timeout: float = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    env = non_interactive_git_env()
    env["GH_PROMPT_DISABLED"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return run_noninteractive(
            ["git", *args],
            cwd=checkout,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ManagementError(
            f"git {' '.join(args)} timed out after {timeout:g}s"
        ) from exc
    except OSError as exc:
        raise ManagementError(f"could not run git {' '.join(args)}: {exc}") from exc


def _failure_message(action: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    suffix = f": {detail}" if detail else ""
    return f"failed to {action} (exit {result.returncode}){suffix}"


def _success(commit_id: str, *, changed: bool) -> dict[str, Any]:
    return {
        "ok": True,
        "changed": changed,
        "commit_id": commit_id,
        "pushed": True,
        "message": "repository is SASE-managed",
    }


__all__ = ["ManagementError", "manage_repository"]
