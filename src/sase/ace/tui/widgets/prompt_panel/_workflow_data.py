"""Filesystem snapshot loading for workflow detail display."""

from pathlib import Path
from typing import Any

from ...models._loaders._json_cache import load_json_cached
from ...models.agent import Agent
from ._helpers import aggregate_meta_fields
from ._workflow_types import (
    EmbeddedMarkerMap,
    EmbeddedMetaMap,
    WorkflowDetailSnapshot,
    WorkflowJsonLoader,
)


def load_workflow_detail_snapshot(
    agent: Agent,
    *,
    json_loader: WorkflowJsonLoader = load_json_cached,
) -> WorkflowDetailSnapshot:
    """Load all workflow detail artifacts needed for one render pass."""
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir is None:
        return WorkflowDetailSnapshot(
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
    state = _load_workflow_state(artifacts_path, json_loader)
    steps = _workflow_steps(state)

    return WorkflowDetailSnapshot(
        artifacts_path=artifacts_path,
        workflow_state=state,
        inputs=_workflow_inputs(state),
        meta_raw=_workflow_meta_raw(steps),
        meta_fields=aggregate_meta_fields(steps),
        steps=steps,
        error=_string_or_none(state.get("error") if state else None),
        traceback=_string_or_none(state.get("traceback") if state else None),
        prompt_content=_load_workflow_prompt_from_snapshot(artifacts_path, state),
        embedded_markers=_load_embedded_markers(artifacts_path, json_loader),
        embedded_meta=_load_all_embedded_meta(artifacts_path, steps, json_loader),
    )


def _load_workflow_state(
    artifacts_path: Path,
    json_loader: WorkflowJsonLoader,
) -> dict[str, Any] | None:
    state_file = artifacts_path / "workflow_state.json"
    if not state_file.exists():
        return None

    try:
        data = json_loader(state_file)
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


def _load_embedded_markers(
    artifacts_path: Path,
    json_loader: WorkflowJsonLoader,
) -> EmbeddedMarkerMap:
    """Load all prompt_step_*.json markers and group by parent_step_index.

    Args:
        artifacts_path: Path to the workflow artifacts directory.
        json_loader: JSON loader function to use.

    Returns:
        Dict mapping parent_step_index to sorted list of marker dicts.
    """
    result: EmbeddedMarkerMap = {}

    for marker_file in artifacts_path.glob("prompt_step_*.json"):
        try:
            data = json_loader(marker_file)
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
    artifacts_path: Path,
    steps: list[dict[str, Any]],
    json_loader: WorkflowJsonLoader,
) -> EmbeddedMetaMap:
    """Load embedded_workflows_{step_name}.json for each step.

    Args:
        artifacts_path: Path to the workflow artifacts directory.
        steps: List of step state dicts from workflow_state.json.
        json_loader: JSON loader function to use.

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
            data = json_loader(meta_file)
            if isinstance(data, list) and data:
                result[step_name] = data
        except Exception:
            continue

    return result
