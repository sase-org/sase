from __future__ import annotations

import json
from dataclasses import asdict

from sase.host.client import _host_request_payload
from sase.host.provider_queries import provider_host_queries_enabled
from sase.host.routing import host_routing_diagnostics, host_routing_mode
from sase.host.runtime import ProviderHostRuntime, ProviderHostRuntimeConfig
from sase.host.wire import (
    HOST_CAP_LLM_INVOKE,
    HOST_CAP_LLM_METADATA,
    HOST_CAP_WORKFLOW_STEP,
    HOST_CAP_XPROMPT_CATALOG,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostResponseEnvelopeWire,
)
from sase.llm_provider.types import InvokeResult
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


def test_provider_host_rollout_defaults_low_risk_paths_to_host_preferred(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SASE_PROVIDER_HOST_MODE", raising=False)
    monkeypatch.delenv("SASE_DISABLE_PROVIDER_HOST_ROUTING", raising=False)
    monkeypatch.delenv("SASE_PROVIDER_HOST_QUERIES", raising=False)

    assert host_routing_mode("llm.metadata") == "host-preferred"
    assert host_routing_mode("vcs.query") == "host-preferred"
    assert host_routing_mode("llm.invoke") == "direct"
    assert provider_host_queries_enabled() is True


def test_provider_host_direct_mode_is_one_env_rollback(monkeypatch) -> None:
    monkeypatch.setenv("SASE_PROVIDER_HOST_MODE", "direct")

    assert host_routing_mode("llm.metadata") == "direct"
    assert provider_host_queries_enabled() is False


def test_llm_metadata_shadow_mode_returns_direct_and_records_comparison(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SASE_PROVIDER_HOST_LLM_METADATA_MODE", "shadow")
    direct = registry.direct_llm_metadata_payload()
    monkeypatch.setattr(
        registry,
        "call_provider_host",
        lambda **_: _ok_response({"schema_version": 1, "provider_names": ["other"]}),
    )

    assert registry.llm_metadata_payload() == direct
    recent = host_routing_diagnostics()["shadow_recent"]
    assert recent[-1] == {
        "operation": "llm.metadata",
        "matched": False,
        "reason": "mismatch",
    }


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


def test_provider_host_discovery_reports_rollout_diagnostics() -> None:
    request = _host_request_payload(
        family="config",
        operation="host.discover_plugins",
        payload={},
        required_capability=HOST_CAP_LLM_METADATA,
    )
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())

    response = runtime.handle_json_frame(json.dumps(request))

    assert response.status == "ok"
    routing = response.result["routing"]
    assert routing == host_routing_diagnostics()
    assert routing["operation_modes"]["llm.metadata"] == "host-preferred"


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


def test_llm_invoke_host_operation_uses_direct_provider(monkeypatch) -> None:
    class FakeProvider:
        def invoke(self, prompt: str, **kwargs: object) -> InvokeResult:
            assert prompt == "hello"
            assert kwargs["model_tier"] == "small"
            assert kwargs["model_override"] == "test-model"
            return InvokeResult(
                content="hosted response",
                usage={"input_tokens": 3, "output_tokens": 5},
            )

    monkeypatch.setattr(registry, "get_default_provider_name", lambda: "fake")
    monkeypatch.setattr(registry, "get_provider", lambda _name=None: FakeProvider())
    request = _host_request_payload(
        family="llm",
        operation="llm.invoke",
        payload={
            "prompt": "hello",
            "model_tier": "small",
            "model_override": "test-model",
            "suppress_output": True,
            "provider_name": None,
        },
        required_capability=HOST_CAP_LLM_INVOKE,
    )
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())

    response = runtime.handle_json_frame(json.dumps(request))

    assert response.status == "ok"
    assert response.result["content"] == "hosted response"
    assert response.result["usage"] == {"input_tokens": 3, "output_tokens": 5}
    assert response.result["provider"] == "fake"


def test_workflow_step_host_operations_execute_bash_and_python() -> None:
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())
    bash_request = _host_request_payload(
        family="workflow.step",
        operation="workflow.step.bash",
        payload={"command": "printf 'answer=42\\n'", "cwd": "."},
        required_capability=HOST_CAP_WORKFLOW_STEP,
    )
    python_request = _host_request_payload(
        family="workflow.step",
        operation="workflow.step.python",
        payload={"code": "print('kind=python')", "cwd": "."},
        required_capability=HOST_CAP_WORKFLOW_STEP,
    )

    bash_response = runtime.handle_json_frame(json.dumps(bash_request))
    python_response = runtime.handle_json_frame(json.dumps(python_request))

    assert bash_response.status == "ok"
    assert bash_response.result["returncode"] == 0
    assert bash_response.result["stdout"] == "answer=42\n"
    assert python_response.status == "ok"
    assert python_response.result["returncode"] == 0
    assert python_response.result["stdout"] == "kind=python\n"
