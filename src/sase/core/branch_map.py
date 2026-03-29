"""Branch map persistence for immutable-branch VCS providers.

When a VCS provider cannot rename a branch (e.g. GitHub with an open PR),
the original branch name is persisted in a JSON mapping so that
``resolve_revision`` can still find the branch.

The mapping lives at ``~/.sase/projects/<project_basename>/branch_map.json``
and maps *current ChangeSpec name* → *actual git branch name*.
"""

import json
from pathlib import Path


def _branch_map_path(project_basename: str) -> Path:
    return Path.home() / ".sase" / "projects" / project_basename / "branch_map.json"


def read_branch_map(project_basename: str) -> dict[str, str]:
    """Read the branch map for a project.

    Returns an empty dict if the file does not exist.
    """
    path = _branch_map_path(project_basename)
    if not path.exists():
        return {}
    return json.loads(path.read_text())  # type: ignore[no-any-return]


def write_branch_alias(project_basename: str, name: str, branch: str) -> None:
    """Record that ChangeSpec *name* maps to *branch*."""
    path = _branch_map_path(project_basename)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = read_branch_map(project_basename)
    data[name] = branch
    path.write_text(json.dumps(data, indent=2) + "\n")


def remove_branch_alias(project_basename: str, name: str) -> None:
    """Remove the alias for *name*, deleting the file if empty."""
    path = _branch_map_path(project_basename)
    if not path.exists():
        return
    data: dict[str, str] = json.loads(path.read_text())
    if name not in data:
        return
    del data[name]
    if data:
        path.write_text(json.dumps(data, indent=2) + "\n")
    else:
        path.unlink()
