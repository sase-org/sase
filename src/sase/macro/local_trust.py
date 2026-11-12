"""Apply digest-pinned local-command trust to config-defined macros.

The shared policy lives in Rust and the enforcement adapter. This module
is the macro-side consumer: it partitions prompt-only vs executable config
entries, filters independent loaders, attaches a trust descriptor to local
executable workflows, and refuses explicit requests for blocked names.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.macro._exceptions import LocalMacroTrustError
from sase.macro.discovery_order import RANK_FILESYSTEM_BASE
from sase.macro.workflow_models import Workflow, WorkflowExecutionError


def workflow_mapping_from_macro_entry(value: Any) -> dict[str, Any] | None:
    """Return a workflow mapping for one config macro entry, if executable.

    Prompt-only strings and structured prompt definitions return ``None``.
    A top-level ``bash``/``python`` field is wrapped as a single step so
    ``load_workflow_from_mapping`` can parse it.
    """
    if not isinstance(value, dict):
        return None
    steps = value.get("steps")
    if isinstance(steps, list):
        return dict(value)
    bash = value.get("bash")
    python = value.get("python")
    has_bash = isinstance(bash, str)
    has_python = isinstance(python, str)
    if not has_bash and not has_python:
        return None
    mapping = {
        key: item for key, item in value.items() if key not in {"bash", "python"}
    }
    step: dict[str, Any] = {"name": "main"}
    if has_bash:
        step["bash"] = bash
    else:
        step["python"] = python
    mapping["steps"] = [step]
    return mapping


def partition_config_macros(
    macros_data: Mapping[str, Any],
    *,
    lower_macros: Mapping[str, Any] | None = None,
    source: str = "config",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split one config macros mapping into prompt-only vs executable.

    Classification uses the shared Rust projection. Binding failures fail
    closed: entries that look executable are treated as executable.
    """
    if not macros_data:
        return {}, {}
    layer = {"macros": dict(macros_data)}
    try:
        from sase.config.local_trust import project_local_commands

        projection = project_local_commands(
            layer,
            lower_macros=dict(lower_macros or {}),
            source=source,
        )
    except Exception:
        return _partition_by_shape(macros_data)
    executable_names = _executable_names_from_projection(
        projection.blocked_paths,
        projection.projection,
        macros_data,
    )
    prompt_only = {
        name: value
        for name, value in macros_data.items()
        if name not in executable_names
    }
    executable = {
        name: value for name, value in macros_data.items() if name in executable_names
    }
    return prompt_only, executable


def _trust_descriptor_from_evaluation(evaluation: Any) -> dict[str, Any]:
    """Return the small descriptor retained with a local executable workflow."""
    return {
        "identity": getattr(evaluation, "identity", None),
        "config_path": getattr(evaluation, "config_path", None),
        "logical_path": getattr(evaluation, "logical_path", None),
        "digest": getattr(evaluation, "digest", None),
        "status": getattr(evaluation, "status", None),
        "enabled": getattr(evaluation, "enabled", True),
        "policy_version": getattr(evaluation, "policy_version", None),
    }


def _attach_trust_to_steps(steps: list[Any], descriptor: dict[str, Any]) -> None:
    """Retain the source descriptor on nested executable step records."""
    for step in steps:
        if step.trust is None:
            step.trust = dict(descriptor)
        parallel = getattr(step, "parallel_config", None)
        nested = getattr(parallel, "steps", None)
        if isinstance(nested, list):
            _attach_trust_to_steps(nested, descriptor)


def attach_local_trust(workflow: Workflow, evaluation: Any) -> Workflow:
    """Copy the current local trust descriptor onto *workflow*."""
    descriptor = _trust_descriptor_from_evaluation(evaluation)
    workflow.trust = descriptor
    _attach_trust_to_steps(workflow.steps, descriptor)
    return workflow


