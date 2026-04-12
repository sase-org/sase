"""Pre-commit hooks: beads, SASE_PLAN handling, and precommit command."""

from __future__ import annotations

import os
import shutil
import subprocess

from sase.config.core import load_merged_config
from sase.output import print_status


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


def handle_beads(payload: dict, cwd: str) -> None:
    """Close and sync beads, inject bead ID into commit message."""
    bead_id = payload.get("bead_id")
    has_bead_dir = os.path.isdir(os.path.join(cwd, ".sase_beads")) or os.path.isdir(
        os.path.join(cwd, ".beads")
    )

    if bead_id:
        # Close bead (best effort)
        print_status(f"Closing bead {bead_id}...", "progress")
        subprocess.run(
            ["sase", "bead", "close", bead_id],
            cwd=cwd,
            capture_output=True,
            check=False,
        )
        # Inject bead ID into commit message headline
        message = payload.get("message", "")
        if f"({bead_id})" not in message:
            first_line, sep, rest = message.partition("\n")
            payload["message"] = f"{first_line} ({bead_id}){sep}{rest}"

    if bead_id or has_bead_dir:
        # Sync beads (best effort)
        subprocess.run(
            ["sase", "bead", "sync"],
            cwd=cwd,
            capture_output=True,
            check=False,
        )


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


def handle_sase_plan(payload: dict, cwd: str) -> None:
    """Append PLAN= to commit message and mark plan as done."""
    plan_path = os.environ.get("SASE_PLAN", "")
    if not plan_path:
        return

    from sase.sdd.beads import get_sdd_config

    version_controlled = get_sdd_config()

    # Determine repo root
    repo_root = _get_repo_root(cwd)
    in_repo = bool(repo_root) and plan_path.startswith(repo_root + "/")

    # If plan file doesn't exist at the expected path, try the ~/.sase/plans/ archive
    if not os.path.isfile(plan_path):
        archive_fallback = os.path.join(
            os.path.expanduser("~"), ".sase", "plans", os.path.basename(plan_path)
        )
        if os.path.isfile(archive_fallback):
            plan_path = archive_fallback
            in_repo = False
        else:
            return  # truly missing

    # Only copy plan into repo for version-controlled SDD projects
    if version_controlled and not in_repo:
        from sase.sdd.files import get_yyyymm

        yyyymm = _extract_yyyymm_from_plan(plan_path) or get_yyyymm()
        dest = os.path.join(cwd, "plans", yyyymm, os.path.basename(plan_path))
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

            with open(plan_path, "w", encoding="utf-8") as f:
                f.write(add_create_time_frontmatter(plan_content))

    # Compute repo-root-relative path
    if repo_root and plan_path.startswith(repo_root + "/"):
        plan_rel = plan_path[len(repo_root) + 1 :]
    else:
        plan_rel = (
            os.path.relpath(plan_path, repo_root)
            if repo_root
            else os.path.basename(plan_path)
        )

    # Append PLAN= to commit message (only for version-controlled projects)
    if version_controlled:
        message = payload.get("message", "")
        payload["message"] = f"{message}\n\nPLAN={plan_rel}"

    # Mark plan as done
    subprocess.run(
        ["sed", "-i", "s/^status: wip$/status: done/", plan_path],
        check=False,
        capture_output=True,
    )

    # Only stage plan file if version-controlled
    if version_controlled:
        payload["_plan_path"] = plan_path
