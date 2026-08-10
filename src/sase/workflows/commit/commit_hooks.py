"""Commit hooks plus bead and SASE_PLAN handling."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.bead.project import BEADS_DIRNAME
from sase.config.core import load_merged_config
from sase.output import print_status
from sase.workflows.commit.plan_paths import (
    format_sase_plan_link,
    format_sase_plan_tag_value,
    is_sase_plan_in_repo,
)

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def _extract_yyyymm_from_plan(plan_path: str) -> str | None:
    """Extract YYYYMM from a plan file's ``create_time`` frontmatter field.

    Returns ``None`` if the file has no frontmatter or no ``create_time`` field.
    """
    import re

    try:
        with open(plan_path, encoding="utf-8") as f:
            content = f.read(512)  # frontmatter is near the top
    except OSError:
        return None
    if not content.startswith("---\n"):
        return None
    end = content.find("\n---\n", 4)
    if end == -1:
        return None
    fm = content[4:end]
    m = re.search(r"^create_time:\s*(\d{4})-(\d{2})", fm, re.MULTILINE)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return None


CommitHookPhase = Literal["before", "after"]
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


def _run_commit_hook(phase: CommitHookPhase, cwd: str) -> bool:
    """Run the configured hook for *phase* in the repository root."""
    config = load_merged_config()
    hooks = config.get("commit_hooks", {})
    cmd = hooks.get(phase, "") if isinstance(hooks, dict) else ""
    if not cmd:
        return True
    repo_root = _get_repo_root(cwd) or cwd
    print_status(f"Running {phase} commit hook: {cmd}", "progress")
    result = subprocess.run(
        cmd, shell=True, cwd=repo_root, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        print_status(
            f"{phase.capitalize()} commit hook failed "
            f"(exit {result.returncode}): {cmd}",
            "error",
        )
        tail = _commit_hook_output_tail(result.stdout, result.stderr)
        if tail:
            print(f"---- {phase} commit hook output tail ----", file=sys.stderr)
            print(tail, file=sys.stderr)
            print(f"---- end {phase} commit hook output ----", file=sys.stderr)
        return False
    return True


def run_before_commit_hook(cwd: str) -> bool:
    """Run ``commit_hooks.before`` in the repository root."""
    return _run_commit_hook("before", cwd)


def run_after_commit_hook(cwd: str) -> bool:
    """Run ``commit_hooks.after`` in the repository root."""
    return _run_commit_hook("after", cwd)


def _commit_hook_output_tail(stdout: str, stderr: str, *, max_lines: int = 50) -> str:
    """Return the last useful lines from captured commit-hook output."""
    lines: list[str] = []
    for label, text in (("stdout", stdout), ("stderr", stderr)):
        if not text:
            continue
        section = text.rstrip().splitlines()
        if not section:
            continue
        lines.append(f"[{label}]")
        lines.extend(section)
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


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
        repo_root = _get_repo_root(cwd)
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
        f"Auto-closed by `sase commit` after {landed}. No verification is implied "
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


def _get_repo_root(cwd: str) -> str:
    """Return the repo root directory, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _store_owning_plan_path(
    plan_path: Path,
    code_repo_root: str,
) -> SddStore | None:
    """Return the external SDD clone that directly owns *plan_path*."""

    plan_repo_root = _get_repo_root(str(plan_path.parent))
    if not plan_repo_root:
        return None

    plan_root = Path(plan_repo_root).expanduser().resolve(strict=False)
    code_root = (
        Path(code_repo_root).expanduser().resolve(strict=False)
        if code_repo_root
        else None
    )
    if code_root is not None and plan_root == code_root:
        return None
    try:
        relative_plan = plan_path.resolve(strict=False).relative_to(plan_root)
    except ValueError:
        return None

    from sase.sdd._paths import looks_like_sdd_root
    from sase.sdd._store_types import (
        SDD_STORAGE_SEPARATE_REPO,
        SDD_STORAGE_SIDECAR_REPOS,
        SddStore,
    )

    if not looks_like_sdd_root(plan_root):
        return None
    storage = (
        SDD_STORAGE_SIDECAR_REPOS
        if relative_plan.parts and re.fullmatch(r"\d{6}", relative_plan.parts[0])
        else SDD_STORAGE_SEPARATE_REPO
    )
    remote_url = _git_origin_remote(plan_root)
    provider: str | None = None
    if remote_url:
        from sase._git_remote import parse_hosted_git_remote

        hosted = parse_hosted_git_remote(remote_url)
        if hosted is not None and hosted.host.split(":", 1)[0] == "github.com":
            provider = "github"
    return SddStore(
        storage=storage,
        sdd_dir=plan_root,
        repo_root=plan_root,
        provider=provider,
        remote_url=remote_url,
    )


