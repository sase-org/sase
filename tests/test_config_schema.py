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


def test_config_schema_accepts_dispatch_federation_contract() -> None:
    validator = Draft7Validator(schema())

    validator.validate(
        {
            "dispatch": {
                "federation_worker": {
                    "enabled": True,
                    "command": "sase_federation_worker",
                    "sase_home": "/tmp/sase",
                    "run_root": "/tmp/sase/run",
                    "socket_path": "/tmp/sase/run/worker.sock",
                    "idle_timeout_seconds": 300,
                    "startup_timeout_seconds": 5,
                    "request_timeout_seconds": 5,
                    "max_frame_bytes": 1048576,
                },
                "remote_hosts": [
                    {
                        "enabled": True,
                        "alias": "remote",
                        "provider_ref": "fleet",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "env:SASE_FLEET_TOKEN",
                        "pinned_installation_id": "remote-install",
                        "connection_kind": "gateway",
                    }
                ],
            }
        }
    )

    with pytest.raises(ValidationError):
        validator.validate(
            {
                "dispatch": {
                    "remote_hosts": [
                        {"endpoint": "https://fleet.example.test", "extra": True}
                    ]
                }
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


def test_config_schema_rejects_retired_memory_glossary() -> None:
    validator = Draft7Validator(schema())

    with pytest.raises(ValidationError):
        validator.validate(
            {
                "memory": {
                    "glossary": {
                        "Workspace": {"definition": "A numbered project checkout."}
                    }
                }
            }
        )


def test_config_schema_accepts_both_finalizer_refusal_policies() -> None:
    """The public schema must not lag the finalizer config validator.

    ``src/sase/finalizers/config.py`` accepts ``fail`` and ``defer``, and
    ``default_config.yml`` ships ``defer``. The schema drifted behind both
    once already, which broke every schema-driven config surface.
    """

    validator = Draft7Validator(schema())

    for refusal in ("fail", "defer"):
        validator.validate(
            {
                "finalizers": {
                    "instances": {
                        "commit": {"use": "builtin@commit", "refusal": refusal}
                    }
                }
            }
        )

    with pytest.raises(ValidationError):
        validator.validate(
            {
                "finalizers": {
                    "instances": {
                        "commit": {"use": "builtin@commit", "refusal": "ignore"}
                    }
                }
            }
        )


def test_config_schema_validates_dispatch_machine_records() -> None:
    validator = Draft7Validator(schema())
    pin = "sase_inst_v1_" + "a" * 64

    validator.validate(
        {
            "dispatch": {
                "providers": {"builtin@https": {"enabled": True}},
                "machines": {
                    "alpha": {
                        "provider": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "fleet:alpha",
                        "installation_pin": pin,
                    }
                },
                "discovery": {"enabled_providers": ["builtin@tailnet"]},
            }
        }
    )

    with pytest.raises(ValidationError):
        validator.validate(
            {
                "dispatch": {
                    "machines": {
                        "alpha": {
                            "provider": "builtin@https",
                            "endpoint": "http://fleet.example.test",
                            "credential_ref": "fleet:alpha",
                            "installation_pin": pin,
                        }
                    }
                }
            }
        )

    with pytest.raises(ValidationError):
        validator.validate(
            {
                "dispatch": {
                    "machines": {
                        "alpha": {
                            "provider": "builtin@https",
                            "endpoint": "https://fleet.example.test",
                            "credential_ref": "fleet:alpha",
                            "installation_pin": pin,
                            "token": "must-not-be-here",
                        }
                    }
                }
            }
        )
