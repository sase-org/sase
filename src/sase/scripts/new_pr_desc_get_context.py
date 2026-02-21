"""Get context step for the #new_pr_desc xprompt workflow."""

import subprocess
import tempfile

from sase.ace.changespec import find_all_changespecs
from sase.gh_workspace import get_default_branch, parse_workspace_dir


def main(*, name: str) -> None:
    """Find changespec, get diff and commit info for PR description generation.

    Prints key=value output for the workflow executor.
    """
    # Find the ChangeSpec
    changespec = None
    for cs in find_all_changespecs():
        if cs.name == name:
            changespec = cs
            break

    if changespec is None:
        print(f"error=ChangeSpec '{name}' not found")
        print("description=")
        print("diff=")
        print("workspace_dir=")
        print("default_branch=")
        print("branch_name=")
        return

    project_file = changespec.file_path
    workspace_dir = parse_workspace_dir(project_file)
    if not workspace_dir:
        print("error=WORKSPACE_DIR is not set for this project")
        print("description=")
        print("diff=")
        print("workspace_dir=")
        print("default_branch=")
        print(f"branch_name={name}")
        return

    default_branch_ref = get_default_branch(workspace_dir)
    default_branch = default_branch_ref.rsplit("/", 1)[-1]

    # Get description
    desc = changespec.description or "No description"

    # Get diff against default branch
    try:
        result = subprocess.run(
            ["git", "diff", f"origin/{default_branch}...{name}"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        diff = result.stdout[:5000] if result.returncode == 0 else ""
    except Exception:
        diff = ""

    # Get commit subjects
    try:
        result = subprocess.run(
            ["git", "log", "--format=%s", f"origin/{default_branch}..{name}"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        commits = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        commits = ""

    # Save diff to temp file for the prompt
    diff_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".diff", prefix="pr_desc_", delete=False
    )
    diff_file.write(diff)
    diff_file.close()

    print("error=")
    print(f"description={desc}")
    print(f"diff_file={diff_file.name}")
    print(f"commits={commits}")
    print(f"workspace_dir={workspace_dir}")
    print(f"default_branch={default_branch}")
    print(f"branch_name={name}")
    print(f"_chdir={workspace_dir}")
