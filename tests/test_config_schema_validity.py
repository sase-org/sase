"""Meta-validation for bundled JSON schemas."""

from __future__ import annotations

import importlib.resources
import json
from collections.abc import Iterator
from typing import Any

from jsonschema import Draft7Validator

from tests._config_schema_helpers import schema as config_schema


def _workflow_schema() -> dict[str, Any]:
    resource = importlib.resources.files("sase") / "xprompts" / "workflow.schema.json"
    document = json.loads(resource.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _bundled_schemas() -> Iterator[tuple[str, dict[str, Any]]]:
    yield "src/sase/config/sase.schema.json", config_schema()
    yield "src/sase/xprompts/workflow.schema.json", _workflow_schema()


def _json_pointer(path: tuple[str, ...]) -> str:
    if not path:
        return ""
    escaped = [part.replace("~", "~0").replace("/", "~1") for part in path]
    return "/" + "/".join(escaped)


def _enum_fingerprint(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _duplicate_enum_errors(enum_values: list[Any], path: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    errors: list[str] = []
    for value in enum_values:
        fingerprint = _enum_fingerprint(value)
        if fingerprint in seen:
            errors.append(f"{_json_pointer(path)} duplicates enum value {fingerprint}")
            continue
        seen.add(fingerprint)
    return errors


def _enum_duplicate_errors(node: Any, path: tuple[str, ...] = ()) -> list[str]:
    errors: list[str] = []
    if isinstance(node, dict):
        enum_values = node.get("enum")
        if isinstance(enum_values, list):
            errors.extend(_duplicate_enum_errors(enum_values, (*path, "enum")))
        for key, value in node.items():
            errors.extend(_enum_duplicate_errors(value, (*path, str(key))))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            errors.extend(_enum_duplicate_errors(value, (*path, str(index))))
    return errors


def test_bundled_json_schemas_are_valid_and_have_unique_enum_values() -> None:
    duplicate_errors: list[str] = []
    for label, document in _bundled_schemas():
        Draft7Validator.check_schema(document)
        duplicate_errors.extend(
            f"{label}: {error}" for error in _enum_duplicate_errors(document)
        )

    assert duplicate_errors == []
