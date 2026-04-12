"""Git repository management for the memory store."""

import subprocess
from pathlib import Path


MEMORY_REPO_PATH = Path.home() / ".sase" / "memory"

_README_CONTENT = """\
# Sase Agent Memory

This repository stores structured memory files used by sase agents.

## Layout

- `global/system/` — Cross-project context, always loaded into prompts
- `global/` (non-system) — Cross-project context, loaded on demand
- `projects/<name>/system/` — Per-project context, always loaded
- `projects/<name>/` (non-system) — Per-project context, loaded on demand

Memory files use YAML frontmatter + markdown body.
"""


def get_repo_path() -> Path:
    """Return the memory repo path, checking config override first."""
    try:
        from sase.config import load_merged_config

        cfg = load_merged_config()
        mem_cfg = cfg.get("memory", {})
        if isinstance(mem_cfg, dict):
            repo_path = mem_cfg.get("repo_path")
            if repo_path:
                return Path(repo_path).expanduser()
    except Exception:
        pass
    return MEMORY_REPO_PATH


def ensure_repo() -> Path:
    """Initialize the memory repo if it doesn't exist, return its path."""
    repo = get_repo_path()
    if (repo / ".git").is_dir():
        return repo

    repo.mkdir(parents=True, exist_ok=True)

    # Initialize git repo
    run_git(repo, "init")

    # Create initial structure
    global_system = repo / "global" / "system"
    global_system.mkdir(parents=True, exist_ok=True)
    (global_system / ".gitkeep").touch()

    projects_dir = repo / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    (projects_dir / ".gitkeep").touch()

    # Write README
    (repo / "README.md").write_text(_README_CONTENT)

    # Initial commit
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "Initialize memory repository")

    return repo


def repo_exists() -> bool:
    """Check if the memory repo has been initialized."""
    return (get_repo_path() / ".git").is_dir()


def auto_commit(message: str) -> None:
    """Stage all changes in the memory repo and commit."""
    repo = get_repo_path()
    if not (repo / ".git").is_dir():
        raise RuntimeError("Memory repo not initialized. Run: sase memory init")

    run_git(repo, "add", "-A")

    # Check if there's anything to commit
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo,
        capture_output=True,
    )
    if result.returncode == 0:
        return  # Nothing staged

    run_git(repo, "commit", "-m", message)


def get_filetree(project: str | None = None) -> str:
    """Return directory tree of the memory repo as a string.

    If *project* is given, show only that project's subtree plus global/.
    Otherwise show the full tree.
    """
    repo = get_repo_path()
    if not repo.is_dir():
        return ""

    lines: list[str] = []
    _walk_tree(repo, repo, lines, project)
    return "\n".join(lines)


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in the given directory."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _walk_tree(
    root: Path,
    current: Path,
    lines: list[str],
    project: str | None,
    prefix: str = "",
) -> None:
    """Recursively build a tree listing, skipping .git and .gitkeep."""
    entries = sorted(
        e
        for e in current.iterdir()
        if e.name not in (".git", ".gitkeep", "__pycache__")
    )

    # Filter: if project is specified, under projects/ only show that project
    if project and current == root / "projects":
        entries = [e for e in entries if e.name == project]

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            extension = "    " if is_last else "\u2502   "
            _walk_tree(root, entry, lines, project, prefix + extension)
        else:
            lines.append(f"{prefix}{connector}{entry.name}")