def blocked_local_macro_message(
    name: str,
    *,
    catalog_item: Any | None = None,
    extra_names: set[str] | None = None,
    project: str | None = None,
) -> str | None:
    """Return a trust error for an explicit blocked local macro, else None.

    File-backed definitions (discovery rank at or above filesystem) keep
    winning over config. A remaining lower-priority namesake is refused
    rather than executed. Workflow-local extras in *extra_names* are
    allowed because they are not config-local contributions.
    """
    if extra_names and name in extra_names:
        return None
    if catalog_item is not None and _is_filesystem_definition(catalog_item):
        return None
    evaluation = _blocking_evaluation_for_name(name, project=project)
    if evaluation is None:
        return None
    config_path = evaluation.config_path or "the selected local config"
    return (
        f"Local macro '{name}' is blocked without current trust "
        f"(config {config_path}); run `sase config trust allow {config_path}` "
        "after review"
    )


def assert_workflow_local_trust(
    workflow: Workflow,
    *,
    step_name: str,
    step_trust: Mapping[str, Any] | None = None,
) -> None:
    """Revalidate a retained local descriptor before bash/python dispatch.

    Changed config or revocation blocks further local execution. A command
    already started is not terminated. User-origin workflows (no descriptor)
    proceed.
    """
    descriptor = step_trust or workflow.trust
    if not descriptor:
        source = workflow.source_path or ""
        if source == "local_config" or source.startswith("project_local_config:"):
            try:
                from sase.config.local_trust_enforcement import (
                    is_local_command_trust_enabled,
                )

                if is_local_command_trust_enabled():
                    raise WorkflowExecutionError(
                        f"Local workflow '{workflow.name}' step '{step_name}' "
                        "skipped without current trust"
                    )
            except WorkflowExecutionError:
                raise
            except Exception:
                raise WorkflowExecutionError(
                    f"Local workflow '{workflow.name}' step '{step_name}' "
                    "skipped without current trust"
                ) from None
        return
    try:
        from sase.config.local_trust_enforcement import validate_trust_descriptor

        trusted = validate_trust_descriptor(descriptor)
    except Exception:
        trusted = False
    if trusted:
        return
    config_path = descriptor.get("config_path")
    path_text = config_path if isinstance(config_path, str) and config_path else None
    if path_text:
        detail = (
            f" (config {path_text}); run `sase config trust allow {path_text}` "
            "after review"
        )
    else:
        detail = "; run `sase config trust allow` after review"
    raise WorkflowExecutionError(
        f"Local workflow '{workflow.name}' step '{step_name}' skipped without "
        f"current trust{detail}"
    )


