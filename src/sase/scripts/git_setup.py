"""Setup step for the #git xprompt workflow.

Delegates to :func:`sase.runner_providers.git.allocate_workspace` for the
shared allocation logic, then prints key=value output for the workflow
executor.
"""

from sase.runner_providers.git import allocate_workspace


def main(*, git_ref: str, n: int | None, release: bool) -> None:
    """Resolve git ref, claim a workspace, and print config.

    Prints key=value output for the workflow executor.
    """
    ctx = allocate_workspace(git_ref, n=n, release=release)

    print(f"project_name={ctx.project_name}")
    print(f"project_file={ctx.project_file}")
    print(f"workspace_dir={ctx.workspace_dir}")
    print(f"workspace_num={ctx.workspace_num}")
    print(f"checkout_target={ctx.checkout_target}")
    print(f"primary_workspace_dir={ctx.primary_workspace_dir}")
    print(f"should_release={'true' if ctx.should_release else 'false'}")
    print(f"_chdir={ctx.workspace_dir}")
    print(f"meta_workspace={ctx.workspace_num}")
