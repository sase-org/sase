"""Workflow display mixin for the agent prompt panel."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.worker import Worker, WorkerState

from ...models._loaders._json_cache import load_json_cached
from ...models.agent import Agent
from ._helpers import (
    aggregate_meta_fields,
    append_model_field,
    format_output,
    get_rich_status_indicator,
)

# Display width for step header lines (name + status)
_STEP_LINE_WIDTH = 60

# Box drawing characters for embedded workflow sections
_BOX_TOP_LEFT = "\u250c"
_BOX_VERTICAL = "\u2502"
_BOX_BOTTOM_LEFT = "\u2514"
_BOX_HORIZONTAL = "\u2500"
_BOX_SEPARATOR = "\u2504"  # ┄ (dotted)

# Phase indicators
_PRE_ARROW = "\u25b2"  # ▲
_POST_ARROW = "\u25bc"  # ▼

# Style constants
_BORDER_STYLE = "#5F87AF"
_PRE_STYLE = "bold #5F87AF"
_POST_STYLE = "bold #D7AF5F"
_WORKFLOW_NAME_STYLE = "bold #AF87D7"
_STEP_NUM_STYLE = "bold #87D7FF"
_STEP_NAME_STYLE = "bold #AF87D7"


# Type alias: step_index -> list of embedded step marker dicts
EmbeddedMarkerMap = dict[int, list[dict[str, Any]]]

# Type alias: step_name -> list of embedded workflow metadata dicts
EmbeddedMetaMap = dict[str, list[dict[str, Any]]]


@dataclass(frozen=True)
class _WorkflowDetailSnapshot:
    """Filesystem-backed workflow detail data for one render pass."""

    artifacts_path: Path | None
    workflow_state: dict[str, Any] | None
    inputs: dict[str, Any] | None
    meta_raw: dict[str, str] | None
    meta_fields: list[tuple[str, str]]
    steps: list[dict[str, Any]]
    error: str | None
    traceback: str | None
    prompt_content: str | None
    embedded_markers: EmbeddedMarkerMap
    embedded_meta: EmbeddedMetaMap


@dataclass(frozen=True)
class _WorkflowDetailRenderRequest:
    """State captured when an async workflow detail render is started."""

    agent_identity: tuple[Any, ...]
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


class WorkflowDisplayMixin:
    """Mixin providing workflow-specific display methods for AgentPromptPanel."""

    def _update_workflow_display(self, agent: Agent) -> None:
        """Update display for a workflow agent.

        Args:
            agent: The workflow agent to display.
        """
        snapshot = _load_workflow_detail_snapshot(agent)
        self.update(_build_workflow_detail_renderable(agent, snapshot))  # type: ignore[attr-defined]

    def start_workflow_detail_render(
        self,
        agent: Agent,
        *,
        generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
        is_current: Callable[[tuple[Any, ...], int, str, int | None], bool],
    ) -> None:
        """Render a workflow parent row in a worker thread."""
        current_worker = getattr(self, "_workflow_detail_worker", None)
        if current_worker is not None and current_worker.is_running:
            current_worker.cancel()

        request = _WorkflowDetailRenderRequest(
            agent_identity=agent.identity,
            generation=generation,
            attempt_view_mode=attempt_view_mode,
            attempt_pinned_number=attempt_pinned_number,
            is_current=is_current,
        )
        self._workflow_detail_request = request  # type: ignore[attr-defined]

        def render_task() -> Group:
            snapshot = _load_workflow_detail_snapshot(agent)
            return _build_workflow_detail_renderable(agent, snapshot)

        self._workflow_detail_worker = self.run_worker(  # type: ignore[attr-defined]
            render_task, thread=True
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Apply async workflow detail worker results when still current."""
        self._apply_workflow_detail_worker_result(event.worker, event.state)

    def _apply_workflow_detail_worker_result(
        self, worker: Worker[Any], state: WorkerState
    ) -> None:
        current_worker = getattr(self, "_workflow_detail_worker", None)
        if worker != current_worker:
            return

        if state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._workflow_detail_worker = None  # type: ignore[attr-defined]

        if state != WorkerState.SUCCESS:
            return

        request: _WorkflowDetailRenderRequest | None = getattr(
            self, "_workflow_detail_request", None
        )
        if request is None:
            return
        if not request.is_current(
            request.agent_identity,
            request.generation,
            request.attempt_view_mode,
            request.attempt_pinned_number,
        ):
            return

        self.update(worker.result)  # type: ignore[attr-defined]

    def _load_workflow_inputs(self, agent: Agent) -> dict[str, Any] | None:
        """Load workflow inputs from workflow_state.json."""
        return _load_workflow_detail_snapshot(agent).inputs

    def _load_workflow_meta_raw(self, agent: Agent) -> dict[str, str] | None:
        """Load raw meta_* fields from workflow step outputs as a dict."""
        return _load_workflow_detail_snapshot(agent).meta_raw

    def _load_workflow_meta_fields(self, agent: Agent) -> list[tuple[str, str]]:
        """Load aggregated meta_* fields from workflow step outputs."""
        return _load_workflow_detail_snapshot(agent).meta_fields

    def _load_workflow_prompt(self, agent: Agent) -> str | None:
        """Load prompt content for a workflow."""
        return _load_workflow_detail_snapshot(agent).prompt_content

    def _load_workflow_steps_rich(self, agent: Agent) -> Text | None:
        """Load and format workflow steps as a rich Text from workflow_state.json."""
        return _workflow_steps_rich_from_snapshot(_load_workflow_detail_snapshot(agent))