def _partition_by_shape(
    macros_data: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail-closed split when the shared classifier is unavailable."""
    prompt_only: dict[str, Any] = {}
    executable: dict[str, Any] = {}
    for name, value in macros_data.items():
        if workflow_mapping_from_macro_entry(value) is not None:
            executable[name] = value
        else:
            prompt_only[name] = value
    return prompt_only, executable


def _executable_names_from_projection(
    blocked_paths: tuple[str, ...],
    projection: Mapping[str, Any],
    macros_data: Mapping[str, Any],
) -> set[str]:
    """Return command-bearing macro names from one projection payload."""
    names: set[str] = set()
    if "macros" in blocked_paths:
        names.update(macros_data)
    for path in blocked_paths:
        if path.startswith("macros."):
            names.add(path[len("macros.") :].split(".", 1)[0])
        elif path.startswith("workflows."):
            names.add(path[len("workflows.") :].split(".", 1)[0])
    projected = projection.get("macros")
    if isinstance(projected, dict):
        names.update(str(key) for key in projected)
    projected_workflows = projection.get("workflows")
    if isinstance(projected_workflows, dict):
        names.update(str(key) for key in projected_workflows)
    return names


def _is_filesystem_definition(item: Any) -> bool:
    """Return whether *item* comes from a filesystem macro/workflow source."""
    rank = getattr(item, "discovery_rank", None)
    if isinstance(rank, int) and rank >= RANK_FILESYSTEM_BASE:
        return True
    source_path = getattr(item, "source_path", None)
    if not isinstance(source_path, str) or not source_path:
        return False
    if source_path in {"config", "default_config", "local_config"}:
        return False
    return not source_path.startswith(
        ("config_overlay:", "plugin_config:", "project_local_config:")
    )


def _blocking_evaluation_for_name(
    name: str,
    *,
    project: str | None,
) -> Any | None:
    """Return the untrusted evaluation that blocks *name*, if any."""
    namespace, bare = _split_macro_namespace(name)
    for local_path, ns in _candidate_local_paths(namespace, project):
        evaluation, blocked = _blocked_names_for_path(local_path)
        if evaluation is None or not blocked:
            continue
        if name in blocked or bare in blocked:
            return evaluation
        if ns is not None and f"{ns}/{bare}" in blocked:
            return evaluation
    return None


def _split_macro_namespace(name: str) -> tuple[str | None, str]:
    """Return ``(namespace, bare_name)`` for a possibly namespaced macro."""
    if "/" not in name:
        return None, name
    namespace, bare = name.split("/", 1)
    if not namespace or not bare:
        return None, name
    return namespace, bare


def _candidate_local_paths(
    namespace: str | None,
    project: str | None,
) -> list[tuple[Path, str | None]]:
    """Return local config paths that could own a blocked executable name."""
    seen: set[str] = set()
    results: list[tuple[Path, str | None]] = []

    def _add(path: Path | None, ns: str | None) -> None:
        if path is None:
            return
        key = str(path)
        if key in seen:
            return
        seen.add(key)
        results.append((path, ns))

    try:
        from sase.config.core import get_local_config_path

        _add(get_local_config_path(), project)
    except Exception:
        pass
    for candidate in (namespace, project):
        if not candidate:
            continue
        _add(_project_local_config_path(candidate), candidate)
    return results


def _project_local_config_path(project: str) -> Path | None:
    """Return the selected config path for one registered project's workspace."""
    try:
        from sase.content_layout import resolve_project_config_read_path
        from sase.macro.project_identity import known_project_namespaces

        workspace = known_project_namespaces().get(project)
        if workspace is None:
            return None
        return resolve_project_config_read_path(
            workspace,
            label=f"project config for {project}",
        )
    except Exception:
        return None


def _blocked_names_for_path(local_path: Path) -> tuple[Any | None, frozenset[str]]:
    """Return the evaluation and blocked executable names for one local file."""
    try:
        from sase.config.local_trust_enforcement import evaluate_local_trust_for_path

        evaluation = evaluate_local_trust_for_path(local_path, None)
    except Exception:
        return None, frozenset()
    if not evaluation.enabled or evaluation.trusted:
        return evaluation, frozenset()
    names = _names_from_removed_paths(evaluation.removed_paths)
    if "macros" in evaluation.removed_paths or "workflows" in evaluation.removed_paths:
        names.update(_raw_local_macro_names(local_path))
    return evaluation, frozenset(names)


def _names_from_removed_paths(removed_paths: tuple[str, ...]) -> set[str]:
    """Extract macro/workflow names from command-bearing removed paths."""
    names: set[str] = set()
    for path in removed_paths:
        if path.startswith("macros."):
            names.add(path[len("macros.") :].split(".", 1)[0])
        elif path.startswith("workflows."):
            names.add(path[len("workflows.") :].split(".", 1)[0])
    return names


def _raw_local_macro_names(local_path: Path) -> set[str]:
    """Return authored local macro keys when the whole section is blocked."""
    try:
        from sase._yaml_safe import yaml_safe_load

        raw = yaml_safe_load(local_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(raw, dict):
        return set()
    macros: dict[str, Any]
    try:
        from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

        normalized = normalize_frontmatter_macros(raw, source="local_config")
        macros = dict(normalized) if isinstance(normalized, dict) else {}
    except Exception:
        fallback = raw.get("macros")
        macros = dict(fallback) if isinstance(fallback, dict) else {}
    names = {str(key) for key in macros}
    workflows = raw.get("workflows")
    if isinstance(workflows, dict):
        names.update(str(key) for key in workflows)
    return names


__all__ = [
    "LocalMacroTrustError",
    "assert_workflow_local_trust",
    "attach_local_trust",
    "blocked_local_macro_message",
    "partition_config_macros",
    "workflow_mapping_from_macro_entry",
]
