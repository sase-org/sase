"""Core regression coverage for the user-facing SASE config schema."""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from sase.config.inventory import config_schema_path
from tests._config_schema_helpers import REPO_ROOT, format_schema_error, schema


pytestmark = pytest.mark.contract


def test_config_schema_resolves_inside_sase_package() -> None:
    schema_path = config_schema_path().resolve()
    package_root = Path(str(importlib.resources.files("sase"))).resolve()

    assert schema_path.is_file()
    assert schema_path.is_relative_to(package_root)
    json.loads(schema_path.read_text(encoding="utf-8"))


def test_default_config_matches_public_schema() -> None:
    public_schema = schema()
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text()
    )

    Draft7Validator.check_schema(public_schema)
    errors = sorted(
        Draft7Validator(public_schema).iter_errors(default_config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_allows_base_config_without_identity() -> None:
    validator = Draft7Validator(schema())

    validator.validate({})
    validator.validate(
        {
            "use_chezmoi": True,
            "max_running_agents": 10,
        }
    )


def test_config_schema_validates_nested_owner_and_legacy_machine_name() -> None:
    validator = Draft7Validator(schema())

    validator.validate({"id": {"username": "alice-2", "machine_name": "athena"}})
    validator.validate({"machine_name": "athena"})
    validator.validate({"machine_name": "build_host"})
    for invalid in ("Athena", "host-1", "host1", ""):
        with pytest.raises(ValidationError):
            validator.validate({"id": {"username": "alice", "machine_name": invalid}})
    for invalid in ("Alice", "alice.", "a--b", "agents", "sase"):
        with pytest.raises(ValidationError):
            validator.validate({"id": {"username": invalid, "machine_name": "athena"}})

    assert schema()["properties"]["machine_name"]["deprecated"] is True


def test_config_schema_validates_project_glossary_shape() -> None:
    validator = Draft7Validator(schema())

    valid_glossary = {
        "Agent Clan": {
            "aliases": ["agent clans", "clan"],
            "definition": "A named, rootless container.",
        },
        "Workspace": {
            "definition": "A numbered project checkout.",
        },
    }
    validator.validate({"memory": {"glossary": valid_glossary}})

    for invalid in (
        {"Agent Clan": {"aliases": ["clan"]}},
        {"Agent Clan": {"definition": ""}},
        {"Agent Clan": {"definition": "Valid", "aliases": ["two\nlines"]}},
        {"Agent Clan": {"definition": "Valid", "unknown": True}},
        {"": {"definition": "Blank term"}},
    ):
        with pytest.raises(ValidationError):
            validator.validate({"memory": {"glossary": invalid}})