def _load_workflow_detail_snapshot(agent: Agent) -> _WorkflowDetailSnapshot:
    """Load all workflow detail artifacts needed for one render pass."""
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return _WorkflowDetailSnapshot(
            artifacts_path=None,
            workflow_state=None,
            inputs=None,
            meta_raw=None,
            meta_fields=[],
            steps=[],
            error=None,
            traceback=None,
            prompt_content=None,
            embedded_markers={},
            embedded_meta={},
        )

    artifacts_path = Path(artifacts_dir)
    state = _load_workflow_state(artifacts_path)
    steps = _workflow_steps(state)

    return _WorkflowDetailSnapshot(
        artifacts_path=artifacts_path,
        workflow_state=state,
        inputs=_workflow_inputs(state),
        meta_raw=_workflow_meta_raw(steps),
        meta_fields=aggregate_meta_fields(steps),
        steps=steps,
        error=_string_or_none(state.get("error") if state else None),
        traceback=_string_or_none(state.get("traceback") if state else None),
        prompt_content=_load_workflow_prompt_from_snapshot(artifacts_path, state),
        embedded_markers=_load_embedded_markers(artifacts_path),
        embedded_meta=_load_all_embedded_meta(artifacts_path, steps),
    )


def _build_workflow_detail_renderable(
    agent: Agent, snapshot: _WorkflowDetailSnapshot
) -> Group:
    """Build the rich workflow-detail renderable from an existing snapshot."""
    header_text = Text()

    # Header - WORKFLOW DETAILS
    header_text.append("WORKFLOW DETAILS\n", style="bold #D7AF5F underline")
    header_text.append("\n")

    # Workflow name (stored in workflow field)
    header_text.append("Workflow: ", style="bold #87D7FF")
    header_text.append(f"{agent.workflow or 'unknown'}\n", style="#AF87D7 bold")

    # Extract meta_* overrides from step outputs
    meta_project = None
    meta_changespec = None
    meta_workspace = None
    meta_fields_data = snapshot.meta_raw
    if meta_fields_data:
        meta_project = meta_fields_data.get("meta_project")
        meta_changespec = meta_fields_data.get("meta_changespec")
        meta_workspace = meta_fields_data.get("meta_workspace")

    # Project/ChangeSpec with meta_* priority
    if meta_project:
        header_text.append("Project: ", style="bold #87D7FF")
        header_text.append(f"{meta_project}\n", style="#00D7AF")
    elif meta_changespec:
        header_text.append("ChangeSpec: ", style="bold #87D7FF")
        header_text.append(f"{meta_changespec}\n", style="#00D7AF")
    else:
        header_text.append("ChangeSpec: ", style="bold #87D7FF")
        header_text.append(f"{agent.cl_name}\n", style="#00D7AF")

    # Workspace (if available) - check meta_workspace first, then agent field
    workspace_num = meta_workspace or agent.workspace_num
    if workspace_num is not None:
        header_text.append("Workspace: ", style="bold #87D7FF")
        header_text.append(f"#{workspace_num}\n", style="#5FD7FF")

    # Model (with provider-themed styling)
    append_model_field(header_text, agent.model, agent.llm_provider)

    # VCS provider
    if agent.vcs_provider:
        header_text.append("VCS: ", style="bold #87D7FF")
        header_text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")

    # Status
    header_text.append("Status: ", style="bold #87D7FF")
    status_style = {
        "RUNNING": "#87D7FF",
        "WAITING": "#FF87D7",
        "WAITING INPUT": "#FFAF5F",
        "DONE": "#5FD75F",
        "FAILED": "#FF5F5F",
        "PLAN": "#FF87AF",
        "PLAN APPROVED": "#00D7AF",
        "TALE APPROVED": "#00D7AF",
        "PLAN REJECTED": "#D7AF5F",
        "EPIC CREATED": "#5FD7AF",
        "QUESTION": "#FFAF00",
    }.get(agent.status, "#D7D7FF")
    header_text.append(f"{agent.status}\n", style=status_style)
    if agent.activity:
        header_text.append("Activity: ", style="bold #87D7FF")
        header_text.append(f"{agent.activity}\n", style="bold #D7AF5F")

    # Timestamp(s)
    header_text.append("Timestamps: ", style="bold #87D7FF")
    header_text.append(f"{agent.timestamps_display}\n", style="#D7D7FF")

    # PID (if available)
    if agent.pid:
        header_text.append("PID: ", style="bold #87D7FF")
        header_text.append(f"{agent.pid}\n", style="#FF87D7 bold")

    # Error message (for failed workflows)
    if agent.error_message:
        header_text.append("\n")
        header_text.append("ERROR\n", style="bold #FF5F5F underline")
        header_text.append(f"{agent.error_message}\n", style="bold #FF5F5F")
        if agent.output_path:
            header_text.append("Output: ", style="bold #87D7FF")
            header_text.append(f"{agent.output_path}\n", style="dim")

    # Compute traceback renderable for ERROR section
    error_tb_syntax: Syntax | None = None
    if agent.error_traceback:
        error_tb_syntax = Syntax(
            agent.error_traceback,
            "pytb",
            theme="monokai",
            word_wrap=True,
        )

    # Meta fields aggregated from all step outputs
    meta_fields = snapshot.meta_fields
    if meta_fields:
        header_text.append("\n")
        for name, value in meta_fields:
            header_text.append(f"{name}: ", style="bold #87D7FF")
            header_text.append(f"{value}\n", style="#5FD75F")

    # Inputs (if available)
    inputs = snapshot.inputs
    if inputs:
        header_text.append("\n")
        header_text.append("INPUTS\n", style="bold #D7AF5F underline")
        for key, value in inputs.items():
            header_text.append(f"  {key}: ", style="bold #87D7FF")
            if isinstance(value, str):
                header_text.append(f'"{value}"\n', style="#5FD75F")
            else:
                header_text.append(f"{value}\n", style="#5FD75F")

    # Separator + WORKFLOW STEPS header
    steps_header = Text()
    steps_header.append("\n")
    steps_header.append("─" * 50 + "\n", style="dim")
    steps_header.append("\n")
    steps_header.append("WORKFLOW STEPS\n", style="bold #D7AF5F underline")
    steps_header.append("\n")

    # Load and format workflow steps from workflow_state.json
    steps_rich = _workflow_steps_rich_from_snapshot(snapshot)
    renderables: list[Text | Syntax] = [header_text]
    if error_tb_syntax:
        renderables.append(error_tb_syntax)
    renderables.append(steps_header)
    if steps_rich:
        renderables.append(steps_rich)
    else:
        steps_header.append("No workflow state found.\n", style="dim italic")

    # AGENT PROMPT section - show the prompt that was attempted
    prompt_content = snapshot.prompt_content
    if prompt_content:
        prompt_header = Text()
        prompt_header.append("\n")
        prompt_header.append("─" * 50 + "\n", style="dim")
        prompt_header.append("\n")
        prompt_header.append("AGENT PROMPT\n", style="bold #D7AF5F underline")
        prompt_header.append("\n")
        renderables.append(prompt_header)
        renderables.append(
            Syntax(prompt_content, "markdown", theme="monokai", word_wrap=True)
        )

    return Group(*renderables)


