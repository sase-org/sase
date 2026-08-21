"""Provider identity canonicalization and single-invocation dispatch."""

from __future__ import annotations

from collections.abc import Mapping
import importlib
import io
import json
from pathlib import Path
import sys
from typing import Any

import pytest

from sase.config.core import ConfigLayer
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    load_finalizer_config,
)
from sase.finalizers.providers import (
    FinalizerProviderRecord,
    collect_finalizer_providers,
    diagnose_finalizer_providers,
    provider_records_by_ref,
    provider_ref_key,
)
from sase.finalizers.sdk import ProviderShapeError, dispatch_provider_request
from sase.finalizers.worker_entry import main as worker_main
from sase.plugins.inventory import PluginInventory, _PluginEntryPointRecord

_MIXED_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mixed_finalizer_plugin"
_CANONICAL_REF = "mixed-case-finalizers@audit"
_RAW_PACKAGE = "Mixed.Case_Finalizers"


def _ok(operation: str = "execute") -> dict[str, Any]:
    return {"schema_version": 1, "operation": operation, "status": "ok"}


def _inventory(*packages: str) -> PluginInventory:
    entries = tuple(
        _PluginEntryPointRecord(
            group="sase_finalizers",
            name="audit",
            value="mixed_case_finalizers:provider",
            package=package,
            version="1.0.0",
            load_status="not_loaded",
        )
        for package in packages
    )
    return PluginInventory(entry_points=entries, distributions=(), disabled_env=())


def _inventory_fn(inventory: PluginInventory) -> Any:
    def load(*, load_resource_entry_points: bool = True) -> PluginInventory:
        return inventory

    return load


def _config(provider_ref: str) -> FinalizerConfig:
    return FinalizerConfig(
        defaults=("audit",),
        required=(),
        instances={
            "audit": ConfiguredFinalizerInstance(
                instance_id="audit",
                provider_ref=provider_ref,
            )
        },
        provenance={},
    )


def test_discovery_canonicalizes_mixed_case_distribution_names() -> None:
    providers = collect_finalizer_providers(
        inventory_fn=_inventory_fn(_inventory("Example.Finalizers"))
    )
    plugin = next(item for item in providers if not item.builtin)
    assert plugin.provider_ref == "example-finalizers@audit"
    assert plugin.package == "Example.Finalizers"


@pytest.mark.parametrize(
    "configured",
    (
        "Example_Finalizers@audit",
        "example.finalizers@audit",
        "example-finalizers@audit",
    ),
)
def test_diagnose_matches_punctuation_equivalent_provider_refs(configured: str) -> None:
    diagnostics = diagnose_finalizer_providers(
        _config(configured),
        inventory_fn=_inventory_fn(_inventory("Example.Finalizers")),
    )
    assert diagnostics == ()


def test_equivalent_distribution_names_are_duplicate_providers() -> None:
    diagnostics = diagnose_finalizer_providers(
        _config("example-finalizers@audit"),
        inventory_fn=_inventory_fn(
            _inventory("Example.Finalizers", "example_finalizers")
        ),
    )
    assert any(item.code == "duplicate_provider" for item in diagnostics)
    assert any(item.provider_ref == "example-finalizers@audit" for item in diagnostics)


def test_provider_records_by_ref_keys_canonical_names() -> None:
    providers = (
        FinalizerProviderRecord(
            provider_ref="Example_Finalizers@audit",
            provider_id="audit",
            package="Example_Finalizers",
            version="1.0.0",
            entry_point="pkg:provider",
            builtin=False,
        ),
    )
    by_ref = provider_records_by_ref(providers)
    assert provider_ref_key("example.finalizers@audit") in by_ref
    assert by_ref["example-finalizers@audit"] is providers[0]


def test_config_freeze_canonicalizes_use_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.config.load_config_layers",
        lambda: [
            ConfigLayer(
                name="user",
                path=None,
                exists=True,
                list_strategy="replace",
                data={
                    "finalizers": {
                        "defaults": ["audit"],
                        "instances": {
                            "audit": {"use": "Example_Finalizers@audit"},
                            "commit": {"use": "Builtin@commit"},
                        },
                    }
                },
            )
        ],
    )

    config = load_finalizer_config()

    assert config.instances["audit"].provider_ref == "example-finalizers@audit"
    assert config.instances["commit"].provider_ref == "builtin@commit"


def test_method_bearing_provider_is_invoked_once() -> None:
    class Provider:
        calls = 0

        def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            type(self).calls += 1
            return _ok()

        def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            raise AssertionError("method-bearing objects must not use __call__")

    provider = Provider()
    assert dispatch_provider_request(provider, {"operation": "execute"}) == _ok()
    assert Provider.calls == 1


