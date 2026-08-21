"""Host catalog builder for ``%final`` completion."""

from __future__ import annotations

from unittest.mock import patch

from sase.config.core import ConfigLayer
from sase.finalizers.catalog import (
    _catalog_from_config,
    build_finalizer_completion_catalog,
)
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerConfigDiagnostic,
    FinalizerFieldProvenance,
)


def _instance(
    instance_id: str,
    provider_ref: str = "builtin@command",
    *,
    after: tuple[str, ...] = (),
    max_attempts: int = 1,
    layer: str = "user",
) -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id=instance_id,
        provider_ref=provider_ref,
        after=after,
        max_attempts=max_attempts,
        provenance={"use": FinalizerFieldProvenance(layer, "/tmp/sase.yml")},
    )


def test_catalog_orders_required_then_defaults_then_optional_alphabetically() -> None:
    config = FinalizerConfig(
        defaults=("zoom", "lint"),
        required=("commit",),
        instances={
            "zoom": _instance("zoom", "plugin@zoom"),
            "lint": _instance("lint", after=("format",), max_attempts=2),
            "commit": _instance("commit", "builtin@commit", max_attempts=2),
            "alpha": _instance("alpha"),
        },
        provenance={},
    )

    built = _catalog_from_config(config)

    assert built.ok
    assert [entry.value for entry in built.entries] == [
        "commit",
        "lint",
        "zoom",
        "alpha",
    ]
    assert built.entries[0].required is True
    assert built.entries[0].is_default is False
    assert built.entries[1].is_default is True
    assert built.entries[2].is_default is True
    assert built.entries[3].required is False
    assert built.entries[3].is_default is False


def test_catalog_documentation_covers_provider_after_retry_and_provenance() -> None:
    config = FinalizerConfig(
        defaults=("lint",),
        required=("commit",),
        instances={
            "commit": _instance("commit", "builtin@commit", max_attempts=2),
            "lint": _instance("lint", after=("format",), max_attempts=3),
        },
        provenance={},
    )

    docs = {
        entry.value: entry.documentation
        for entry in _catalog_from_config(config).entries
    }

    assert "Required for this launch." in docs["commit"]
    assert "Provider: `builtin@commit`" in docs["commit"]
    assert "Retry policy: 2 attempts" in docs["commit"]
    assert "Configured from `user:/tmp/sase.yml`" in docs["commit"]
    assert "Selected by default." in docs["lint"]
    assert "Depends on: `format`" in docs["lint"]
    assert "Retry policy: 3 attempts" in docs["lint"]


def test_catalog_wire_rows_are_compact_and_mixed_version_safe() -> None:
    config = FinalizerConfig(
        defaults=(),
        required=(),
        instances={"zoom": _instance("zoom", "plugin@zoom")},
        provenance={},
    )

    payload = _catalog_from_config(config).wire_entries()[0]

    assert payload["value"] == "zoom"
    assert payload["provider_ref"] == "plugin@zoom"
    assert "required" not in payload
    assert "default" not in payload
    assert "after" not in payload
    assert payload["max_attempts"] == 1


def test_fatal_diagnostics_fail_closed_without_invented_rows() -> None:
    config = FinalizerConfig(
        defaults=("commit",),
        required=(),
        instances={"commit": _instance("commit", "builtin@commit")},
        provenance={},
        diagnostics=(
            FinalizerConfigDiagnostic(
                severity="error",
                code="not_a_mapping",
                message="finalizers must be a mapping",
                layer="user",
                path="finalizers",
            ),
        ),
    )

    built = _catalog_from_config(config)

    assert built.status == "error"
    assert built.entries == ()
    assert "finalizers must be a mapping" in built.message


def test_catalog_cache_replays_config_once_per_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loads: list[int] = []

    def fake_load() -> FinalizerConfig:
        loads.append(1)
        return FinalizerConfig(
            defaults=(),
            required=(),
            instances={"commit": _instance("commit", "builtin@commit")},
            provenance={},
        )

    monkeypatch.setattr(
        "sase.finalizers.catalog.current_config_token",
        lambda: ("token-a",),
    )
    monkeypatch.setattr("sase.finalizers.catalog.load_finalizer_config", fake_load)

    first = build_finalizer_completion_catalog()
    second = build_finalizer_completion_catalog()

    assert first.entries[0].value == "commit"
    assert second.entries[0].value == "commit"
    assert loads == [1]

    monkeypatch.setattr(
        "sase.finalizers.catalog.current_config_token",
        lambda: ("token-b",),
    )
    build_finalizer_completion_catalog()
    assert loads == [1, 1]


def test_catalog_builder_does_not_import_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [
            ConfigLayer(
                name="default",
                path=None,
                exists=True,
                list_strategy="concatenate",
                data={
                    "finalizers": {
                        "defaults": ["commit"],
                        "required": [],
                        "instances": {
                            "commit": {
                                "use": "builtin@commit",
                                "max_attempts": 2,
                            }
                        },
                    }
                },
            )
        ],
    )
    monkeypatch.delitem(
        __import__("sys").modules, "sase.finalizers.providers", raising=False
    )

    built = build_finalizer_completion_catalog(use_cache=False)

    assert built.ok
    assert "sase.finalizers.providers" not in __import__("sys").modules
