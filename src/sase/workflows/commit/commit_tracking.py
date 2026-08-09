"""Post-commit tracking: diff capture, COMMITS entries, result markers, Patch."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.ace.patch.section_order import PROJECT_SPEC_SECTION_HEADERS
from sase.ace.patch.storage import is_stitch_section_header
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.core.patch_metadata import canonicalize_patch_metadata
from sase.core.paths import sase_subdir
from sase.output import print_status
from sase.workflows.commit.plan_paths import format_sase_plan_reference

if TYPE_CHECKING:
    from sase.vcs_provider._base import VCSProvider


def resolve_cl_name() -> str | None:
    """Resolve the Patch/branch name from env var or current branch."""
    cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    if cl_name:
        return cl_name
    try:
        from sase.workflows.utils import get_cl_name_from_branch

        return get_cl_name_from_branch()
    except Exception:
        return None


def resolve_project_file() -> str | None:
    """Resolve the project file path from env var or workspace detection."""
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if project_file:
        return project_file
    try:
        from sase.workflows.utils import (
            get_project_file_path,
            get_project_from_workspace,
        )

        project_name = get_project_from_workspace()
        if not project_name:
            return None
        return get_project_file_path(project_name)
    except Exception:
        return None


def capture_pre_commit_diff(
    provider: VCSProvider, cwd: str, cl_name: str | None
) -> str | None:
    """Capture VCS diff before committing and save it for the COMMITS entry.

    After the VCS commit the working-tree diff is empty, so this must run
    beforehand.  When ``SASE_ARTIFACTS_DIR`` is set (agent context), the
    diff is saved there.  Otherwise it falls back to
    ``~/.sase/diffs/<cl_name>-<timestamp>.diff`` so human CLI commits get
    diffs too.

    Returns the path to the saved diff file, or ``None`` on failure.
    """
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir and not cl_name:
        return None

    try:
        diff_with_untracked = getattr(provider, "diff_with_untracked", None)
        if callable(diff_with_untracked):
            try:
                result = diff_with_untracked(cwd)
            except NotImplementedError:
                result = None
            if isinstance(result, tuple) and len(result) == 2:
                ok, diff_text = result
            else:
                ok, diff_text = provider.diff(cwd)  # type: ignore[union-attr]
        else:
            ok, diff_text = provider.diff(cwd)  # type: ignore[union-attr]
    except Exception:
        return None
    if not ok or not diff_text:
        return None
    if artifacts_dir:
        return write_commit_diff_artifact(
            diff_text,
            artifacts_dir=artifacts_dir,
            write_legacy=True,
        )
    assert cl_name is not None
    from sase.core.time import generate_timestamp

    diffs_dir = str(sase_subdir("diffs"))
    os.makedirs(diffs_dir, exist_ok=True)
    diff_path = os.path.join(diffs_dir, f"{cl_name}-{generate_timestamp()}.diff")
    try:
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(diff_text)
    except Exception:
        return None
    return diff_path


def write_commit_diff_artifact(
    diff_text: str,
    *,
    artifacts_dir: str | os.PathLike[str],
    write_legacy: bool = False,
) -> str | None:
    """Write a sequential per-commit diff artifact and return its path."""

    artifacts_dir_str = os.fspath(artifacts_dir)
    diff_dir = os.path.join(artifacts_dir_str, "commit_diffs")
    try:
        os.makedirs(diff_dir, exist_ok=True)
        existing_count = sum(
            1
            for name in os.listdir(diff_dir)
            if name.endswith(".diff") and os.path.isfile(os.path.join(diff_dir, name))
        )
        next_index = existing_count + 1
        diff_path = os.path.join(diff_dir, f"{next_index:03d}.diff")
        while os.path.exists(diff_path):
            next_index += 1
            diff_path = os.path.join(diff_dir, f"{next_index:03d}.diff")
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write(diff_text)
    except OSError:
        return None

    if write_legacy:
        try:
            with open(
                os.path.join(artifacts_dir_str, "commit_diff.diff"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(diff_text)
        except OSError:
            pass
    return diff_path


def _commits_drawer_has_entry_id(
    project_file: str, cl_name: str, entry_id: str
) -> bool:
    """Return True if *cl_name*'s COMMITS drawer already contains *entry_id*."""
    try:
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False

    in_target = False
    in_commits = False
    pattern = re.compile(rf"^\s*\({re.escape(entry_id)}\)\s+")
    for line in lines:
        if line.startswith("NAME: "):
            in_target = line[6:].strip() == cl_name
            in_commits = False
            continue
        if not in_target:
            continue
        if is_stitch_section_header(line):
            in_commits = True
            continue
        if line.startswith(PROJECT_SPEC_SECTION_HEADERS):
            in_commits = False
            continue
        if in_commits and pattern.match(line):
            return True
    return False


