"""Agent OUTPUT VARIABLES rendering for the prompt panel header."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from rich.text import Text

from sase.ace.tui.agent_context_members import compact_role_label
from sase.ace.tui.tools.cache import get_cache_key
from sase.core.output_variable_values import VarValue

from ...models.agent import Agent
from ...models.fold_state import FoldLevel
from ._agent_context_common import (
    COLOR_ROLE,
    COLOR_SUMMARY,
    ROLE_COLUMN_WIDTH,
    count_phrase,
    format_role_column,
)
from ._helpers import append_major_section_divider, append_section_heading
from ._output_variable_rich import append_var_value_lines

_COLOR_HEADER = "bold #D7AF5F underline"


@dataclass(frozen=True)
class _OutputVariableContributor:
    label: str
    output_variables: Mapping[str, VarValue]


def append_agent_output_variables_section(
    text: Text,
    agent: Agent,
    *,
    fold_level: FoldLevel | None = None,
) -> None:
    """Append output variables for the selected agent family."""
    contributors = _output_variable_contributors(agent)
    if not contributors:
        return

    append_major_section_divider(text)
    if fold_level is not None:
        from ._agent_display_family import append_family_fold_heading

        variable_count = sum(
            len(contributor.output_variables) for contributor in contributors
        )
        append_family_fold_heading(
            text,
            "OUTPUT VARIABLES",
            section_id="output-variables",
            level=fold_level,
            count=variable_count,
            style=_COLOR_HEADER,
        )
        if fold_level == FoldLevel.COLLAPSED:
            return
    else:
        heading = Text("OUTPUT VARIABLES", style=_COLOR_HEADER)
        if len(contributors) > 1:
            heading.append(
                f" \u00b7 {count_phrase(len(contributors), 'agent')}",
                style=COLOR_SUMMARY,
            )
        append_section_heading(text, heading, section_id="output-variables")

    if len(contributors) == 1:
        _append_flat_variables(text, contributors[0].output_variables)
        return

    for contributor in contributors:
        _append_attributed_variables(
            text,
            role_label=contributor.label,
            output_variables=contributor.output_variables,
        )


def _output_variable_contributors(agent: Agent) -> list[_OutputVariableContributor]:
    contributors: list[_OutputVariableContributor] = []
    seen_keys: set[str] = set()
    seen_dirs: set[str] = set()

    for member_agent in (agent, *agent.followup_agents):
        if not member_agent.output_variables:
            continue

        cache_key = get_cache_key(member_agent)
        if cache_key in seen_keys:
            continue

        artifacts_dir = _normalize_loaded_artifacts_dir(member_agent.artifacts_dir)
        if artifacts_dir is not None and artifacts_dir in seen_dirs:
            continue

        seen_keys.add(cache_key)
        if artifacts_dir is not None:
            seen_dirs.add(artifacts_dir)
        contributors.append(
            _OutputVariableContributor(
                label=compact_role_label(member_agent),
                output_variables=member_agent.output_variables,
            )
        )

    return contributors


def _normalize_loaded_artifacts_dir(value: str | None) -> str | None:
    """Normalize an already-loaded artifacts path without probing the disk."""
    if not value:
        return None
    try:
        return os.path.normcase(os.path.abspath(os.path.expanduser(value)))
    except (OSError, ValueError):
        return value


def _append_flat_variables(
    text: Text,
    output_variables: Mapping[str, VarValue],
) -> None:
    for key in sorted(output_variables):
        append_var_value_lines(text, output_variables[key], key=key)


def _append_attributed_variables(
    text: Text,
    *,
    role_label: str,
    output_variables: Mapping[str, VarValue],
) -> None:
    continuation_prefix = " " * ROLE_COLUMN_WIDTH
    for key in sorted(output_variables):
        append_var_value_lines(
            text,
            output_variables[key],
            key=key,
            first_prefix=Text(format_role_column(role_label), style=COLOR_ROLE),
            continuation_prefix=continuation_prefix,
        )
