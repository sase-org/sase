"""Handler for the ``sase var`` CLI subcommand."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
import sys
from pathlib import Path
from typing import NoReturn

from sase.core.agent_output_variable_history_wire import (
    AgentOutputVariableHistoryQueryWire,
)
from sase.core.agent_output_variable_selector_wire import (
    DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT,
    AgentOutputVariableSelectorQueryWire,
    OutputVariableSelectorWire,
)
from sase.core.agent_output_variables import (
    parse_output_variable_assignments,
    read_agent_output_variables,
    set_agent_output_variables,
)
from sase.core.agent_scan_facade import (
    query_agent_output_variable_history,
    query_agent_output_variable_selectors,
)
from sase.core.output_variable_values import VarValue, normalize_var_value
from sase.main.parser_var import WrappedAgentTarget
from sase.main.var_cli import (
    artifact_timestamp_from_date,
    display_project_name,
    prepare_output_variable_index,
    resolve_current_var_agent_name,
    resolve_named_var_artifact,
    resolve_var_projects,
)
from sase.main.var_render import (
    render_var_get,
    render_var_history,
    render_var_snapshot,
)
from sase.project_display_names import ProjectRefDisplaySnapshot


def handle_var_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch ``sase var`` subcommands."""
    subcommand = getattr(args, "var_subcommand", None)
    if subcommand == "get":
        _handle_var_get(args)
    if subcommand == "list":
        _handle_var_list(args)
    if subcommand == "set":
        _handle_var_set(args)

    print("Usage: sase var {get,list,set}", file=sys.stderr)
    sys.exit(1)


def _handle_var_get(args: argparse.Namespace) -> NoReturn:
    """Read a snapshot or retrieve output-variable values by selector."""
    targets = list(getattr(args, "targets", None) or [])
    wrapped = [target for target in targets if isinstance(target, WrappedAgentTarget)]
    selectors = [
        target for target in targets if isinstance(target, OutputVariableSelectorWire)
    ]
    if wrapped and selectors:
        print(
            "Error: cannot mix a wrapped <agent_name> with selectors; "
            "use sase var get '<build>' for a snapshot or a selector such as "
            "build.*",
            file=sys.stderr,
        )
        sys.exit(2)
    if len(wrapped) > 1:
        print(
            "Error: only one wrapped <agent_name> is allowed; "
            "use sase var get '<build>' for a single snapshot",
            file=sys.stderr,
        )
        sys.exit(2)
    if not targets:
        _validate_snapshot_options(args)
        _render_snapshot_from_dir(
            _require_get_artifacts_dir(),
            output_format=str(getattr(args, "format", "pretty") or "pretty"),
            color=str(getattr(args, "color", "auto") or "auto"),
        )
    if wrapped:
        _validate_snapshot_options(args)
        _handle_named_snapshot(args, wrapped[0].agent_name)
    _handle_selector_get(args, selectors)


def _handle_named_snapshot(args: argparse.Namespace, agent_name: str) -> NoReturn:
    """Render the newest exact-name historical snapshot."""
    project_refs = list(getattr(args, "projects", None) or [])
    record = resolve_named_var_artifact(
        agent_name,
        projects=project_refs,
        include_hidden=bool(getattr(args, "hidden", False)),
    )
    if record is None:
        print(
            f"Error: unknown agent: {agent_name}{_project_error_suffix(project_refs)}",
            file=sys.stderr,
        )
        sys.exit(1)
    _render_snapshot_from_dir(
        record.artifact_dir,
        output_format=str(getattr(args, "format", "pretty") or "pretty"),
        color=str(getattr(args, "color", "auto") or "auto"),
    )


def _handle_selector_get(
    args: argparse.Namespace,
    selectors: list[OutputVariableSelectorWire],
) -> NoReturn:
    """Retrieve output-variable values by selector."""
    output_format = str(getattr(args, "format", "pretty") or "pretty")
    color = str(getattr(args, "color", "auto") or "auto")
    display: ProjectRefDisplaySnapshot | None = None
    try:
        query, display = _selector_query_from_args(args, selectors)
        index, _root = prepare_output_variable_index()
        result = query_agent_output_variable_selectors(index, query)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as exc:
        _print_selector_query_error(str(exc), display)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: failed to get output variables: {exc}", file=sys.stderr)
        sys.exit(1)

    if output_format == "raw" and (
        len(result.matches) != 1 or result.matches_limit.truncated
    ):
        print(
            "Error: raw format requires exactly one resolved value",
            file=sys.stderr,
        )
        sys.exit(1)

    assert display is not None
    render_var_get(
        result,
        output_format=output_format,
        color=color,
        display=display,
    )
    sys.exit(0)


def _validate_snapshot_options(args: argparse.Namespace) -> None:
    """Reject selector-only options on snapshot invocations."""
    output_format = str(getattr(args, "format", "pretty") or "pretty")
    if output_format in {"raw", "jsonl"}:
        print(
            f"Error: --format {output_format} is only valid with a selector; "
            "use pretty or json for a snapshot, or pass a selector such as "
            "build.*",
            file=sys.stderr,
        )
        sys.exit(2)
    if bool(getattr(args, "limit_explicit", False)):
        print(
            "Error: --limit applies only to selector wildcard expansion; "
            "omit --limit for a snapshot, or pass a selector such as build.*",
            file=sys.stderr,
        )
        sys.exit(2)