def append_commits_entry(
    project_file: str | None,
    cl_name: str | None,
    payload: dict,
    method: str,
    diff_path: str | None,
    *,
    expected_entry_id: str | None = None,
) -> str | None:
    """Append a COMMITS entry after successful commit/proposal. Returns entry_id.

    When *expected_entry_id* is provided, the COMMITS drawer is scanned first
    for a line that begins with ``(<expected_entry_id>) ``; if found, that ID
    is returned without modifying the file (idempotent resume).
    """
    if not project_file or not cl_name or not os.path.isfile(project_file):
        return None

    if expected_entry_id and _commits_drawer_has_entry_id(
        project_file, cl_name, expected_entry_id
    ):
        return expected_entry_id

    # Build note + body from the commit message.
    # The header is the first line; everything after the first blank line is
    # the body.
    message = payload.get("message", "")
    parts = message.split("\n\n", 1)
    note = (parts[0].split("\n")[0]) or "Manual changes"
    body: list[str] | None = None
    if len(parts) > 1 and parts[1].strip():
        body = parts[1].splitlines()

    # For proposals, prepend workflow identifier if available
    if method == "create_proposal":
        who = os.environ.get("SASE_AGENT_WHO")
        if who:
            note = f"[{who}] {note}"

    chat_path = os.environ.get("SASE_AGENT_CHAT_PATH")

    # Compute display path for plan.
    plan_display: str | None = None
    raw_plan = os.environ.get("SASE_PLAN", "")
    if raw_plan:
        plan_display = format_sase_plan_reference(raw_plan, repo_root=os.getcwd())

    from sase.workflows.commit_utils.entries import (
        add_commit_entry_with_id,
        add_proposed_commit_entry,
    )

    if method == "create_proposal":
        ok, entry_id = add_proposed_commit_entry(
            project_file=project_file,
            cl_name=cl_name,
            note=note,
            diff_path=diff_path,
            chat_path=chat_path,
            body=body,
            plan_path=plan_display,
        )
    else:
        ok, entry_id = add_commit_entry_with_id(
            project_file=project_file,
            cl_name=cl_name,
            note=note,
            diff_path=diff_path,
            chat_path=chat_path,
            body=body,
            plan_path=plan_display,
        )
    return entry_id if ok else None


def _repository_root(path: object) -> str | None:
    """Return the nearest repository root containing *path*, when recognizable.

    Commit tracking only needs repository identity, not provider behavior.  The
    nearest marker matters because sidecar repositories may be nested inside
    the primary workspace.  Unknown VCS layouts deliberately return ``None``
    so callers can preserve the legacy compatibility behavior.
    """
    if not isinstance(path, (str, os.PathLike)):
        return None
    try:
        candidate = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not candidate.is_dir():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / ".git").exists() or (directory / ".hg").exists():
            return os.path.normcase(os.path.normpath(os.fspath(directory)))
    return None


def _persist_primary_commit_metadata(
    artifacts_dir: str,
    diff_path: str | None,
    changespec_name: str | None,
    *,
    commit_cwd: str | None = None,
) -> None:
    """Persist generic primary-repository commit metadata fallbacks.

    ``commit_results.json`` records every commit with its repository-aware
    metadata.  The corresponding ``agent_meta.json`` fields have a narrower
    contract: they describe commits in the agent's primary workspace.  Do not
    let a linked, external, sidecar, or temporary repository replace them.

    Historical agents may lack ``workspace_dir`` or use an unrecognized VCS
    layout.  In those cases repository identity cannot be proven, so retain
    the previous conservative behavior and publish the metadata rather than
    silently dropping the only persisted attribution.
    """
    normalized_changespec_name = (
        changespec_name.strip() if changespec_name and changespec_name.strip() else None
    )
    if not diff_path and not normalized_changespec_name:
        return

    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            return
        primary_root = _repository_root(meta.get("workspace_dir"))
        commit_root = _repository_root(commit_cwd)
        if (
            primary_root is not None
            and commit_root is not None
            and primary_root != commit_root
        ):
            return
        original_meta = dict(meta)
        canonicalize_patch_metadata(meta)
        canonicalize_agent_tribe_metadata(meta)
        if diff_path and meta.get("commit_diff_path") != diff_path:
            meta["commit_diff_path"] = diff_path
        if (
            normalized_changespec_name
            and meta.get("commit_patch_name") != normalized_changespec_name
        ):
            meta["commit_patch_name"] = normalized_changespec_name
            meta["commit_changespec_name"] = normalized_changespec_name
        if meta == original_meta:
            return
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return


