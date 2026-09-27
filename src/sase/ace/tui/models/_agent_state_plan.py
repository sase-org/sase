"""Plan association and workflow-step fields for the Agents tab model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class AgentStatePlanFields:
    """Canonical plan references and workflow-step identity for one agent row."""

    # Canonical plan association for detail-header enrichment. The source
    # references are retained so approval changes can switch between the
    # durable local archive and the committed SDD copy without re-reading
    # marker files on the render path.
    plan_path: str | None = None
    archived_plan_path: str | None = None
    sdd_plan_path: str | None = None
    plan_committed: bool | None = None

    # Parent-epic identity is independent from the phase agent's authored plan.
    # Older rows overloaded ``sdd_plan_path``; deferred enrichment recovers
    # their parent relationship from the local bead association instead.
    epic_plan_ref: str | None = None
    epic_bead_id: str | None = None
    phase_bead_id: str | None = None

    # Bug URL for agents with associated bug IDs
    bug: str | None = None

    # PR number for agents with associated PR
    cl_num: str | None = None

    # Parent workflow name for agent steps within workflows
    parent_workflow: str | None = None

    # Parent timestamp for agent steps (links to parent workflow entry)
    parent_timestamp: str | None = None

    # Workflow step name (clean, without tree decoration)
    step_name: str | None = None

    # Type of workflow step: "agent", "bash", or "python"
    step_type: str | None = None

    # Source code/command for bash/python steps
    step_source: str | None = None

    # Step output data
    step_output: dict[str, Any] | None = None

    # Artifact-index records can be loaded in a compact list shape and
    # hydrated on demand before detail rendering needs full outputs.
    record_shape: Literal["full", "list"] = field(default="full", compare=False)
    index_record_dir: str | None = field(default=None, compare=False)
    prompt_step_file_name: str | None = field(default=None, compare=False)

    # Step index for ordering (0-based)
    step_index: int | None = None

    # Total steps in the parent workflow (for step numbering display)
    total_steps: int | None = None

    # Parent step index for embedded workflow steps (0-based)
    parent_step_index: int | None = None

    # Total steps in the grandparent workflow (for embedded step display)
    parent_total_steps: int | None = None

    # Whether this is a hidden workflow step (hidden by default in Agents tab)
    is_hidden_step: bool = False

    # Whether this workflow step belongs to an appears-as-agent parent workflow
    parent_appears_as_agent: bool = False

    # Workflow that looks like an agent (all non-prompt steps hidden)
    appears_as_agent: bool = False

    # Anonymous (temporary) workflow created for ad-hoc runs
    is_anonymous: bool = False

    # Error message for failed agents (from HookStatusLine.suffix)
    error_message: str | None = None

    # True when error_message is the synthesized runner-failure fallback
    # rather than a recorded error. A recorded error from done.json beats a
    # synthetic one during RUNNING<->WORKFLOW dedup.
    error_is_synthetic: bool = False

    # Full traceback string for failed agents
    error_traceback: str | None = None

    # Transient activity surfaced from workflow_state.json while finalization
    # work is still running (for example Markdown PDF construction). The
    # prompt/detail header renders this as a labeled Activity field.
    activity: str | None = None
