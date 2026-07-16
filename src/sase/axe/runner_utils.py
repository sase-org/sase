"""Compatibility imports for shared axe runner helpers.

New code should import from ``runner_artifacts``, ``runner_reporting``,
``runner_signals``, or ``runner_workspace`` according to responsibility.
"""

from sase.axe.runner_artifacts import (
    all_steps_hidden,
    clear_agent_meta_tag,
    detect_write_and_persist_review_agent_meta,
    publish_review_agent_env,
    read_agent_meta,
    write_agent_meta,
    write_done_marker,
)
from sase.axe.runner_reporting import (
    build_no_proposal_error_summary,
    finalize_axe_runner,
    format_markdown_fenced_block,
    write_error_report,
)
from sase.axe.runner_signals import (
    _killed_state,
    install_sigterm_handler,
    killed_at,
    reset_killed,
    was_killed,
)
from sase.axe.runner_workspace import (
    _clear_stale_git_index_lock,
    git_index_lock_path,
    prepare_launch_workspace_repos,
    prepare_workspace,
)

__all__ = [
    "all_steps_hidden",
    "build_no_proposal_error_summary",
    "clear_agent_meta_tag",
    "detect_write_and_persist_review_agent_meta",
    "finalize_axe_runner",
    "format_markdown_fenced_block",
    "git_index_lock_path",
    "install_sigterm_handler",
    "killed_at",
    "prepare_launch_workspace_repos",
    "prepare_workspace",
    "publish_review_agent_env",
    "read_agent_meta",
    "reset_killed",
    "was_killed",
    "write_agent_meta",
    "write_done_marker",
    "write_error_report",
]