def test_class_entry_point_is_a_zero_argument_factory() -> None:
    class Provider:
        calls = 0

        def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            type(self).calls += 1
            assert request["operation"] == "execute"
            return _ok()

    assert dispatch_provider_request(Provider, {"operation": "execute"}) == _ok()
    assert Provider.calls == 1


def test_factory_function_is_invoked_once() -> None:
    calls = {"factory": 0, "execute": 0}

    class Provider:
        def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            calls["execute"] += 1
            return _ok()

    def factory() -> Provider:
        calls["factory"] += 1
        return Provider()

    assert dispatch_provider_request(factory, {"operation": "execute"}) == _ok()
    assert calls == {"factory": 1, "execute": 1}


def test_request_callable_typeerror_is_not_rewritten() -> None:
    calls = {"count": 0}

    def provider(request: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["count"] += 1
        raise TypeError("internal boom")

    with pytest.raises(TypeError, match="internal boom"):
        dispatch_provider_request(provider, {"operation": "execute"})
    assert calls["count"] == 1


def test_method_typeerror_is_not_rewritten_as_missing_operation() -> None:
    class Provider:
        calls = 0

        def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            type(self).calls += 1
            raise TypeError("internal boom")

    with pytest.raises(TypeError, match="internal boom"):
        dispatch_provider_request(Provider(), {"operation": "execute"})
    assert Provider.calls == 1


def test_ambiguous_optional_request_parameter_is_rejected_without_calling() -> None:
    calls = {"count": 0}

    def provider(request: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        calls["count"] += 1
        return _ok()

    with pytest.raises(ProviderShapeError, match="ambiguous"):
        dispatch_provider_request(provider, {"operation": "execute"})
    assert calls["count"] == 0


def test_class_requiring_init_args_is_rejected_without_constructing() -> None:
    class Provider:
        constructed = False

        def __init__(self, request: Mapping[str, Any]) -> None:
            type(self).constructed = True

        def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            return _ok()

    with pytest.raises(ProviderShapeError, match="zero-argument factories"):
        dispatch_provider_request(Provider, {"operation": "execute"})
    assert Provider.constructed is False


def _install_mixed_site(monkeypatch: pytest.MonkeyPatch, site: Path) -> None:
    site.mkdir(parents=True)
    (site / "mixed_case_finalizers.py").write_text(
        (_MIXED_FIXTURE / "mixed_case_finalizers.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    dist = site / "Mixed.Case_Finalizers-1.0.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {_RAW_PACKAGE}\nVersion: 1.0.0\n",
        encoding="utf-8",
    )
    (dist / "entry_points.txt").write_text(
        "[sase_finalizers]\naudit = mixed_case_finalizers:provider\n",
        encoding="utf-8",
    )
    sys.modules.pop("mixed_case_finalizers", None)
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()


def _run_worker(
    monkeypatch: pytest.MonkeyPatch,
    provider_ref: str,
    request: Mapping[str, Any],
) -> tuple[int, dict[str, Any]]:
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(dict(request))))
    monkeypatch.setattr(sys, "stdout", stdout)
    returncode = worker_main(
        ["--provider-ref", provider_ref, "--operation", str(request["operation"])]
    )
    return returncode, json.loads(stdout.getvalue())


@pytest.mark.parametrize(
    "provider_ref",
    (
        _CANONICAL_REF,
        "Mixed.Case_Finalizers@audit",
        "Mixed_Case.Finalizers@audit",
    ),
)
def test_worker_discovers_punctuation_equivalent_distribution_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_ref: str,
) -> None:
    site = tmp_path / "site"
    _install_mixed_site(monkeypatch, site)

    providers = collect_finalizer_providers()
    plugin = next(item for item in providers if item.provider_ref == _CANONICAL_REF)
    assert plugin.package == _RAW_PACKAGE
    assert (
        diagnose_finalizer_providers(
            _config(provider_ref),
            inventory_fn=_inventory_fn(
                _inventory(_RAW_PACKAGE),
            ),
        )
        == ()
    )

    returncode, payload = _run_worker(
        monkeypatch,
        provider_ref,
        {"operation": "execute", "instance_id": "audit"},
    )

    assert returncode == 0
    assert payload["provider_ref"] == _CANONICAL_REF
    assert payload["status"] == "success"


def test_worker_preserves_internal_typeerror_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = tmp_path / "site"
    _install_mixed_site(monkeypatch, site)

    returncode, payload = _run_worker(
        monkeypatch,
        "Mixed_Case.Finalizers@audit",
        {
            "operation": "execute",
            "instance_id": "audit",
            "payload": {"boom": True},
        },
    )
    imported = importlib.import_module("mixed_case_finalizers")

    assert returncode == 1
    assert payload["diagnostics"][0]["message"] == "TypeError: internal boom"
    assert "does not implement operation" not in payload["diagnostics"][0]["message"]
    assert imported.CALLS == 1
