"""Repeat-chain finalization helpers for ``run_agent_runner``."""

from collections.abc import Callable, Mapping
from typing import Any

from sase.axe.run_agent_exec_markers import (
    write_done_marker_and_update_index as _write_done_marker_and_update_index,
)
from sase.axe.run_agent_phases import build_done_marker
from sase.axe.run_agent_repeat_stop import (
    STOP_OUTPUT_VARIABLE,
    RepeatStopDecision,
)
from sase.core.agent_output_variables import (
    set_agent_output_variables as _set_agent_output_variables,
)
from sase.core.output_variable_values import VarValue


def finalize_repeat_stop(
    *,
    decision: RepeatStopDecision,
    artifacts_dir: str,
    cl_name: str,
    project_file: str,
    timestamp: str,
    artifacts_timestamp: str,
    workspace_num: int,
    workspace_dir: str,
    output_path: str,
    agent_name: str | None,
    agent_model: str | None,
    agent_llm_provider: str | None,
    agent_vcs_provider: str | None,
    agent_hidden: bool,
    set_output_variables: Callable[[str, Mapping[str, VarValue]], Any] = (
        _set_agent_output_variables
    ),
    write_done_marker: Callable[[str, dict[str, Any]], Any] = (
        _write_done_marker_and_update_index
    ),
) -> None:
    """Finalize the current repeat slot as a successful skipped STOP slot.

    Propagates ``STOP`` into this slot's own output variables *before* writing
    the completed ``done.json`` marker: the next downstream waiter can only
    wake once this slot has a completed done marker, so writing the variable
    first guarantees the cascade always observes the propagated value.
    """
    set_output_variables(artifacts_dir, {STOP_OUTPUT_VARIABLE: decision.stop_value})
    done_marker = build_done_marker(
        cl_name,
        project_file,
        timestamp,
        artifacts_timestamp,
        workspace_num,
        workspace_dir,
        output_path,
        "completed",
        agent_name=agent_name,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
        agent_vcs_provider=agent_vcs_provider,
        agent_hidden=agent_hidden,
        repeat_stopped=True,
        stopped_by=decision.producer_name,
    )
    write_done_marker(artifacts_dir, done_marker)
    print(
        f"Repeat chain stopped by {decision.producer_name} "
        f"(STOP={decision.stop_value}); skipping execution"
    )