def _render_snapshot_from_dir(
    artifact_dir: str | Path,
    *,
    output_format: str,
    color: str,
) -> NoReturn:
    """Read and render one artifact directory's stored variable map."""
    try:
        variables = read_agent_output_variables(artifact_dir)
    except Exception as exc:
        print(f"Error: failed to get output variables: {exc}", file=sys.stderr)
        sys.exit(1)
    render_var_snapshot(variables, output_format=output_format, color=color)
    sys.exit(0)


def _project_error_suffix(project_refs: list[str]) -> str:
    if not project_refs:
        return ""
    if len(project_refs) == 1:
        return f" (project {project_refs[0]})"
    return f" (projects {', '.join(project_refs)})"


def _selector_query_from_args(
    args: argparse.Namespace,
    selectors: list[OutputVariableSelectorWire],
) -> tuple[AgentOutputVariableSelectorQueryWire, ProjectRefDisplaySnapshot]:
    project_keys, display = resolve_var_projects(getattr(args, "projects", None))
    return (
        AgentOutputVariableSelectorQueryWire(
            selectors=_selectors_from_args(selectors),
            projects=project_keys,
            include_hidden=bool(getattr(args, "hidden", False)),
            limit=int(getattr(args, "limit", DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT)),
        ),
        display,
    )


def _selectors_from_args(
    selectors: Sequence[object],
) -> list[OutputVariableSelectorWire]:
    parsed: list[OutputVariableSelectorWire] = []
    for selector in selectors:
        if not isinstance(selector, OutputVariableSelectorWire):
            raise ValueError(
                "selectors must be parsed OutputVariableSelectorWire values"
            )
        parsed.append(selector)
    return parsed


def _print_selector_query_error(
    raw: str,
    display: ProjectRefDisplaySnapshot | None,
) -> None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(f"Error: {raw}", file=sys.stderr)
        return
    if not isinstance(payload, dict):
        print(f"Error: {raw}", file=sys.stderr)
        return
    kind = payload.get("kind")
    selector = payload.get("selector")
    if kind == "no_match":
        print(f"Error: no match for selector {selector!r}", file=sys.stderr)
        return
    if kind == "ambiguous_project":
        projects = [
            display_project_name(str(name), display)
            if display is not None
            else str(name)
            for name in payload.get("projects") or []
        ]
        print(
            f"Error: selector {selector!r} matches agent "
            f"{payload.get('agent')!r} in multiple projects "
            f"({', '.join(projects)}); pass --project to disambiguate",
            file=sys.stderr,
        )
        return
    if kind == "path_type":
        print(
            f"Error: selector {selector!r} path {payload.get('path')} "
            f"expected {payload.get('expected')}, found {payload.get('actual')}",
            file=sys.stderr,
        )
        return
    if kind == "path_missing":
        print(
            f"Error: selector {selector!r} path {payload.get('path')} "
            f"is missing key {payload.get('key')}",
            file=sys.stderr,
        )
        return
    if kind == "path_range":
        print(
            f"Error: selector {selector!r} path {payload.get('path')} "
            f"index {payload.get('index')} is out of range "
            f"(length {payload.get('len')})",
            file=sys.stderr,
        )
        return
    if kind == "index":
        print(f"Error: {payload.get('message')}", file=sys.stderr)
        return
    print(f"Error: {raw}", file=sys.stderr)


def _handle_var_list(args: argparse.Namespace) -> NoReturn:
    """Display grouped historical output variables."""
    try:
        query, display = _history_query_from_args(args)
        index, _root = prepare_output_variable_index()
        history = query_agent_output_variable_history(index, query)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: failed to list output variables: {exc}", file=sys.stderr)
        sys.exit(1)

    render_var_history(
        history,
        output_format=str(getattr(args, "format", "pretty") or "pretty"),
        color=str(getattr(args, "color", "auto") or "auto"),
        display=display,
    )
    sys.exit(0)


def _history_query_from_args(
    args: argparse.Namespace,
) -> tuple[AgentOutputVariableHistoryQueryWire, ProjectRefDisplaySnapshot]:
    project_keys, display = resolve_var_projects(getattr(args, "projects", None))
    key_limit, value_limit = getattr(args, "limit", (20, 5))
    since = getattr(args, "since", None)
    until = getattr(args, "until", None)
    return (
        AgentOutputVariableHistoryQueryWire(
            projects=project_keys,
            agents=list(getattr(args, "agents", None) or []),
            keys=list(getattr(args, "keys", None) or []),
            values=list(getattr(args, "values", None) or []),
            value_json=list(getattr(args, "value_json", None) or []),
            since_timestamp=(
                artifact_timestamp_from_date(since, boundary="since") if since else None
            ),
            until_timestamp=(
                artifact_timestamp_from_date(until, boundary="until") if until else None
            ),
            include_hidden=bool(getattr(args, "hidden", False)),
            key_limit=int(key_limit),
            value_limit=int(value_limit),
            reverse=bool(getattr(args, "reverse", False)),
        ),
        display,
    )


