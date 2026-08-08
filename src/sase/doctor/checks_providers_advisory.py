"""Model-advisory routing checks for ``sase doctor``.

Providers may flag individual models with an advisory (see the
``llm_model_advisories`` hook) — a discounted tier that trains on its inputs, a
preview model with no stability guarantee, and so on. Opting into one of those
globally is the user's call; doing it without noticing is not. This check
reports every resolved route that lands on an advisory-flagged model.
"""

from __future__ import annotations

from typing import Any

from sase.diagnostics import CheckStatus, DiagnosticCheck

_RERUN = "Rerun `sase doctor -C llm.model_advisory -v` after changing the route."


def check_llm_model_advisory() -> DiagnosticCheck:
    """Report configured routes that resolve to an advisory-flagged model."""
    try:
        from sase.llm_provider import registry as llm_registry

        advisories = llm_registry.model_advisory_map()
    except Exception as exc:  # noqa: BLE001 - registry failures are diagnostic.
        return _error_check(exc)

    if not advisories:
        return DiagnosticCheck(
            id="llm.model_advisory",
            group="llm",
            status="OK",
            title="Model advisories",
            summary="no registered provider flags any model with an advisory",
            data={"advisory_models": [], "findings": []},
        )

    try:
        findings = _collect_findings(advisories)
    except Exception as exc:  # noqa: BLE001 - resolution failures are diagnostic.
        return _error_check(exc)

    status: CheckStatus = "WARN" if findings else "OK"
    if findings:
        summary = (
            f"{len(findings)} configured route(s) resolve to an advisory-flagged model"
        )
    else:
        summary = "no configured route resolves to an advisory-flagged model"

    return DiagnosticCheck(
        id="llm.model_advisory",
        group="llm",
        status=status,
        title="Model advisories",
        summary=summary,
        details=tuple(_format_finding(finding) for finding in findings),
        next_steps=(
            (
                "Repoint the reported route(s) at a model without an advisory, "
                "or keep them if the quoted terms are acceptable.",
                _RERUN,
            )
            if findings
            else ()
        ),
        data={
            "advisory_models": sorted(advisories),
            "findings": findings,
        },
    )


def _collect_findings(advisories: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Return one finding per resolved route landing on a flagged model."""
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for source, provider, model in _resolved_routes():
        advisory = advisories.get(model)
        if advisory is None or (source, model) in seen:
            continue
        seen.add((source, model))
        findings.append(
            {
                "source": source,
                "provider": provider,
                "model": model,
                "severity": advisory.get("severity", "info"),
                "label": advisory.get("label", ""),
                "detail": advisory.get("detail", ""),
            }
        )
    return findings


def _resolved_routes() -> list[tuple[str, str, str]]:
    """Return ``(source, provider, model)`` for every route doctor inspects.

    Two families of route can send SASE traffic to a model: a model alias
    (including ``@default``, which is what an unqualified run uses) and the
    default provider's own tier mapping, which is what ``model_tier`` resolves
    to when no alias or ``%model`` names a model explicitly.
    """
    from sase.llm_provider import registry as llm_registry
    from sase.llm_provider.alias_view import build_alias_views

    routes: list[tuple[str, str, str]] = []
    for view in build_alias_views(overrides={}):
        if view.model:
            routes.append((f"@{view.name}", view.provider or "", view.model))

    try:
        provider_name = llm_registry.get_default_provider_name()
    except Exception:  # noqa: BLE001 - `llm.default` owns reporting this.
        return routes

    providers = llm_registry.get_llm_metadata_payload().get("providers")
    metadata = providers.get(provider_name) if isinstance(providers, dict) else None
    if not isinstance(metadata, dict):
        return routes
    resolutions = metadata.get("model_resolutions")
    if not isinstance(resolutions, dict):
        return routes
    for tier in ("large", "small"):
        model = resolutions.get(tier)
        if isinstance(model, str) and model:
            routes.append((f"{provider_name} {tier} tier", provider_name, model))
    return routes


def _format_finding(finding: dict[str, Any]) -> str:
    target = finding["model"]
    if provider := finding.get("provider"):
        target = f"{provider}/{target}"
    detail = finding.get("detail") or finding.get("label") or ""
    return f"{finding['source']} -> {target}: {detail}"


def _error_check(exc: Exception) -> DiagnosticCheck:
    return DiagnosticCheck(
        id="llm.model_advisory",
        group="llm",
        status="ERROR",
        title="Model advisories",
        summary="model advisories could not be resolved",
        details=(f"{type(exc).__name__}: {exc}",),
        next_steps=(
            "Run `sase doctor -C llm.registry` and fix provider registry errors first.",
        ),
        data={"error": f"{type(exc).__name__}: {exc}"},
    )
