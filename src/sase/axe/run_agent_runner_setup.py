"""Pre-execution setup helpers for ``run_agent_runner``.

This module preserves the historical ``sase.axe.run_agent_runner_setup``
import surface while the implementation lives in smaller focused modules:

- ``run_agent_runner_setup_workspace``: occupancy guard, workspace
  preparation/entry, SDD base-SHA capture.
- ``run_agent_runner_setup_linked_repos``: linked-repo preparation/refresh.
- ``run_agent_runner_setup_prompt``: prompt preprocessing and launch helpers.
- ``run_agent_runner_setup_meta``: artifacts directory, agent meta,
  retry chain, telemetry, and the home-mode running marker.
"""

from sase.axe.run_agent_runner_setup_linked_repos import (
    prepare_linked_repo_workspaces_if_needed,
    refresh_linked_repos_for_workspace,
)
from sase.axe.run_agent_runner_setup_meta import (
    apply_retry_chain_to_meta,
    bump_spawn_telemetry,
    load_retry_handoff_from_env,
    setup_artifacts_directory,
    write_agent_meta,
    write_home_running_marker,
)
from sase.axe.run_agent_runner_setup_prompt import (
    build_output_variable_namespaces,
    expand_deferred_launch_xprompts,
    preprocess_prompt_xprompts,
    print_agent_start_banner,
    write_submitted_xprompt_artifact,
)
from sase.axe.run_agent_runner_setup_workspace import (
    capture_sdd_base_sha,
    enter_agent_workspace,
    guard_workspace_not_occupied,
    prepare_workspace_if_needed,
)

__all__ = [
    "apply_retry_chain_to_meta",
    "build_output_variable_namespaces",
    "bump_spawn_telemetry",
    "capture_sdd_base_sha",
    "enter_agent_workspace",
    "expand_deferred_launch_xprompts",
    "guard_workspace_not_occupied",
    "load_retry_handoff_from_env",
    "prepare_linked_repo_workspaces_if_needed",
    "prepare_workspace_if_needed",
    "preprocess_prompt_xprompts",
    "print_agent_start_banner",
    "refresh_linked_repos_for_workspace",
    "setup_artifacts_directory",
    "write_agent_meta",
    "write_home_running_marker",
    "write_submitted_xprompt_artifact",
]
