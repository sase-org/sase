"""Pretty, JSON, and JSONL renderers for ``sase var show`` and ``sase var list``."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import TextIO

from rich.console import Console
from rich.text import Text

from sase.bead.cli_dep_render import resolve_color
from sase.core.agent_output_variable_history_wire import (
    AgentOutputVariableHistoryQueryWire,
    AgentOutputVariableHistoryWire,
    AgentOutputVariableKeyGroupWire,
    AgentOutputVariableLimitWire,
    AgentOutputVariableOccurrenceWire,
    AgentOutputVariableValueGroupWire,
)
from sase.core.agent_output_variable_selector_wire import (
    AgentOutputVariableSelectorMatchWire,
    AgentOutputVariableSelectorQueryWire,
    AgentOutputVariableSelectorResultWire,
    OutputVariableSelectorPathWire,
    output_variable_selector_to_dict,
)
from sase.core.output_variable_display import VarLine, format_var_value_lines
from sase.core.output_variable_values import VarValue
from sase.main.var_cli import display_project_name
from sase.project_display_names import ProjectRefDisplaySnapshot

_KEY_STYLE = "bold #87D7FF"
_VALUE_STYLES = {
    "string": "#5FD75F",
    "number": "#FFAF5F",
    "boolean": "italic #AFAFAF",
    "null": "italic #AFAFAF",
    "list": "dim",
    "map": "dim",
    "block": "dim",
}
_COUNT_STYLE = "dim"
_AGENT_STYLE = "#D7AFFF"
_TRUNCATION_STYLE = "italic #AFAFAF"
_EMPTY_SHOW_MESSAGE = "No output variables set."
_EMPTY_LIST_MESSAGE = "No matching output variables."
_UNNAMED_AGENT = "(unnamed)"


def _var_console(color: str, *, file: TextIO | None = None) -> Console:
    """Build a Rich console honoring ``-c/--color``."""
    use_color = resolve_color(color)
    kwargs: dict[str, object] = {"file": file or sys.stdout, "highlight": False}
    if color == "always":
        kwargs.update(force_terminal=True, no_color=False, color_system="standard")
    elif color == "never" or not use_color:
        kwargs.update(no_color=True, color_system=None, force_terminal=False)
    return Console(**kwargs)  # type: ignore[arg-type]


def render_var_snapshot(
    variables: Mapping[str, VarValue],
    *,
    output_format: str,
    color: str,
) -> None:
    """Render one agent's stored variable map."""
    if output_format == "json":
        print(_compact_json(dict(variables)))
        return
    console = _var_console(color)
    use_color = resolve_color(color)
    if not variables:
        console.print(Text(_EMPTY_SHOW_MESSAGE, style=_style("dim", use_color)))
        return
    lines, _truncated = format_var_value_lines(dict(variables))
    for line in lines:
        console.print(_styled_var_line(line, use_color=use_color))


def render_var_get(
    result: AgentOutputVariableSelectorResultWire,
    *,
    output_format: str,
    color: str,
    display: ProjectRefDisplaySnapshot,
) -> None:
    """Render selector matches for ``sase var get``."""
    if output_format == "raw":
        _render_get_raw(result)
        return
    if output_format == "json":
        print(_compact_json(_get_envelope(result, display=display)))
        return
    if output_format == "jsonl":
        _render_get_jsonl(result, display=display)
        return
    _render_get_pretty(result, color=color, display=display)


def render_var_history(
    history: AgentOutputVariableHistoryWire,
    *,
    output_format: str,
    color: str,
    display: ProjectRefDisplaySnapshot,
) -> None:
    """Render grouped historical output variables."""
    if output_format == "json":
        print(_compact_json(_history_envelope(history, display=display)))
        return
    if output_format == "jsonl":
        _render_history_jsonl(history, display=display)
        return
    _render_history_pretty(history, color=color, display=display)


def _render_get_raw(result: AgentOutputVariableSelectorResultWire) -> None:
    match = result.matches[0]
    if isinstance(match.value, str):
        print(match.value)
        return
    print(match.value_json)