def _load_commit_results(results_path: str) -> list[dict[str, Any]]:
    try:
        with open(results_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _upsert_commit_results_marker(
    artifacts_dir: str,
    marker: dict[str, Any],
) -> None:
    results_path = os.path.join(artifacts_dir, "commit_results.json")
    try:
        results = _load_commit_results(results_path)
        key = (marker.get("cwd"), marker.get("result"))
        for index, existing in enumerate(results):
            if (existing.get("cwd"), existing.get("result")) == key:
                results[index] = marker
                break
        else:
            results.append(marker)

        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(results, f)
    except (TypeError, OSError):
        return


def agent_workspace_dir(artifacts_dir: str) -> str | None:
    """Resolve the primary workspace recorded for an agent artifact directory."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        meta = None
    if isinstance(meta, dict):
        workspace_dir = meta.get("workspace_dir")
        if isinstance(workspace_dir, str) and workspace_dir.strip():
            return workspace_dir
    from sase.env_contracts import WORKSPACE_PIN_ENV_VARS

    for env_name in (*WORKSPACE_PIN_ENV_VARS, "PWD"):
        workspace_dir = os.environ.get(env_name)
        if workspace_dir:
            return workspace_dir
    return None


def _sdd_repo_name_for_commit_cwd(
    commit_cwd: str,
    workspace_dir: str | None,
) -> str | None:
    """Return an external SDD repository label containing ``commit_cwd``."""

    if not workspace_dir:
        return None
    try:
        from sase.sdd.store import get_primary_workspace_dir, read_sdd_store_record

        cwd = Path(commit_cwd).expanduser().resolve(strict=False)
        workspace = Path(workspace_dir).expanduser().resolve(strict=False)
        sidecars_root = workspace / "sase" / "repos"
        try:
            relative = cwd.relative_to(sidecars_root)
        except ValueError:
            relative = None
        if relative is not None and relative.parts:
            role = relative.parts[0]
            if role not in {"external", "linked"}:
                return role

        legacy_root = workspace / ".sase" / "sdd"
        try:
            cwd.relative_to(legacy_root)
        except ValueError:
            return None
        primary_workspace = get_primary_workspace_dir(str(workspace), 1)
        record = read_sdd_store_record(primary_workspace)
        if record is not None and record.repo:
            return record.repo
        return "sdd"
    except Exception:
        return None


def _external_repo_name_for_commit_cwd(
    commit_cwd: str,
    workspace_dir: str | None,
) -> str | None:
    """Return the canonical external-repo name containing ``commit_cwd``."""

    if not workspace_dir:
        return None
    try:
        from sase.external_repos import external_repo_name_from_clone_parts
        from sase.linked_repos import EXTERNAL_REPO_CLONES_SUBDIR

        repo_root = _repository_root(commit_cwd)
        if repo_root is None:
            return None
        external_root = (
            Path(workspace_dir)
            .expanduser()
            .resolve(strict=False)
            .joinpath(*EXTERNAL_REPO_CLONES_SUBDIR)
        )
        clone_parts = Path(repo_root).relative_to(external_root).parts
        return external_repo_name_from_clone_parts(clone_parts)
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve_commit_created_at(cwd: str, sha: str | None) -> int | None:
    """Best-effort author-time lookup for a just-made commit. Never raises."""
    if not sha:
        return None
    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(cwd)
        commits = provider.log(cwd, 1, revs=(sha,), merges="show")
    except Exception:
        return None

    if not commits:
        return None
    commit = commits[0]
    target = sha.lower()
    if commit.full_id.lower() != target and commit.short_id.lower() != target:
        return None
    return commit.timestamp


def record_sdd_commit_result_marker(
    *,
    cwd: str | os.PathLike[str],
    result: str,
    message: str,
    repo_name: str | None = None,
    artifacts_dir: str | os.PathLike[str] | None = None,
    diff_path: str | None = None,
) -> None:
    """Append an SDD commit to an agent's commit-results marker list.

    SDD commits are additional repo commits, not the primary workflow commit,
    so this deliberately does not write ``commit_result.json``.
    """
    resolved_artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved_artifacts_dir:
        return

    artifacts_dir_str = os.fspath(resolved_artifacts_dir)
    if not os.path.isdir(artifacts_dir_str):
        return

    run_id = os.environ.get("SASE_AGENT_TIMESTAMP", "").strip()
    if not run_id:
        run_id = os.path.basename(os.path.normpath(artifacts_dir_str))

    cwd_str = os.fspath(cwd)
    marker: dict[str, Any] = {
        "method": "sdd_commit",
        "run_id": run_id,
        "cwd": cwd_str,
        "result": result,
        "commit_result": result,
        "message": message,
        "repo_name": repo_name or Path(cwd_str).name,
        "diff_path": diff_path,
        "commit_diff_path": diff_path,
    }
    committed_at = _resolve_commit_created_at(cwd_str, result)
    if committed_at is not None:
        marker["committed_at"] = committed_at
    _upsert_commit_results_marker(artifacts_dir_str, marker)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir_str)


def write_result_marker(
    method: str,
    payload: dict,
    diff_path: str | None,
    result: str | None,
    changespec_name: str | None,
    *,
    entry_id: str | None = None,
) -> None:
    """Write commit result to a marker file for xprompt post-steps."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return

    run_id = os.environ.get("SASE_AGENT_TIMESTAMP", "").strip()
    if not run_id:
        run_id = os.path.basename(os.path.normpath(artifacts_dir))
    commit_cwd = os.getcwd()
    workspace_dir = agent_workspace_dir(artifacts_dir)
    repo_name = _external_repo_name_for_commit_cwd(commit_cwd, workspace_dir)
    if repo_name is None:
        repo_name = _sdd_repo_name_for_commit_cwd(commit_cwd, workspace_dir)

    marker = {
        "method": method,
        "run_id": run_id,
        "cwd": commit_cwd,
        "result": result,
        "commit_result": result,
        "message": payload.get("message", ""),
        "name": payload.get("name", ""),
        "bead_id": payload.get("bead_id", ""),
        "patch_name": changespec_name,
        "changespec_name": changespec_name,
        "commit_patch_name": changespec_name,
        "commit_changespec_name": changespec_name,
        "entry_id": entry_id,
        "stitch_id": entry_id,
        "commit_entry_id": entry_id,
        "diff_path": diff_path,
        "commit_diff_path": diff_path,
    }
    if repo_name is not None:
        marker["repo_name"] = repo_name
    committed_at = _resolve_commit_created_at(commit_cwd, result)
    if committed_at is not None:
        marker["committed_at"] = committed_at
    marker_path = os.path.join(artifacts_dir, "commit_result.json")
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker, f)
    _upsert_commit_results_marker(artifacts_dir, marker)
    _persist_primary_commit_metadata(
        artifacts_dir,
        diff_path,
        changespec_name,
        commit_cwd=commit_cwd,
    )


