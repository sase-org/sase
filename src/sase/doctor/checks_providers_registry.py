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


def check_llm_shipped_model_policy() -> DiagnosticCheck:
    """Validate the bundled size-alias policy from ``models.yml``."""
    from sase.llm_provider import model_manifest
    from sase.llm_provider.model_policy import (
        PolicyViolation,
        format_policy_violations,
        validate_manifest_policy,
    )

    try:
        manifest = model_manifest.get_model_manifest()
    except Exception as exc:  # noqa: BLE001 - doctor converts load failures.
        return DiagnosticCheck(
            id="llm.model_policy",
            group="llm",
            status="ERROR",
            title="Shipped model policy",
            summary="bundled model manifest could not be loaded",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=(
                "Reinstall SASE or restore src/sase/llm_provider/models.yml, "
                "then rerun `sase doctor -C llm.model_policy`.",
            ),
            data={"error": f"{type(exc).__name__}: {exc}"},
        )

    violations: tuple[PolicyViolation, ...] = validate_manifest_policy(manifest)
    if violations:
        return DiagnosticCheck(
            id="llm.model_policy",
            group="llm",
            status="WARN",
            title="Shipped model policy",
            summary=(
                f"{len(violations)} bundled size-alias policies are violated"
                if len(violations) != 1
                else "1 bundled size-alias policy is violated"
            ),
            details=tuple(format_policy_violations(violations).splitlines()),
            next_steps=(
                "Fix src/sase/llm_provider/models.yml, run `just fix` to "
                "regenerate docs/llms.md, then rerun "
                "`sase doctor -C llm.model_policy`.",
            ),
            data={"violation_count": len(violations)},
        )

    return DiagnosticCheck(
        id="llm.model_policy",
        group="llm",
        status="OK",
        title="Shipped model policy",
        summary="bundled size-alias policy is valid",
        data={
            "provider_count": len(manifest.providers),
            "violation_count": 0,
        },
    )