def _get_envelope(
    result: AgentOutputVariableSelectorResultWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "index_path": result.index_path,
        "query": _selector_query_payload(result.query, display=display),
        "limits": {
            "matches": _limit_payload(
                result.matches_limit,
                requested=result.query.limit,
            )
        },
        "matches": [
            _selector_match_payload(match, display=display) for match in result.matches
        ],
    }


def _render_get_jsonl(
    result: AgentOutputVariableSelectorResultWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> None:
    for match in result.matches:
        print(
            _compact_json(
                {
                    "schema_version": result.schema_version,
                    "matches_limit": _limit_payload(
                        result.matches_limit,
                        requested=result.query.limit,
                    ),
                    **_selector_match_payload(match, display=display),
                }
            )
        )


def _render_get_pretty(
    result: AgentOutputVariableSelectorResultWire,
    *,
    color: str,
    display: ProjectRefDisplaySnapshot,
) -> None:
    console = _var_console(color)
    use_color = resolve_color(color)
    for index, match in enumerate(result.matches):
        if index:
            console.print()
        _print_selector_match(console, match, display=display, use_color=use_color)
    if result.matches_limit.truncated:
        hidden = result.matches_limit.total_count - result.matches_limit.returned_count
        console.print(
            Text(
                _more_label(hidden, "match", "matches", result.matches_limit.limit),
                style=_style(_TRUNCATION_STYLE, use_color),
            )
        )


def _print_selector_match(
    console: Console,
    match: AgentOutputVariableSelectorMatchWire,
    *,
    display: ProjectRefDisplaySnapshot,
    use_color: bool,
) -> None:
    lines, _truncated = format_var_value_lines(match.value)
    if lines:
        first = _styled_var_line(lines[0], use_color=use_color)
        console.print(first)
        for line in lines[1:]:
            console.print(_styled_var_line(line, use_color=use_color))
    attribution = Text("  ")
    agent = match.agent_name or _UNNAMED_AGENT
    attribution.append(agent, style=_style(_AGENT_STYLE, use_color))
    attribution.append(" · ", style=_style(_COUNT_STYLE, use_color))
    attribution.append(
        display_project_name(match.project_name, display),
        style=_style(_COUNT_STYLE, use_color),
    )
    attribution.append(" · ", style=_style(_COUNT_STYLE, use_color))
    attribution.append(match.timestamp, style=_style(_COUNT_STYLE, use_color))
    attribution.append(" · ", style=_style(_COUNT_STYLE, use_color))
    attribution.append(
        match.key + _format_selector_path(match.path),
        style=_style(_KEY_STYLE, use_color),
    )
    console.print(attribution)


def _format_selector_path(path: list[OutputVariableSelectorPathWire]) -> str:
    """Render JSON-path steps as ``[0]["key"]``."""
    rendered: list[str] = []
    for step in path:
        if step.kind == "index" and step.index is not None:
            rendered.append(f"[{step.index}]")
        elif step.kind == "key" and step.key is not None:
            rendered.append(f"[{json.dumps(step.key, ensure_ascii=False)}]")
    return "".join(rendered)


def _selector_query_payload(
    query: AgentOutputVariableSelectorQueryWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    return {
        "selectors": [
            output_variable_selector_to_dict(selector) for selector in query.selectors
        ],
        "projects": [display_project_name(name, display) for name in query.projects],
        "include_hidden": query.include_hidden,
        "limit": query.limit,
    }


def _selector_match_payload(
    match: AgentOutputVariableSelectorMatchWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    return {
        "selector": match.selector,
        "key": match.key,
        "path": [
            {
                "kind": step.kind,
                **({"index": step.index} if step.index is not None else {}),
                **({"key": step.key} if step.key is not None else {}),
            }
            for step in match.path
        ],
        "value": match.value,
        "value_json": match.value_json,
        "artifact_dir": match.artifact_dir,
        "project_name": display_project_name(match.project_name, display),
        "workflow_dir_name": match.workflow_dir_name,
        "timestamp": match.timestamp,
        "agent_name": match.agent_name,
        "cl_name": match.cl_name,
        "hidden": match.hidden,
    }


def _history_envelope(
    history: AgentOutputVariableHistoryWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    """Return the stable versioned JSON envelope for one history result."""
    return {
        "schema_version": history.schema_version,
        "index_path": history.index_path,
        "query": _query_payload(history.query, display=display),
        "limits": {
            "keys": _limit_payload(
                history.keys_limit,
                requested=history.query.key_limit,
            ),
            "values": {
                "requested": history.query.value_limit,
                "effective": history.query.value_limit,
            },
        },
        "groups": [
            _key_group_payload(group, display=display) for group in history.groups
        ],
    }


def _render_history_jsonl(
    history: AgentOutputVariableHistoryWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> None:
    for group in history.groups:
        for value in group.values:
            print(
                _compact_json(
                    {
                        "schema_version": history.schema_version,
                        "key": group.key,
                        "key_occurrence_count": group.occurrence_count,
                        "key_distinct_value_count": group.distinct_value_count,
                        "values_limit": _limit_payload(
                            group.values_limit,
                            requested=history.query.value_limit,
                        ),
                        **_value_group_payload(value, display=display),
                    }
                )
            )


def _render_history_pretty(
    history: AgentOutputVariableHistoryWire,
    *,
    color: str,
    display: ProjectRefDisplaySnapshot,
) -> None:
    console = _var_console(color)
    use_color = resolve_color(color)
    if not history.groups:
        console.print(Text(_EMPTY_LIST_MESSAGE, style=_style("dim", use_color)))
        return
    for index, group in enumerate(history.groups):
        if index:
            console.print()
        _print_key_group(console, group, display=display, use_color=use_color)
    keys_limit = history.keys_limit
    if keys_limit.truncated:
        hidden = keys_limit.total_count - keys_limit.returned_count
        console.print(
            Text(
                _more_label(hidden, "key", "keys", keys_limit.limit),
                style=_style(_TRUNCATION_STYLE, use_color),
            )
        )


def _print_key_group(
    console: Console,
    group: AgentOutputVariableKeyGroupWire,
    *,
    display: ProjectRefDisplaySnapshot,
    use_color: bool,
) -> None:
    header = Text()
    header.append(group.key, style=_style(_KEY_STYLE, use_color))
    console.print(header)
    console.print(
        Text(
            "  "
            + " · ".join(
                (
                    _count_label(group.occurrence_count, "occurrence", "occurrences"),
                    _count_label(group.distinct_value_count, "value", "values"),
                )
            ),
            style=_style(_COUNT_STYLE, use_color),
        )
    )
    for value in group.values:
        _print_value_group(console, value, display=display, use_color=use_color)
    if group.values_limit.truncated:
        hidden = group.values_limit.total_count - group.values_limit.returned_count
        console.print(
            Text(
                "  " + _more_label(hidden, "value", "values", group.values_limit.limit),
                style=_style(_TRUNCATION_STYLE, use_color),
            )
        )


def _print_value_group(
    console: Console,
    group: AgentOutputVariableValueGroupWire,
    *,
    display: ProjectRefDisplaySnapshot,
    use_color: bool,
) -> None:
    lines, _truncated = format_var_value_lines(group.value)
    if lines:
        first = _styled_var_line(lines[0], use_color=use_color)
        first.pad_left(2)
        console.print(first)
        for line in lines[1:]:
            rendered = _styled_var_line(line, use_color=use_color)
            rendered.pad_left(2)
            console.print(rendered)
    attribution = Text("    ")
    attribution.append(
        f"×{group.occurrence_count}", style=_style(_COUNT_STYLE, use_color)
    )
    if group.agents:
        attribution.append(" · ", style=_style(_COUNT_STYLE, use_color))
        attribution.append(
            ", ".join(group.agents), style=_style(_AGENT_STYLE, use_color)
        )
    projects = [display_project_name(name, display) for name in group.projects]
    if projects:
        attribution.append(" · ", style=_style(_COUNT_STYLE, use_color))
        attribution.append(", ".join(projects), style=_style(_COUNT_STYLE, use_color))
    console.print(attribution)


def _styled_var_line(line: VarLine, *, use_color: bool) -> Text:
    rendered = Text("  " * line.indent)
    if line.bullet:
        rendered.append("-", style=_style("dim", use_color))
    if line.key is not None:
        if line.bullet:
            rendered.append(" ")
        rendered.append(f"{line.key}:", style=_style(_KEY_STYLE, use_color))
        if line.text is not None:
            rendered.append(" ")
    elif line.bullet and line.text is not None:
        rendered.append(" ")
    if line.text is not None:
        rendered.append(line.text, style=_style(_VALUE_STYLES[line.kind], use_color))
    return rendered


def _style(style: str, use_color: bool) -> str:
    return style if use_color else ""


def _query_payload(
    query: AgentOutputVariableHistoryQueryWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    return {
        "projects": [display_project_name(name, display) for name in query.projects],
        "agents": list(query.agents),
        "keys": list(query.keys),
        "values": list(query.values),
        "value_json": list(query.value_json),
        "since_timestamp": query.since_timestamp,
        "until_timestamp": query.until_timestamp,
        "include_hidden": query.include_hidden,
        "key_limit": query.key_limit,
        "value_limit": query.value_limit,
        "reverse": query.reverse,
    }


def _limit_payload(
    limit: AgentOutputVariableLimitWire,
    *,
    requested: int,
) -> dict[str, object]:
    return {
        "requested": requested,
        "effective": limit.limit,
        "total_count": limit.total_count,
        "returned_count": limit.returned_count,
        "truncated": limit.truncated,
    }


def _key_group_payload(
    group: AgentOutputVariableKeyGroupWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    return {
        "key": group.key,
        "occurrence_count": group.occurrence_count,
        "distinct_value_count": group.distinct_value_count,
        "values_limit": {
            "limit": group.values_limit.limit,
            "total_count": group.values_limit.total_count,
            "returned_count": group.values_limit.returned_count,
            "truncated": group.values_limit.truncated,
        },
        "values": [
            _value_group_payload(value, display=display) for value in group.values
        ],
    }


def _value_group_payload(
    group: AgentOutputVariableValueGroupWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    return {
        "value": group.value,
        "value_json": group.value_json,
        "occurrence_count": group.occurrence_count,
        "agent_count": group.agent_count,
        "agents": list(group.agents),
        "projects": [display_project_name(name, display) for name in group.projects],
        "first_seen_timestamp": group.first_seen_timestamp,
        "last_seen_timestamp": group.last_seen_timestamp,
        "newest": _occurrence_payload(group.newest, display=display),
    }


def _occurrence_payload(
    occurrence: AgentOutputVariableOccurrenceWire,
    *,
    display: ProjectRefDisplaySnapshot,
) -> dict[str, object]:
    return {
        "artifact_dir": occurrence.artifact_dir,
        "project_name": display_project_name(occurrence.project_name, display),
        "workflow_dir_name": occurrence.workflow_dir_name,
        "timestamp": occurrence.timestamp,
        "agent_name": occurrence.agent_name,
        "cl_name": occurrence.cl_name,
        "key": occurrence.key,
        "value": occurrence.value,
        "value_json": occurrence.value_json,
        "hidden": occurrence.hidden,
    }


def _compact_json(payload: object) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _count_label(count: int, singular: str, plural: str) -> str:
    label = singular if count == 1 else plural
    return f"{count} {label}"


def _more_label(hidden: int, singular: str, plural: str, limit: int) -> str:
    label = singular if hidden == 1 else plural
    if limit:
        return f"… {hidden} more {label} (limit {limit})"
    return f"… {hidden} more {label}"


__all__ = [
    "render_var_get",
    "render_var_history",
    "render_var_snapshot",
]
