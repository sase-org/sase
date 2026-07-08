"""LLM provider registry checks for ``sase doctor``."""

from __future__ import annotations

from sase.diagnostics import DiagnosticCheck
from sase.doctor.checks_providers import (
    llm_registry,
    metadata_list,
    providers_from_payload,
)


def check_llm_registry() -> DiagnosticCheck:
    """Verify provider plugin metadata can be loaded."""
    try:
        payload = llm_registry.get_llm_metadata_payload()
    except Exception as exc:  # noqa: BLE001 - doctor converts registry failures.
        return DiagnosticCheck(
            id="llm.registry",
            group="llm",
            status="ERROR",
            title="LLM provider registry",
            summary="LLM provider metadata could not be loaded",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=(
                "Reinstall or disable the failing LLM provider plugin, then rerun `sase doctor -C llm.registry`.",
            ),
            data={"error": f"{type(exc).__name__}: {exc}"},
        )

    providers = providers_from_payload(payload)
    provider_names = sorted(providers)
    if not provider_names:
        return DiagnosticCheck(
            id="llm.registry",
            group="llm",
            status="ERROR",
            title="LLM provider registry",
            summary="no LLM providers are registered",
            next_steps=(
                "Install at least one SASE LLM provider plugin in this environment.",
            ),
            data={"provider_count": 0, "providers": []},
        )

    model_count = sum(
        len(metadata_list(metadata.get("known_model_names")))
        for metadata in providers.values()
    )
    autodetect_count = len(metadata_list(payload.get("autodetect_candidates")))
    return DiagnosticCheck(
        id="llm.registry",
        group="llm",
        status="OK",
        title="LLM provider registry",
        summary=(
            f"{len(provider_names)} provider(s), {model_count} known model(s), "
            f"{autodetect_count} autodetect candidate(s)"
        ),
        data={
            "provider_count": len(provider_names),
            "providers": provider_names,
            "model_count": model_count,
            "autodetect_candidates": metadata_list(
                payload.get("autodetect_candidates")
            ),
        },
    )


_check_llm_registry = check_llm_registry
