"""Pre-commit hooks: beads, SASE_PLAN handling, and precommit command."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from sase.bead.project import BEADS_DIRNAME
from sase.config.core import load_merged_config
from sase.output import print_status
from sase.workflows.commit.plan_paths import (
    format_sase_plan_reference,
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


def run_precommit(cwd: str) -> bool:
    """Run the precommit_command from config, if configured."""
    config = load_merged_config()
    cmd = config.get("precommit_command", "")
    if not cmd:
        return True
    print_status(f"Running precommit command: {cmd}", "progress")
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        print_status(
            f"Precommit command failed (exit {result.returncode}): {cmd}",
            "error",
        )
        return False
    return True


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


def _infer_prompt_link(repo_root: str, plan_path: str) -> str | None:
    """Infer a repo-relative SDD prompt link for a plan path, if one exists."""
    from pathlib import Path

    from sase.sdd.files import find_sdd_file

    prompt = find_sdd_file(Path(repo_root), "prompts", os.path.basename(plan_path))
    if prompt is None:
        return None
    try:
        return prompt.relative_to(Path(repo_root)).as_posix()
    except ValueError:
        return os.path.relpath(prompt, repo_root).replace(os.sep, "/")


def handle_sase_plan(payload: dict, cwd: str) -> None:
    """Append PLAN= to commit message and mark plan as done."""
    plan_path = os.environ.get("SASE_PLAN", "")
    if not plan_path:
        return

    from sase.sdd.beads import get_sdd_config

    version_controlled = get_sdd_config()

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

    # Only copy plan into repo for version-controlled SDD projects
    if version_controlled and not in_repo:
        from sase.sdd.files import get_yyyymm

        yyyymm = _extract_yyyymm_from_plan(plan_path) or get_yyyymm()
        dest = os.path.join(cwd, "sdd", "tales", yyyymm, os.path.basename(plan_path))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(plan_path, dest)
        # Format the copied plan with prettier (safety net for
        # archives created before the plan_command_handler format step)
        from sase.gemini_wrapper.file_references import format_with_prettier

        raw = open(dest, encoding="utf-8").read()
        formatted = format_with_prettier(raw)
        if formatted != raw:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(formatted)
        plan_path = dest

    # Only add frontmatter for version-controlled plans
    if version_controlled:
        plan_content = open(plan_path, encoding="utf-8").read()
        if not plan_content.startswith("---\n"):
            from sase.llm_provider._plan_utils import add_create_time_frontmatter

            plan_content = add_create_time_frontmatter(plan_content)

        if repo_root:
            from sase.sdd.frontmatter import set_frontmatter_fields

            prompt_link = _infer_prompt_link(repo_root, plan_path)
            if prompt_link:
                plan_content = set_frontmatter_fields(
                    plan_content, {"prompt": prompt_link}
                )

        with open(plan_path, "w", encoding="utf-8") as f:
            f.write(plan_content)

    plan_ref = format_sase_plan_reference(plan_path, repo_root=repo_root)
    if plan_ref is None:
        plan_ref = os.path.basename(plan_path)

    # Append PLAN= to commit message (only for version-controlled projects)
    if version_controlled:
        message = payload.get("message", "")
        payload["message"] = f"{message}\n\nPLAN={plan_ref}"

    # Mark plan as done
    subprocess.run(
        ["sed", "-i", "s/^status: wip$/status: done/", plan_path],
        check=False,
        capture_output=True,
    )

    # Only stage plan file if version-controlled
    if version_controlled:
        payload["_plan_path"] = plan_path
