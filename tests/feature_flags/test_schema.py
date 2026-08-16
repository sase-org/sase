"""Feature-flag schema generation tests."""

from __future__ import annotations

import copy
from typing import Any

from sase.config.inventory import config_field_model, load_config_schema
from sase.core.rust import require_rust_binding
from sase.feature_flags.schema import (
    feature_flags_schema_block,
    feature_flags_schema_drift,
)

from ._helpers import definitions, demo_flag


def test_feature_flags_schema_block_is_ordered_and_marks_sunset_flags() -> None:
    block = feature_flags_schema_block(
        definitions(
            demo_flag("zeta_flag", default=True),
            demo_flag("old_flag", kind="sunset"),
        )
    )

    assert list(block["properties"]) == ["old_flag", "zeta_flag"]
    assert block["properties"]["zeta_flag"]["default"] is True
    assert block["properties"]["old_flag"]["deprecated"] is True
    assert block["additionalProperties"] == {"type": "boolean"}


def test_shipped_schema_feature_flags_block_has_no_drift() -> None:
    schema = load_config_schema()

    assert feature_flags_schema_drift(schema) is None

    mutated = copy.deepcopy(schema)
    mutated["properties"]["feature_flags"]["description"] = "wrong"
    assert feature_flags_schema_drift(mutated) is not None


def test_generated_block_integrates_with_field_model_and_validator() -> None:
    document: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "feature_flags": feature_flags_schema_block(
                definitions(demo_flag("demo_flag"))
            )
        },
    }

    fields = {field.path: field for field in config_field_model(document).fields}
    assert fields["feature_flags"].kind == "object"
    assert fields["feature_flags.demo_flag"].kind == "scalar"
    assert fields["feature_flags.demo_flag"].types == ("boolean",)
    assert fields["feature_flags.demo_flag"].has_default is True

    config_validate = require_rust_binding("config_validate")
    diagnostics = config_validate(
        {
            "schema": document,
            "config": {"feature_flags": {"demo_flag": "yes"}},
        }
    )
    assert [diagnostic["code"] for diagnostic in diagnostics] == ["type_mismatch"]
    assert (
        config_validate(
            {
                "schema": document,
                "config": {"feature_flags": {"unknown_flag": True}},
            }
        )
        == []
    )
