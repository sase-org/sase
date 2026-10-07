"""Output-variable storage for SASE agent runs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_meta_update import update_agent_meta_locked
from sase.core.artifact_file_helpers import read_json_object
from sase.core.output_variable_values import (
    MAX_OUTPUT_VARIABLES,
    MAX_OUTPUT_VARIABLE_VALUE_BYTES,
    VarValue,
    coerce_var_map,
    normalize_var_value,
)

_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OUTPUT_VARIABLES_FIELD = "output_variables"


def parse_output_variable_assignments(assignments: list[str]) -> dict[str, str]:
    """Parse ``KEY=VALUE`` output-variable assignments."""
    variables: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(
                "output variable assignment must be KEY=VALUE: "
                f"{assignment}. Quote the whole assignment, or use "
                "`sase var set KEY --value TEXT` for a value with spaces or newlines"
            )
        key, value = assignment.split("=", 1)
        _validate_output_variable_key(key)
        normalized = normalize_var_value(key, value)
        assert isinstance(normalized, str)
        variables[key] = normalized
    return variables


def read_agent_output_variables(artifacts_dir: Path | str) -> dict[str, VarValue]:
    """Read structured output variables from an agent artifact directory."""
    artifacts_path = Path(artifacts_dir).expanduser()
    meta = read_json_object(artifacts_path / "agent_meta.json")
    return coerce_var_map(meta.get(_OUTPUT_VARIABLES_FIELD))


def set_agent_output_variables(
    artifacts_dir: Path | str,
    variables: Mapping[str, VarValue],
) -> dict[str, VarValue]:
    """Merge output variables into ``agent_meta.json`` and return the stored map."""
    normalized: dict[str, VarValue] = {}
    for key, value in variables.items():
        _validate_output_variable_key(key)
        normalized[key] = normalize_var_value(key, value)

    def _merge(meta: dict[str, Any]) -> dict[str, VarValue]:
        merged = {**coerce_var_map(meta.get(_OUTPUT_VARIABLES_FIELD))}
        merged.update(normalized)
        if len(merged) > MAX_OUTPUT_VARIABLES:
            raise ValueError(
                f"output variables contain {len(merged)} entries; "
                f"limit is {MAX_OUTPUT_VARIABLES}"
            )
        meta[_OUTPUT_VARIABLES_FIELD] = merged
        return merged

    return update_agent_meta_locked(artifacts_dir, _merge)


def _validate_output_variable_key(key: str) -> None:
    if not isinstance(key, str):
        raise ValueError("output variable key must be a string")
    if not key:
        raise ValueError("output variable key must not be empty")
    if _KEY_RE.fullmatch(key) is None:
        raise ValueError(
            "output variable key must be a valid Jinja attribute identifier "
            f"([A-Za-z_][A-Za-z0-9_]*): {key}"
        )


__all__ = [
    "MAX_OUTPUT_VARIABLES",
    "MAX_OUTPUT_VARIABLE_VALUE_BYTES",
    "parse_output_variable_assignments",
    "read_agent_output_variables",
    "set_agent_output_variables",
]