def _handle_var_set(args: argparse.Namespace) -> NoReturn:
    """Persist output variables for the current SASE agent."""
    agent_artifacts_dir = _require_agent_artifacts_dir("set")

    try:
        variables = _output_variables_from_args(args)
        stored = set_agent_output_variables(agent_artifacts_dir, variables)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: failed to set output variables: {exc}", file=sys.stderr)
        sys.exit(1)

    agent_name = _current_agent_name(agent_artifacts_dir)
    if agent_name:
        print(f"agent: {agent_name}")
    print(f"keys: {', '.join(sorted(stored))}")
    print(f"artifacts_dir: {Path(agent_artifacts_dir).expanduser()}")
    sys.exit(0)


def _require_get_artifacts_dir() -> str:
    """Return the current artifact directory for no-target ``get``."""
    agent_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not agent_artifacts_dir:
        print(
            "Error: sase var get requires SASE_ARTIFACTS_DIR or a quoted <agent_name>",
            file=sys.stderr,
        )
        sys.exit(1)
    return agent_artifacts_dir


def _require_agent_artifacts_dir(subcommand: str) -> str:
    """Return this agent's artifact directory or exit with a clear error."""
    if os.environ.get("SASE_AGENT") != "1":
        print(
            f"Error: sase var {subcommand} must be run from inside a SASE agent "
            "(SASE_AGENT=1 is required)",
            file=sys.stderr,
        )
        sys.exit(1)

    agent_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not agent_artifacts_dir:
        print(
            f"Error: sase var {subcommand} requires SASE_ARTIFACTS_DIR",
            file=sys.stderr,
        )
        sys.exit(1)
    return agent_artifacts_dir


def _output_variables_from_args(args: argparse.Namespace) -> dict[str, VarValue]:
    parse_json = bool(getattr(args, "json", False))
    value = getattr(args, "value", None)
    value_file = getattr(args, "value_file", None)
    if value is None and value_file is None:
        if not parse_json:
            text_variables = parse_output_variable_assignments(args.assignments)
            variables: dict[str, VarValue] = {}
            variables.update(text_variables)
            return variables
        parsed = _split_json_assignments(args.assignments)
        return {
            key: _decode_json_value(raw_value, key=key, source="KEY=VALUE")
            for key, raw_value in parsed.items()
        }

    if len(args.assignments) != 1 or "=" in args.assignments[0]:
        raise ValueError(
            "the value-source form requires exactly one bare KEY (without '='): "
            "`sase var set KEY --value TEXT` sets exactly one variable"
        )

    key = args.assignments[0]
    if value_file is None:
        if not isinstance(value, str):
            raise ValueError("output variable --value must be a string")
        if parse_json:
            return {key: _decode_json_value(value, key=key, source="--value")}
        return {key: normalize_var_value(key, value)}
    if not isinstance(value_file, str):
        raise ValueError("output variable --value-file must be a path")

    raw_value = _read_output_variable_value(value_file)
    if parse_json:
        return {
            key: _decode_json_value(
                raw_value,
                key=key,
                source=f"--value-file {value_file}",
            )
        }
    normalized = parse_output_variable_assignments([f"{key}={raw_value}"])[key]
    if normalized.endswith("\n"):
        normalized = normalized[:-1]
    return {key: normalized}


def _split_json_assignments(assignments: list[str]) -> dict[str, str]:
    """Split JSON assignments without applying the per-string-leaf cap."""
    result: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            # Reuse the established assignment error and key guidance.
            parse_output_variable_assignments([assignment])
            raise AssertionError("unreachable")
        key, raw_value = assignment.split("=", 1)
        # Validate the top-level variable name through the canonical parser,
        # while leaving the JSON document intact for its structural limits.
        parse_output_variable_assignments([f"{key}="])
        result[key] = raw_value
    return result


def _decode_json_value(raw_value: str, *, key: str, source: str) -> VarValue:
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON for output variable {key} from {source}: "
            f"{exc.msg} at line {exc.lineno} column {exc.colno}"
        ) from exc
    return normalize_var_value(key, value)


def _read_output_variable_value(source: str) -> str:
    if source == "-":
        try:
            return sys.stdin.read()
        except UnicodeDecodeError as exc:
            raise ValueError(
                "output variable value from stdin is not valid UTF-8"
            ) from exc
        except OSError as exc:
            raise ValueError(
                f"could not read output variable value from stdin: {exc}"
            ) from exc

    value_path = Path(source).expanduser()
    try:
        return value_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"output variable value file not found: {value_path}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"output variable value file is not valid UTF-8: {value_path}"
        ) from exc
    except OSError as exc:
        raise ValueError(
            f"could not read output variable value file {value_path}: {exc}"
        ) from exc


def _current_agent_name(artifacts_dir: str) -> str | None:
    return resolve_current_var_agent_name(artifacts_dir)
