"""Utilities for writing version-controlled spec and plan (SDD) files."""

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
