"""Handler registry for provider host runtime operations."""

from __future__ import annotations

from sase.host.runtime_config_ops import (
    discover_plugins,
    fake_echo,
    fake_log,
    fake_sleep,
    fake_stderr,
)
from sase.host.runtime_llm import llm_invoke, llm_metadata
from sase.host.runtime_shared import OperationHandler
from sase.host.runtime_vcs import vcs_mutation_shadow, vcs_query
from sase.host.runtime_workflow import workflow_step_bash, workflow_step_python
from sase.host.runtime_workspace import workspace_metadata, workspace_resolve_ref
from sase.host.runtime_xprompt import xprompt_catalog


def runtime_handlers() -> dict[tuple[str, str], OperationHandler]:
    return {
        ("config", "fake.echo"): fake_echo,
        ("config", "fake.log"): fake_log,
        ("config", "fake.sleep"): fake_sleep,
        ("config", "fake.stderr"): fake_stderr,
        ("config", "host.discover_plugins"): discover_plugins,
        ("llm", "llm.metadata"): llm_metadata,
        ("llm", "llm.invoke"): llm_invoke,
        ("workflow.step", "workflow.step.bash"): workflow_step_bash,
        ("workflow.step", "workflow.step.python"): workflow_step_python,
        ("xprompt", "xprompt.catalog"): xprompt_catalog,
        ("vcs", "vcs.query"): vcs_query,
        ("vcs", "vcs.mutation"): vcs_mutation_shadow,
        ("workspace", "workspace.metadata"): workspace_metadata,
        ("workspace", "workspace.resolve_ref"): workspace_resolve_ref,
    }
