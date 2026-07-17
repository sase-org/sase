"""Output-variable storage for SASE agent runs."""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sase.core.artifact_file_helpers import read_json_object
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OUTPUT_VARIABLES_FIELD = "output_variables"


def parse_output_variable_assignments(assignments: list[str]) -> dict[str, str]:
    """Parse ``KEY=VALUE`` output-variable assignments."""
    variables: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(
                f"output variable assignment must be KEY=VALUE: {assignment}"
            )
        key, value = assignment.split("=", 1)
        _validate_output_variable_key(key)
        variables[key] = value
    return variables


def read_agent_output_variables(artifacts_dir: Path | str) -> dict[str, str]:
    """Read string output variables from an agent artifact directory."""
    artifacts_path = Path(artifacts_dir).expanduser()
    meta = read_json_object(artifacts_path / "agent_meta.json")
    return _string_output_variables(meta.get(_OUTPUT_VARIABLES_FIELD))


def set_agent_output_variables(
    artifacts_dir: Path | str,
    variables: Mapping[str, str],
) -> dict[str, str]:
    """Merge output variables into ``agent_meta.json`` and return the stored map."""
    artifacts_path = Path(artifacts_dir).expanduser()
    if not artifacts_path.is_dir():
        raise ValueError(f"agent artifacts directory not found: {artifacts_path}")
    for key, value in variables.items():
        _validate_output_variable_key(key)
        if not isinstance(value, str):
            raise ValueError(f"output variable value must be a string: {key}")

    meta_path = artifacts_path / "agent_meta.json"
    with _locked_agent_meta(meta_path):
        meta = read_json_object(meta_path)
        merged = {**_string_output_variables(meta.get(_OUTPUT_VARIABLES_FIELD))}
        merged.update(variables)
        meta[_OUTPUT_VARIABLES_FIELD] = merged
        _write_json_object_atomic(meta_path, meta)

    update_agent_artifact_index_for_marker_mutation(artifacts_path)
    return merged


def _validate_output_variable_key(key: str) -> None:
    if not key:
        raise ValueError("output variable key must not be empty")
    if _KEY_RE.fullmatch(key) is None:
        raise ValueError(
            "output variable key must be a valid Jinja attribute identifier "
            f"([A-Za-z_][A-Za-z0-9_]*): {key}"
        )


def _string_output_variables(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


@contextmanager
def _locked_agent_meta(meta_path: Path) -> Iterator[None]:
    lock_path = meta_path.with_name(f".{meta_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_json_object_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp_path, path)


__all__ = [
    "parse_output_variable_assignments",
    "read_agent_output_variables",
    "set_agent_output_variables",
]