def _load_workflow_state(artifacts_path: Path) -> dict[str, Any] | None:
    state_file = artifacts_path / "workflow_state.json"
    if not state_file.exists():
        return None

    try:
        data = load_json_cached(state_file)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _workflow_inputs(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    inputs = state.get("inputs")
    return inputs if isinstance(inputs, dict) and inputs else None


def _workflow_steps(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if state is None:
        return []
    steps = state.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


def _workflow_meta_raw(steps: list[dict[str, Any]]) -> dict[str, str] | None:
    meta: dict[str, str] = {}
    for step in steps:
        output = step.get("output")
        if isinstance(output, dict):
            for key, value in output.items():
                if key.startswith("meta_") and value:
                    meta[key] = str(value)
    return meta if meta else None


def _load_workflow_prompt_from_snapshot(
    artifacts_path: Path,
    state: dict[str, Any] | None,
) -> str | None:
    prompt_file = _earliest_prompt_file(artifacts_path)
    if prompt_file is not None:
        try:
            return prompt_file.read_text(encoding="utf-8")
        except Exception:
            pass

    if state is None:
        return None
    return _workflow_prompt_fallback(state)


def _earliest_prompt_file(artifacts_path: Path) -> Path | None:
    prompt_files: list[tuple[float, Path]] = []
    for path in artifacts_path.glob("*_prompt.md"):
        try:
            prompt_files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if not prompt_files:
        return None
    prompt_files.sort(key=lambda item: item[0])
    return prompt_files[0][1]


def _workflow_prompt_fallback(state: dict[str, Any]) -> str | None:
    step_prompts = state.get("step_prompts", [])
    if not isinstance(step_prompts, list):
        return None

    prompts = [
        step_prompt["agent"]
        for step_prompt in step_prompts
        if isinstance(step_prompt, dict) and step_prompt.get("agent")
    ]
    if not prompts:
        return None
    if len(prompts) == 1:
        return str(prompts[0])

    parts: list[str] = []
    for step_prompt in step_prompts:
        if not isinstance(step_prompt, dict) or not step_prompt.get("agent"):
            continue
        parts.append(f"## Step: {step_prompt.get('name')}\n\n{step_prompt['agent']}")
    return "\n\n---\n\n".join(parts)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _workflow_steps_rich_from_snapshot(
    snapshot: _WorkflowDetailSnapshot,
) -> Text | None:
    steps = snapshot.steps
    if not steps:
        if snapshot.error:
            text = Text()
            text.append("Error: ", style="bold #FF5F5F")
            text.append(f"{snapshot.error}\n", style="#FF5F5F")
            if snapshot.traceback:
                text.append("\nTraceback:\n", style="bold #FF5F5F")
                text.append(f"{snapshot.traceback}\n", style="dim")
            return text
        return None

    return _format_workflow_steps_rich(
        steps, snapshot.embedded_markers, snapshot.embedded_meta
    )


def _load_embedded_markers(artifacts_path: Path) -> EmbeddedMarkerMap:
    """Load all prompt_step_*.json markers and group by parent_step_index.

    Args:
        artifacts_path: Path to the workflow artifacts directory.

    Returns:
        Dict mapping parent_step_index to sorted list of marker dicts.
    """
    result: EmbeddedMarkerMap = {}

    for marker_file in artifacts_path.glob("prompt_step_*.json"):
        try:
            data = load_json_cached(marker_file)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        parent_idx = data.get("parent_step_index")
        if parent_idx is None:
            continue

        result.setdefault(parent_idx, []).append(data)

    # Sort each group by step_index
    for markers in result.values():
        markers.sort(key=lambda m: m.get("step_index", 0))

    return result


def _load_all_embedded_meta(
    artifacts_path: Path, steps: list[dict[str, Any]]
) -> EmbeddedMetaMap:
    """Load embedded_workflows_{step_name}.json for each step.

    Args:
        artifacts_path: Path to the workflow artifacts directory.
        steps: List of step state dicts from workflow_state.json.

    Returns:
        Dict mapping step_name to list of workflow metadata dicts.
    """
    result: EmbeddedMetaMap = {}

    for step in steps:
        step_name = step.get("name")
        if not step_name:
            continue

        meta_file = artifacts_path / f"embedded_workflows_{step_name}.json"
        if not meta_file.exists():
            continue

        try:
            data = load_json_cached(meta_file)
            if isinstance(data, list) and data:
                result[step_name] = data
        except Exception:
            continue

    return result


def _format_workflow_steps_rich(
    steps: list[dict[str, Any]],
    embedded_markers: EmbeddedMarkerMap,
    embedded_meta: EmbeddedMetaMap,
) -> Text:
    """Build a rich Text renderable for all workflow steps.

    Args:
        steps: List of step state dicts from workflow_state.json.
        embedded_markers: Embedded step markers grouped by parent_step_index.
        embedded_meta: Embedded workflow metadata grouped by step_name.

    Returns:
        Rich Text renderable.
    """
    text = Text()
    total_steps = len(steps)

    for i, step in enumerate(steps):
        step_name = step.get("name", "unknown")
        status = step.get("status", "pending")
        output = step.get("output")
        error = step.get("error")
        tb = step.get("traceback")

        # Step header line: "Step 1/6 ─ setup ─────────── ✓ completed"
        _render_step_header(text, i, total_steps, step_name, status)

        # Separator line
        text.append(
            "  " + _BOX_HORIZONTAL * _STEP_LINE_WIDTH + "\n", style=_BORDER_STYLE
        )

        # Embedded workflow sections (if any)
        markers = embedded_markers.get(i, [])
        meta_list = embedded_meta.get(step_name, [])
        if markers:
            text.append("\n")
            _render_embedded_sections(text, markers, meta_list)

        # Error (if any)
        if error:
            text.append("    Error: ", style="bold #FF5F5F")
            text.append(f"{error}\n", style="#FF5F5F")

        # Traceback (if any)
        if tb:
            text.append("    Traceback:\n", style="bold #FF5F5F")
            for line in tb.splitlines():
                text.append(f"      {line}\n", style="dim")

        # Output (if any)
        if output:
            output_str = format_output(output)
            text.append("    Output:\n", style="dim")
            for line in output_str.splitlines():
                text.append(f"      {line}\n", style="dim")

        text.append("\n")

    return text


def _render_step_header(
    text: Text,
    index: int,
    total: int,
    name: str,
    status: str,
) -> None:
    """Render a step header line into a Text object.

    Format: "  Step 1/6 ─ setup ─────────────────── ✓ completed"

    Args:
        text: Text object to append to.
        index: 0-based step index.
        total: Total number of steps.
        name: Step name.
        status: Step status string.
    """
    text.append("  Step ", style=_STEP_NUM_STYLE)
    text.append(f"{index + 1}/{total}", style=_STEP_NUM_STYLE)
    text.append(f" {_BOX_HORIZONTAL} ", style=_BORDER_STYLE)
    text.append(name, style=_STEP_NAME_STYLE)
    text.append(" ", style="")

    # Status symbol + label at the right
    symbol, style = get_rich_status_indicator(status)
    status_label = f"{symbol} {status}"

    # Fill with ─ between name and status
    # Calculate used width: "  Step X/Y ─ {name} " + status_label
    prefix_len = len(f"  Step {index + 1}/{total} {_BOX_HORIZONTAL} {name} ")
    fill_len = max(1, _STEP_LINE_WIDTH + 2 - prefix_len - len(status_label))
    text.append(_BOX_HORIZONTAL * fill_len + " ", style=_BORDER_STYLE)
    text.append(f"{status_label}\n", style=style)


def _render_embedded_sections(
    text: Text,
    markers: list[dict[str, Any]],
    meta_list: list[dict[str, Any]],
) -> None:
    """Render boxed embedded workflow sections into a Text object.

    Groups markers by embedded_workflow_name, then renders each group
    as a bordered box with PRE/POST labels.

    Args:
        text: Text object to append to.
        markers: List of embedded step marker dicts (sorted by step_index).
        meta_list: List of embedded workflow metadata dicts for display names.
    """
    # Build a lookup for workflow display names from metadata
    meta_lookup: dict[str, str] = {}
    for meta in meta_list:
        wf_name = meta.get("name", "")
        args = meta.get("args", {})
        args = {k: v for k, v in args.items() if v != ""}
        if args:
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            meta_lookup[wf_name] = f"#{wf_name}({args_str})"
        else:
            meta_lookup[wf_name] = f"#{wf_name}"

    # Group markers by embedded_workflow_name, preserving order
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    seen: dict[str, int] = {}
    for marker in markers:
        wf_name = marker.get("embedded_workflow_name", "")
        if not wf_name:
            continue
        if wf_name in seen:
            groups[seen[wf_name]][1].append(marker)
        else:
            seen[wf_name] = len(groups)
            groups.append((wf_name, [marker]))

    box_width = _STEP_LINE_WIDTH - 4  # indent is "    "

    for wf_name, group_markers in groups:
        display_name = meta_lookup.get(wf_name, f"#{wf_name}")

        # Top border: ┌─ #workflow_name ─────────────
        text.append(f"    {_BOX_TOP_LEFT}{_BOX_HORIZONTAL} ", style=_BORDER_STYLE)
        text.append(display_name, style=_WORKFLOW_NAME_STYLE)
        text.append(" ", style="")
        name_len = len(f"{_BOX_TOP_LEFT}{_BOX_HORIZONTAL} {display_name} ")
        fill = max(1, box_width - name_len)
        text.append(_BOX_HORIZONTAL * fill + "\n", style=_BORDER_STYLE)

        # Separate into pre and post steps
        pre_steps = [m for m in group_markers if m.get("is_pre_prompt_step", False)]
        post_steps = [
            m for m in group_markers if not m.get("is_pre_prompt_step", False)
        ]

        # Render PRE steps
        for marker in pre_steps:
            _render_embedded_step_line(text, marker, is_pre=True)

        # Separator between pre and post (if both exist)
        if pre_steps and post_steps:
            text.append(f"    {_BOX_VERTICAL}  ", style=_BORDER_STYLE)
            text.append(_BOX_SEPARATOR * (box_width - 3) + "\n", style="dim")

        # Render POST steps
        for marker in post_steps:
            _render_embedded_step_line(text, marker, is_pre=False)

        # Bottom border: └──────────────────────────
        text.append(f"    {_BOX_BOTTOM_LEFT}", style=_BORDER_STYLE)
        text.append(_BOX_HORIZONTAL * (box_width - 1) + "\n", style=_BORDER_STYLE)
        text.append("\n")


def _render_embedded_step_line(
    text: Text, marker: dict[str, Any], *, is_pre: bool
) -> None:
    """Render a single embedded step line with phase and status.

    Format: "    │  ▲ PRE   step_name              ✓ completed"

    Args:
        text: Text object to append to.
        marker: The embedded step marker dict.
        is_pre: Whether this is a pre-prompt step.
    """
    step_name = marker.get("step_name", "unknown")
    status = marker.get("status", "pending")

    # Left border
    text.append(f"    {_BOX_VERTICAL}  ", style=_BORDER_STYLE)

    # Phase arrow and label
    if is_pre:
        text.append(f"{_PRE_ARROW} PRE   ", style=_PRE_STYLE)
    else:
        text.append(f"{_POST_ARROW} POST  ", style=_POST_STYLE)

    # Step name (left-aligned with padding)
    name_col_width = 30
    padded_name = step_name.ljust(name_col_width)
    text.append(padded_name, style="")

    # Status
    symbol, style = get_rich_status_indicator(status)
    text.append(f"{symbol} {status}\n", style=style)
