"""JSON Schema generation for registry-owned feature flags."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sase.feature_flags.models import FeatureFlagDefinition
from sase.feature_flags.registry import feature_flag_definitions


# symvision: tools/sync_feature_flags_schema
def feature_flags_schema_block(
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
) -> dict[str, Any]:
    """Return the generated ``feature_flags`` JSON Schema block."""
    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    properties: dict[str, Any] = {}
    for key, definition in sorted(resolved_definitions.items()):
        property_schema: dict[str, Any] = {
            "type": "boolean",
            "description": definition.description,
            "default": definition.default,
        }
        if definition.kind == "sunset":
            property_schema["deprecated"] = True
        properties[key] = property_schema

    return {
        "type": "object",
        "description": "Code-owned SASE feature flags keyed by flag name.",
        "additionalProperties": {"type": "boolean"},
        "properties": properties,
    }


def _stable_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


# symvision: tools/sync_feature_flags_schema
def feature_flags_schema_drift(document: Mapping[str, Any]) -> str | None:
    """Return a human-readable drift message for *document*, or ``None``."""
    properties = document.get("properties")
    actual: Any
    if isinstance(properties, Mapping):
        actual = properties.get("feature_flags")
    else:
        actual = None
    expected = feature_flags_schema_block()
    if actual == expected:
        return None
    return (
        "feature_flags schema block is out of sync with the registry\n"
        f"expected:\n{_stable_json(expected)}\n"
        f"actual:\n{_stable_json(actual)}"
    )
