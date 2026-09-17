"""Contract tests for the typed Rust-backed `service.procs` config facade."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.config.core import ConfigLayer
from sase.service.config import (
    ServiceConfigError,
    compose_service_config,
    load_service_config,
)


def test_the_real_default_config_composes_scheduler_enabled_gateway_disabled() -> None:
    composition = load_service_config()

    assert composition.diagnostics == ()
    scheduler = composition.get("scheduler")
    gateway = composition.get("gateway")
    assert scheduler is not None
    assert gateway is not None
    assert scheduler.enabled is True
    assert scheduler.available is True
    assert gateway.enabled is False
    assert gateway.available is True


def test_an_overlay_replaces_a_plugin_declared_entry_field_whole() -> None:
    layers = [
        ConfigLayer(
            name="plugin:example",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "service": {
                    "procs": {
                        "tunnel": {
                            "command": ["run-tunnel"],
                            "success_exit_codes": [0, 1],
                        }
                    }
                }
            },
        ),
        ConfigLayer(
            name="user",
            path="/home/u/sase.yml",
            exists=True,
            list_strategy="concatenate",
            data={
                "service": {
                    "procs": {
                        "tunnel": {
                            "command": ["run-tunnel", "--verbose"],
                            "success_exit_codes": [0],
                            "enabled": True,
                        }
                    }
                }
            },
        ),
    ]

    composition = compose_service_config(layers)

    tunnel = composition.get("tunnel")
    assert tunnel is not None
    assert tunnel.available, tunnel.unavailable_reasons
    assert tunnel.source == "plugin"
    assert tunnel.success_exit_codes == (0,)
    assert tunnel.launcher is not None
    assert tunnel.launcher.argv == ("run-tunnel", "--verbose")
    # A plugin-declared entry defaults disabled; the user layer re-enables it.
    assert tunnel.enabled is True
    assert tunnel.enablement.explicit is True
    assert tunnel.enablement.layer == "user:/home/u/sase.yml"


def test_a_local_layer_service_section_is_ignored_with_a_warning() -> None:
    layers = [
        ConfigLayer(
            name="local",
            path="/proj/sase.yml",
            exists=True,
            list_strategy="concatenate",
            data={"service": {"procs": {"tunnel": {"command": "x"}}}},
        ),
    ]

    composition = compose_service_config(layers)

    assert composition.procs == ()
    assert composition.ignored_layers == ("local:/proj/sase.yml",)
    assert any(
        diagnostic.code == "service_config_ignored_in_project_layer"
        and diagnostic.severity == "warning"
        for diagnostic in composition.diagnostics
    )
    assert composition.fatal is False


def test_a_fatal_section_error_raises_service_config_error() -> None:
    layers = [
        ConfigLayer(
            name="user",
            path="/home/u/sase.yml",
            exists=True,
            list_strategy="concatenate",
            data={"service": "not-a-mapping"},
        ),
    ]

    with patch("sase.service.config.load_config_layers", return_value=layers):
        with pytest.raises(ServiceConfigError) as excinfo:
            load_service_config()

    assert excinfo.value.diagnostics
    assert all(
        diagnostic.severity == "error" for diagnostic in excinfo.value.diagnostics
    )
