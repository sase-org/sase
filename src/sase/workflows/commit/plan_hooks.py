"""Commit-time SASE plan archival, tagging, and completion handling."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from sase.workflows.commit.hook_utils import get_repo_root
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
    match = re.search(r"^create_time:\s*(\d{4})-(\d{2})", fm, re.MULTILINE)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return None


def _store_owning_plan_path(
    plan_path: Path,
    code_repo_root: str,
) -> SddStore | None:
    """Return the external SDD clone that directly owns *plan_path*."""

    plan_repo_root = get_repo_root(str(plan_path.parent))
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

    repo_root = get_repo_root(cwd)
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
