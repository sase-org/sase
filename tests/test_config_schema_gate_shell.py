"""Schema coverage for gate-shell configuration."""

from __future__ import annotations

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import REPO_ROOT, schema


pytestmark = pytest.mark.contract


def test_config_schema_accepts_gate_shell_reclaim_grace_seconds() -> None:
    Draft7Validator(schema()).validate(
        {"gate": {"shell": {"reclaim_grace_seconds": 0}}}
    )
    Draft7Validator(schema()).validate(
        {"gate": {"shell": {"reclaim_grace_seconds": 7200}}}
    )


@pytest.mark.parametrize("value", [-1, True, "3600"])
def test_config_schema_rejects_invalid_gate_shell_reclaim_grace_seconds(
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"gate": {"shell": {"reclaim_grace_seconds": value}}}
        )


def test_gate_shell_schema_default_matches_default_config_and_constant() -> None:
    from sase.config import DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS

    public_schema = schema()
    gate_shell_schema = public_schema["properties"]["gate"]["properties"]["shell"][
        "properties"
    ]
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    default_gate_shell = default_config["gate"]["shell"]

    assert (
        gate_shell_schema["reclaim_grace_seconds"]["default"]
        == default_gate_shell["reclaim_grace_seconds"]
        == DEFAULT_GATE_SHELL_RECLAIM_GRACE_SECONDS
    )