def create_patch(
    payload: dict,
    base_cl_name: str | None,
    parent_cl_name: str | None,
    reserved_name: str | None,
    pr_url: str | None,
) -> str | None:
    """Best-effort Patch creation after a successful PR flow."""
    try:
        from sase.workflows.utils import (
            get_project_file_path,
            get_project_from_workspace,
        )
        from sase.workspace_provider.patch import (
            create_patch_for_workflow,
        )

        project_name = get_project_from_workspace()
        if not project_name:
            print_status("Skipping Patch: could not detect project name.", "info")
            return None

        project_file = get_project_file_path(project_name)
        branch_name = payload.get("name", "")
        checkout_target = payload.get("checkout_target", "HEAD~1")

        bug_id = (
            payload.get("bug_id", "") or os.environ.get("SASE_BUG_ID", "")
        ).strip()
        bug = f"http://b/{bug_id}" if bug_id and bug_id != "0" else None

        status_map = {"wip": "WIP", "draft": "Draft", "ready": "Ready"}
        raw_status = (
            payload.get("status", "") or os.environ.get("SASE_PR_STATUS", "")
        ).strip()
        status = status_map.get(raw_status.lower(), "Draft")

        cs_name = create_patch_for_workflow(
            project_name=project_name,
            project_file=project_file,
            checkout_target=checkout_target,
            branch_name=branch_name,
            prompt="",
            response="",
            workflow_name="sase_commit",
            pr_url=pr_url,
            cl_name=base_cl_name or payload.get("name"),
            commit_description=payload.get("message", ""),
            parent=parent_cl_name,
            bug=bug,
            reserved_name=reserved_name,
            status=status,
        )
        if cs_name:
            print_status(f"Created Patch: {cs_name}", "success")
        else:
            print_status("Skipping Patch: no new commits detected.", "info")
        return cs_name
    except Exception as exc:
        print_status(f"Skipping Patch: {exc}", "warning")
        return None


def cleanup_reservation(reserved_name: str | None) -> None:
    """Remove the reservation entry on VCS failure (best-effort)."""
    if not reserved_name:
        return
    try:
        from sase.workflows.commit.patch_operations import remove_reservation
        from sase.workflows.utils import get_project_from_workspace

        project_name = get_project_from_workspace()
        if project_name:
            remove_reservation(project_name, reserved_name)
    except Exception:
        pass
