from __future__ import annotations

import json
from dataclasses import asdict

from sase.host.client import _host_request_payload
from sase.host.runtime import ProviderHostRuntime, ProviderHostRuntimeConfig
from sase.host.wire import (
    HOST_CAP_LLM_METADATA,
    HOST_CAP_XPROMPT_CATALOG,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostResponseEnvelopeWire,
)
from sase.llm_provider import registry
from sase.xprompt import catalog
from sase.xprompt._catalog_structured import (
    build_structured_xprompts_catalog as build_structured_xprompts_catalog_direct,
)
from sase.xprompt._catalog_models import (
    StructuredCatalogProjection,
    StructuredCatalogStats,
)


def _ok_response(result: dict[str, object]) -> HostResponseEnvelopeWire:
    return HostResponseEnvelopeWire(
        schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
        request_id="host_req_test",
        status="ok",
        result=result,
    )


def test_llm_metadata_host_operation_matches_direct_registry() -> None:
    direct = registry.direct_llm_metadata_payload()
    request = _host_request_payload(
        family="llm",
        operation="llm.metadata",
        payload={},
        required_capability=HOST_CAP_LLM_METADATA,
    )
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())

    response = runtime.handle_json_frame(json.dumps(request))

    assert response.status == "ok"
    assert response.result == direct


def test_registry_metadata_uses_host_without_entry_point_imports(monkeypatch) -> None:
    payload = {
        "model_to_provider": {"model-a": "provider-a"},
        "provider_short_names": {"provider-a": "pa"},
        "model_short_aliases": {"model-a": "ma"},
        "provider_cli_status_colors": {"provider-a": "#123456"},
        "provider_names": ["provider-a"],
        "autodetect_candidates": [],
        "default_retry_configs": {},
    }

    monkeypatch.setattr(
        registry, "call_provider_host", lambda **_: _ok_response(payload)
    )
    monkeypatch.setattr(
        registry.importlib.metadata,
        "entry_points",
        lambda **_: (_ for _ in ()).throw(AssertionError("direct entry points used")),
    )

    assert registry.model_to_provider_map() == {"model-a": "provider-a"}
    assert registry.provider_short_name_map() == {"provider-a": "pa"}
    assert registry.model_short_alias_map() == {"model-a": "ma"}
    assert registry.provider_cli_status_color_map() == {"provider-a": "#123456"}
    assert registry.resolve_model_provider("provider-a/model-a") == (
        "provider-a",
        "model-a",
    )


def test_xprompt_catalog_host_operation_matches_direct_structured_catalog() -> None:
    direct = build_structured_xprompts_catalog_direct(limit=5)
    request = _host_request_payload(
        family="xprompt",
        operation="xprompt.catalog",
        payload={"include_pdf": False, "limit": 5},
        required_capability=HOST_CAP_XPROMPT_CATALOG,
    )
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())

    response = runtime.handle_json_frame(json.dumps(request))

    assert response.status == "ok"
    assert response.result["projection"] == asdict(direct)
    assert response.result["cache_invalidation"]["version"] == 1


def test_structured_catalog_uses_host_without_direct_catalog_imports(
    monkeypatch,
) -> None:
    projection = StructuredCatalogProjection(
        entries=[],
        stats=StructuredCatalogStats(
            total_count=0,
            project_count=0,
            skill_count=0,
            pdf_requested=False,
        ),
        warnings=[],
        skipped=[],
        catalog_attachment=None,
    )

    monkeypatch.setattr(
        catalog,
        "call_provider_host",
        lambda **_: _ok_response({"projection": asdict(projection)}),
    )
    monkeypatch.setattr(
        catalog,
        "get_all_xprompts",
        lambda *_, **__: (_ for _ in ()).throw(
            AssertionError("direct xprompt loader used")
        ),
    )

    assert catalog.build_structured_xprompts_catalog() == projection
