"""Setup step for the sync workflow: detect VCS type, CWD, and branch name."""

import os

from sase.vcs_provider._registry import detect_vcs_family, get_vcs_provider


def main(*, cwd: str = "") -> None:
    """Detect VCS type, determine working directory, and get branch name.

    Resolution order for working directory:
    1. ``cwd`` parameter (if non-empty)
    2. ``SASE_SYNC_CWD`` environment variable
    3. ``os.getcwd()``

    Prints key=value output for the workflow executor.
    """
    work_dir = cwd or os.environ.get("SASE_SYNC_CWD", "") or os.getcwd()
    work_dir = os.path.abspath(work_dir)

    vcs_type = detect_vcs_family(work_dir)
    if vcs_type is None:
        print("error=No VCS detected")
        print("vcs_type=unknown")
        print("branch_name=")
        print(f"cwd={work_dir}")
        return

    provider = get_vcs_provider(work_dir)
    success, branch = provider.get_branch_name(work_dir)
    branch_name = branch if success and branch else ""

    print(f"vcs_type={vcs_type}")
    print(f"branch_name={branch_name}")
    print(f"cwd={work_dir}")
    print(f"_chdir={work_dir}")
