"""Utilities for writing version-controlled spec and plan (SDD) files."""

import subprocess
from pathlib import Path

from sase.config import load_merged_config


def get_sdd_config() -> bool:
    """Check if sdd.version_controlled is enabled in merged config."""
    config = load_merged_config()
    return bool(config.get("sdd", {}).get("version_controlled", False))


def get_sdd_dir(
    workspace_dir: str, workspace_num: int, version_controlled: bool
) -> Path:
    """Return the target directory for SDD files.

    If version_controlled: return Path(workspace_dir) (specs/ and plans/ at project root)
    If not: return primary_workspace / ".sase" / "sdd"
    """
    if version_controlled:
        return Path(workspace_dir)
    return (
        Path(_get_primary_workspace_dir(workspace_dir, workspace_num)) / ".sase" / "sdd"
    )


def _get_primary_workspace_dir(workspace_dir: str, workspace_num: int) -> str:
    """Derive primary workspace dir from current workspace.

    For workspace_num == 1, returns workspace_dir as-is.
    For workspace_num > 1, strips the ``_{workspace_num}`` suffix.
    """
    if workspace_num <= 1:
        return workspace_dir
    suffix = f"_{workspace_num}"
    stripped = workspace_dir.rstrip("/")
    if stripped.endswith(suffix):
        return stripped[: -len(suffix)]
    return workspace_dir


def init_beads(workspace_dir: str, workspace_num: int) -> Path:
    """Bootstrap `.sase/sdd/` as a standalone git repo for local SDD tracking.

    1. Creates `.sase/sdd/` in the primary workspace.
    2. Runs `git init` inside it if not already a git repo.
    3. Runs `bd init --quiet --skip-hooks` in the primary workspace if `.beads/` missing.

    Returns the `.sase/sdd/` path.
    """
    primary = _get_primary_workspace_dir(workspace_dir, workspace_num)
    sdd_dir = Path(primary) / ".sase" / "sdd"
    sdd_dir.mkdir(parents=True, exist_ok=True)

    if not (sdd_dir / ".git").is_dir():
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)

    beads_dir = Path(primary) / ".beads"
    if not beads_dir.is_dir():
        subprocess.run(
            ["bd", "init", "--quiet", "--skip-hooks"],
            cwd=primary,
            check=True,
            capture_output=True,
        )

    return sdd_dir


def commit_sdd_files(sdd_dir: Path, message: str) -> None:
    """Auto-commit SDD files in a local `.sase/sdd/` git repo.

    No-op if `sdd_dir` is not a git repo or there are no staged changes.
    """
    if not (sdd_dir / ".git").is_dir():
        return

    subprocess.run(["git", "add", "-A"], cwd=sdd_dir, check=True, capture_output=True)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=sdd_dir,
        capture_output=True,
    )
    if result.returncode != 0:
        # There are staged changes — commit them
        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )


def check_epic_available(workspace_dir: str, workspace_num: int) -> bool:
    """Check if the Epic option should be shown for plan approval.

    Requires both:
    1. ``sdd.version_controlled`` is enabled in merged config
    2. ``.beads/`` directory exists in the primary workspace
    """
    if not get_sdd_config():
        return False
    primary = _get_primary_workspace_dir(workspace_dir, workspace_num)
    return Path(primary, ".beads").is_dir()


def write_sdd_files(
    sdd_dir: Path,
    plan_name: str,
    spec_content: str,
    plan_file: str,
) -> tuple[Path, Path]:
    """Write specs/<name>.md and plans/<name>.md to sdd_dir.

    Returns (spec_path, plan_path).
    """
    specs_dir = sdd_dir / "specs"
    plans_dir = sdd_dir / "plans"
    specs_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)

    spec_path = specs_dir / f"{plan_name}.md"
    spec_path.write_text(spec_content, encoding="utf-8")

    plan_path = plans_dir / f"{plan_name}.md"
    plan_source = Path(plan_file)
    if plan_source.exists():
        plan_path.write_text(plan_source.read_text(encoding="utf-8"), encoding="utf-8")

    return spec_path, plan_path


def update_spec_with_qa(spec_path: Path, qa_markdown: str) -> None:
    """Append Q&A section to an existing spec file."""
    if not spec_path.exists():
        return
    existing = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(
        existing.rstrip("\n") + "\n\n" + qa_markdown + "\n", encoding="utf-8"
    )