def _git_origin_remote(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _is_local_plan_archive(plan_path: Path) -> bool:
    from sase.core.paths import sase_subdir

    archive_root = sase_subdir("plans").resolve(strict=False)
    return plan_path.resolve(strict=False).is_relative_to(archive_root)


def _launch_owning_store(cwd: str) -> SddStore:
    """Resolve the host workspace's SDD store for an archive-only plan."""

    from sase.sdd.store import resolve_sdd_store

    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(cwd)
    except Exception:
        found = None
    if found is None:
        return resolve_sdd_store(cwd, 1)

    checkout_dir, marker = found
    store = resolve_sdd_store(checkout_dir, marker.workspace_num or 1)
    if store.is_in_tree:
        store = replace(store, repo_root=Path(checkout_dir))
    return store


def handle_sase_plan(payload: dict, cwd: str) -> None:
    """Append PLAN= to commit message and mark plan as done."""
    raw_plan_path = os.environ.get("SASE_PLAN", "")
    if not raw_plan_path:
        return

    # Determine repo root
    repo_root = _get_repo_root(cwd)
    plan = Path(raw_plan_path).expanduser()
    if not plan.is_absolute() and repo_root:
        plan = Path(repo_root) / plan
    archive_only = _is_local_plan_archive(plan)

    # If plan file doesn't exist at the expected path, try the ~/.sase/plans/ archive
    if not plan.is_file():
        from sase.core.paths import find_sharded_file

        archive_fallback = find_sharded_file("plans", plan.name)
        if archive_fallback is not None:
            plan = Path(archive_fallback)
            archive_only = True
        else:
            return  # truly missing

    plan_path = str(plan.resolve(strict=False))
    if archive_only:
        store = _launch_owning_store(cwd)
    else:
        resolved_store = _launch_owning_store(cwd)
        if is_sase_plan_in_repo(plan_path, resolved_store.sdd_dir):
            store = resolved_store
        else:
            store = (
                _store_owning_plan_path(Path(plan_path), repo_root) or resolved_store
            )

    in_repo = is_sase_plan_in_repo(plan_path, repo_root)
    plan_in_store = is_sase_plan_in_repo(plan_path, store.sdd_dir)
    # A nested store is physically under the workspace but belongs to its own
    # repository, so it must not be staged with the code commit.
    plan_in_code_repo = in_repo and (store.is_in_tree or not plan_in_store)
    should_copy = (
        not in_repo if store.is_in_tree else not plan_in_store and not plan_in_code_repo
    )

    from sase.sdd.files import get_yyyymm

    path_month = Path(plan_path).parent.name
    yyyymm = (
        path_month
        if re.fullmatch(r"\d{6}", path_month)
        else _extract_yyyymm_from_plan(plan_path) or get_yyyymm()
    )
    plan_content = Path(plan_path).read_text(encoding="utf-8")

    if should_copy:
        dest = os.path.join(
            store.kind_root("plans"), yyyymm, os.path.basename(plan_path)
        )
        # Format the copied plan with prettier (safety net for
        # archives created before the plan_command_handler format step)
        from sase.file_references import format_with_prettier

        plan_content = format_with_prettier(plan_content)
        plan_path = dest
        plan_in_code_repo = store.is_in_tree and is_sase_plan_in_repo(
            plan_path,
            repo_root,
        )

    # Approved store-backed plans already received frontmatter when written.
    # Copied archives need the same normalization as in-tree plans.
    if store.is_in_tree or should_copy:
        if not plan_content.startswith("---\n"):
            from sase.llm_provider._plan_utils import add_create_time_frontmatter

            plan_content = add_create_time_frontmatter(plan_content)

        reference_root = repo_root if store.is_in_tree else str(store.sdd_dir)
        if reference_root:
            from sase.sdd.frontmatter import set_frontmatter_fields
            from sase.sdd.plan_tiers import read_plan_tier_from_content

            fields = {"tier": read_plan_tier_from_content(plan_content) or "tale"}
            plan_content = set_frontmatter_fields(plan_content, fields)
            from sase.sdd.plan_header_writes import (
                refresh_bead_plan_section,
                refresh_existing_parent_section,
            )

            plan_content = refresh_existing_parent_section(
                plan_content,
                source_path=Path(plan_path),
                plans_root=store.kind_root("plans"),
                store=store,
                primary_root=Path(repo_root or cwd),
            )
            plan_content = refresh_bead_plan_section(
                plan_content,
                store=store,
                primary_root=Path(repo_root or cwd),
            )
            from sase.file_references import format_with_prettier

            plan_content = format_with_prettier(plan_content)

    from sase.sdd.committed_plan_validation import validate_plan_for_commit
    from sase.sdd.plan_tiers import read_plan_tier_from_content

    validate_plan_for_commit(
        plan_content,
        tier=read_plan_tier_from_content(plan_content),
        path=plan_path,
        yyyymm=yyyymm,
    )

    if store.is_in_tree or should_copy:
        Path(plan_path).parent.mkdir(parents=True, exist_ok=True)
        Path(plan_path).write_text(plan_content, encoding="utf-8")

    plan_ref = format_sase_plan_tag_value(
        plan_path,
        repo_root=repo_root,
        store=store,
    )
    if plan_ref is None:
        plan_ref = os.path.basename(plan_path)

    from sase.workflows.commit.runtime_tags import (
        LinkedCommitTagValue,
        update_trailing_commit_tags,
    )

    plan_target = format_sase_plan_link(plan_ref, store=store)
    plan_value: object = (
        LinkedCommitTagValue(plan_ref, plan_target) if plan_target else plan_ref
    )

    message = payload.get("message", "")
    payload["message"] = update_trailing_commit_tags(
        message, {"PLAN": plan_value}, remove_keys={"PLAN"}
    )

    # Mark plan as done
    subprocess.run(
        ["sed", "-i", "s/^status: wip$/status: done/", plan_path],
        check=False,
        capture_output=True,
    )

    # Store-backed plans must be committed after their status transition.  For a
    # copied archive this ensures the initial sidecar commit contains
    # ``status: done``; for an existing sidecar plan it avoids leaving the
    # completion change dirty and unpushed in the SDD clone.
    if (not plan_in_code_repo) and (should_copy or plan_in_store):
        from sase.sdd.files import commit_sdd_store_files

        action = "Add" if should_copy else "Complete"
        commit_sdd_store_files(
            store,
            f"{action} SDD plan for {os.path.splitext(os.path.basename(plan_path))[0]}",
            paths=[plan_path],
        )

    # Only stage plan files that belong to the code repository.
    if plan_in_code_repo:
        payload["_plan_path"] = plan_path
