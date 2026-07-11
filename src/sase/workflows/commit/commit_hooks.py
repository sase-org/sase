"""Commit hooks plus bead and SASE_PLAN handling."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from typing import Literal

from sase.bead.project import BEADS_DIRNAME
from sase.config.core import load_merged_config
from sase.output import print_status
from sase.workflows.commit.plan_paths import (
    format_sase_plan_tag_value,
    is_sase_plan_in_repo,
)


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


def enforce_bead_id_in_message(payload: dict) -> None:
    """Add payload["bead_id"] to the commit-message headline when present."""
    bead_id = payload.get("bead_id")
    if not bead_id:
        return

    bead_id = str(bead_id)
    message = str(payload.get("message", "") or "")
    first_line, sep, rest = message.partition("\n")
    if _message_line_has_bead_id(first_line, bead_id):
        return

    tagged_first_line = f"{first_line} ({bead_id})" if first_line else f"({bead_id})"
    payload["message"] = f"{tagged_first_line}{sep}{rest}"


def _message_line_has_bead_id(line: str, bead_id: str) -> bool:
    """Return True when *line* contains the exact bead ID as a token."""
    pattern = rf"(?<![A-Za-z0-9_.-]){re.escape(bead_id)}(?![A-Za-z0-9_.-])"
    return re.search(pattern, line) is not None


def handle_beads(payload: dict, cwd: str) -> None:
    """Close and sync beads best-effort; keep message tagging idempotent."""
    bead_id = payload.get("bead_id")
    has_bead_dir = os.path.isdir(os.path.join(cwd, BEADS_DIRNAME)) or os.path.isdir(
        os.path.join(cwd, ".beads")
    )

    if bead_id:
        # Close bead (best effort)
        print_status(f"Closing bead {bead_id}...", "progress")
        _run_bead_command(["sase", "bead", "close", bead_id], cwd)
        enforce_bead_id_in_message(payload)

    if bead_id or has_bead_dir:
        # Sync beads (best effort)
        _run_bead_command(["sase", "bead", "sync"], cwd)


def _run_bead_command(args: list[str], cwd: str) -> None:
    """Run a bead command best-effort, tolerating missing sase binary."""
    try:
        subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        print_status("Skipping bead command: `sase` CLI not found.", "warning")


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


def _infer_prompt_link(reference_root: str, plan_path: str) -> str | None:
    """Infer an SDD-root-relative prompt link for a plan path, if one exists."""
    from pathlib import Path

    from sase.sdd.files import find_sdd_file

    root = Path(reference_root)
    prompt = find_sdd_file(root, "prompts", os.path.basename(plan_path))
    if prompt is None:
        return None
    try:
        return prompt.relative_to(root).as_posix()
    except ValueError:
        return os.path.relpath(prompt, reference_root).replace(os.sep, "/")


def handle_sase_plan(payload: dict, cwd: str) -> None:
    """Append PLAN= to commit message and mark plan as done."""
    plan_path = os.environ.get("SASE_PLAN", "")
    if not plan_path:
        return

    from sase.sdd.store import resolve_sdd_store

    store = resolve_sdd_store(cwd, 1)

    # Determine repo root
    repo_root = _get_repo_root(cwd)
    in_repo = is_sase_plan_in_repo(plan_path, repo_root)

    # If plan file doesn't exist at the expected path, try the ~/.sase/plans/ archive
    if not os.path.isfile(plan_path):
        from sase.core.paths import find_sharded_file

        archive_fallback = find_sharded_file("plans", os.path.basename(plan_path))
        if archive_fallback is not None:
            plan_path = archive_fallback
            in_repo = False
        else:
            return  # truly missing

    if not os.path.isabs(plan_path) and repo_root:
        plan_path = os.path.join(repo_root, plan_path)

    plan_in_store = is_sase_plan_in_repo(plan_path, store.sdd_dir)
    # A nested store is physically under the workspace but belongs to its own
    # repository, so it must not be staged with the code commit.
    plan_in_code_repo = in_repo and (store.is_in_tree or not plan_in_store)
    should_copy = (
        not in_repo if store.is_in_tree else not plan_in_store and not plan_in_code_repo
    )

    if should_copy:
        from sase.sdd.files import get_yyyymm

        yyyymm = _extract_yyyymm_from_plan(plan_path) or get_yyyymm()
        dest = os.path.join(store.sdd_dir, "tales", yyyymm, os.path.basename(plan_path))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(plan_path, dest)
        # Format the copied plan with prettier (safety net for
        # archives created before the plan_command_handler format step)
        from sase.file_references import format_with_prettier

        raw = open(dest, encoding="utf-8").read()
        formatted = format_with_prettier(raw)
        if formatted != raw:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(formatted)
        plan_path = dest
        plan_in_code_repo = store.is_in_tree

    # Approved store-backed plans already received frontmatter when written.
    # Copied archives need the same normalization as in-tree plans.
    if store.is_in_tree or should_copy:
        plan_content = open(plan_path, encoding="utf-8").read()
        if not plan_content.startswith("---\n"):
            from sase.llm_provider._plan_utils import add_create_time_frontmatter

            plan_content = add_create_time_frontmatter(plan_content)

        reference_root = repo_root if store.is_in_tree else str(store.sdd_dir)
        if reference_root:
            from sase.sdd.frontmatter import set_frontmatter_fields

            prompt_link = _infer_prompt_link(reference_root, plan_path)
            if prompt_link:
                plan_content = set_frontmatter_fields(
                    plan_content, {"prompt": prompt_link}
                )

        with open(plan_path, "w", encoding="utf-8") as f:
            f.write(plan_content)

    plan_ref = format_sase_plan_tag_value(
        plan_path,
        repo_root=repo_root,
        store=store,
    )
    if plan_ref is None:
        plan_ref = os.path.basename(plan_path)

    from sase.workflows.commit.runtime_tags import update_trailing_commit_tags

    message = payload.get("message", "")
    payload["message"] = update_trailing_commit_tags(
        message, {"PLAN": plan_ref}, remove_keys={"PLAN"}
    )

    # Mark plan as done
    subprocess.run(
        ["sed", "-i", "s/^status: wip$/status: done/", plan_path],
        check=False,
        capture_output=True,
    )

    # Store-backed plans must be committed after their status transition.  For a
    # copied archive this ensures the initial companion commit contains
    # ``status: done``; for an existing companion plan it avoids leaving the
    # completion change dirty and unpushed in the SDD clone.
    if not store.is_in_tree and (should_copy or plan_in_store):
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
