"""Tests for composing layered axe lumberjack config."""

from unittest.mock import patch

from sase.axe.config import _compose_keyed_axe_layers, load_axe_config
from sase.config.core import ConfigLayer


def test_load_axe_config_allows_sparse_interval_overlay() -> None:
    base = ConfigLayer(
        name="default",
        path=None,
        exists=True,
        list_strategy="concatenate",
        data={
            "axe": {
                "lumberjacks": {
                    "hooks": {
                        "description": "Run hook checks",
                        "interval": 1,
                        "chops": {
                            "hook_checks": {
                                "description": "Check hooks",
                            }
                        },
                    }
                }
            }
        },
    )
    overlay = ConfigLayer(
        name="overlay:test.yml",
        path="/tmp/test.yml",
        exists=True,
        list_strategy="concatenate",
        data={
            "axe": {
                "lumberjacks": {
                    "hooks": {
                        "interval": 5,
                    }
                }
            }
        },
    )

    with (
        patch("sase.axe.config.load_merged_config", return_value=overlay.data),
        patch("sase.axe.config.load_config_layers", return_value=[base, overlay]),
    ):
        config = load_axe_config()

    assert config.lumberjacks["hooks"].interval == 5


def test_keyed_layer_composition_patches_fields_and_tracks_provenance() -> None:
    default = ConfigLayer(
        name="default",
        path=None,
        exists=True,
        list_strategy="concatenate",
        data={
            "axe": {
                "lumberjacks": {
                    "checks": {
                        "description": "Run audit checks",
                        "interval": 60,
                        "chops": [
                            {
                                "name": "audit",
                                "script": "audit-script",
                                "description": "packaged",
                            }
                        ],
                    }
                }
            }
        },
    )
    overlay = ConfigLayer(
        name="overlay:athena.yml",
        path="/tmp/athena.yml",
        exists=True,
        list_strategy="concatenate",
        data={
            "axe": {
                "lumberjacks": {
                    "checks": {
                        "chops": {
                            "audit": {"run_every": "1d"},
                            "unused": {
                                "description": "Retain a disabled audit check",
                                "enabled": False,
                            },
                        }
                    }
                }
            }
        },
    )

    composed, provenance, diagnostics = _compose_keyed_axe_layers([default, overlay])

    assert diagnostics == []
    audit = composed["axe"]["lumberjacks"]["checks"]["chops"]["audit"]
    assert audit == {
        "name": "audit",
        "script": "audit-script",
        "description": "packaged",
        "run_every": "1d",
    }
    assert provenance["axe.lumberjacks.checks.chops.audit.script"] == "default"
    assert (
        provenance["axe.lumberjacks.checks.chops.audit.run_every"]
        == "overlay:athena.yml:/tmp/athena.yml"
    )

    with (
        patch("sase.axe.config.load_merged_config", return_value=overlay.data),
        patch("sase.axe.config.load_config_layers", return_value=[default, overlay]),
    ):
        loaded = load_axe_config()

    loaded_audit = loaded.lumberjacks["checks"].chops[0]
    assert loaded_audit.name == "audit"
    assert loaded_audit.script == "audit-script"
    assert loaded_audit.description == "packaged"
    assert loaded_audit.run_every == 86400
    assert loaded_audit.provenance["run_every"] == (
        "overlay:athena.yml:/tmp/athena.yml"
    )
    assert loaded.lumberjacks["checks"].chops[1].enabled is False


def test_keyed_composition_keeps_legacy_list_duplicates_fail_closed() -> None:
    def _layer(name: str) -> ConfigLayer:
        return ConfigLayer(
            name=name,
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "axe": {
                    "lumberjacks": {
                        "checks": {
                            "description": "Run audit checks",
                            "interval": 60,
                            "chops": [
                                {
                                    "name": "audit",
                                    "description": "Audit configured changes",
                                }
                            ],
                        }
                    }
                }
            },
        )

    _, _, diagnostics = _compose_keyed_axe_layers(
        [_layer("default"), _layer("plugin:audit")]
    )

    assert [item.code for item in diagnostics] == ["duplicate_chop_identity"]
    assert diagnostics[0].layer == "plugin:audit"
