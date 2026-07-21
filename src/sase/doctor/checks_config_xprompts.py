"""XPrompt configuration checks for ``sase doctor``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import (
    MAX_DETAIL_ROWS,
    REMOVED_IMPLICIT_ALIAS_GUIDANCE,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


@dataclass(frozen=True)
class _ModelPresetScan:
    tokens: tuple[str, ...] = ()
    override_tokens: tuple[tuple[str, str], ...] = ()
    errors: tuple[str, ...] = ()


def check_config_model_xprompts(context: DoctorContext) -> DiagnosticCheck:
    """Warn when a model-preset xprompt expands to an unroutable model token.

    Configured ``%model``/``%m`` presets (e.g. ``#m_agy_flash`` expands to
    ``%model:@#agy_flash``) resolve their final model token to a provider at
    launch time. When that token is a bare name that is neither a configured
    model alias entry, an explicit ``provider/model`` target, nor a model a
    registered provider plugin knows, the launch silently falls back to the
    default provider instead of the intended one.

    This read-only guard surfaces that drift, for example a removed
    ``agy_flash`` alias quietly rerouting every ``#agy_*``/``#m_agy_*`` preset to
    the default provider. It is provider-neutral, so it also catches
    ``#m_fable``, ``#m_qwen``, or plugin-provided presets whose tokens stop
    resolving.
    """
    from sase.llm_provider.config import model_alias_names
    from sase.xprompt.loader import get_all_xprompts

    aliases = model_alias_names()
    xprompts = get_all_xprompts(context.project)

    problems: list[dict[str, str]] = []
    scanned = 0
    for name in sorted(xprompts):
        scan = _model_preset_tokens(xprompts[name].content)
        if scan is None:
            continue
        scanned += 1
        for error in scan.errors:
            problems.append(
                {
                    "xprompt": name,
                    "token": "",
                    "message": f"{name}: {error}",
                }
            )
        for token in scan.tokens:
            if token not in aliases and token in REMOVED_IMPLICIT_ALIAS_GUIDANCE:
                guidance = REMOVED_IMPLICIT_ALIAS_GUIDANCE[token]
                problems.append(
                    {
                        "xprompt": name,
                        "token": token,
                        "message": (
                            f"{name} -> %model:@{token} uses the retired "
                            f"'@{token}' alias; {guidance}"
                        ),
                    }
                )
                continue
            if _model_token_routes(token, aliases):
                continue
            problems.append(
                {
                    "xprompt": name,
                    "token": token,
                    "message": (
                        f"{name} -> {token} does not resolve to a provider; "
                        "it will fall back to the default provider"
                    ),
                }
            )
        for alias, token in scan.override_tokens:
            if _model_token_routes(token, aliases):
                continue
            problems.append(
                {
                    "xprompt": name,
                    "token": token,
                    "message": (
                        f"{name} -> %model({alias}={token}) does not resolve "
                        "to a provider; the family override will fall back to "
                        "the default provider"
                    ),
                }
            )

    status: CheckStatus = "WARN" if problems else "OK"
    details = tuple(row["message"] for row in problems[:MAX_DETAIL_ROWS])
    summary = (
        f"{scanned} model preset xprompt(s) route to a provider"
        if not problems
        else f"{len(problems)} model preset token(s) fall back to the default provider"
    )
    next_steps = (
        (
            "Add the unresolved token(s) to `llm_provider.model_aliases.custom`, "
            "or point the xprompt at an explicit `provider/model` target, then "
            "rerun `sase doctor -C config.model_xprompts`.",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.model_xprompts",
        group="config",
        status=status,
        title="Model xprompt routing",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={"scanned": scanned, "problems": problems},
    )


def check_config_xprompt_definitions(context: DoctorContext) -> DiagnosticCheck:
    """Surface non-fatal xprompt/workflow definition load issues."""
    from sase.xprompt.load_issues import XPromptLoadIssue, collect_xprompt_load_issues
    from sase.xprompt.loader import get_all_project_local_prompts, get_all_prompts

    with collect_xprompt_load_issues() as issues:
        prompts = get_all_prompts(context.project)
        project_local_prompts = get_all_project_local_prompts()

    issue_rows: list[XPromptLoadIssue] = list(issues)
    rows = [
        {
            "source": issue.source,
            "error": issue.error,
            "kind": issue.kind,
        }
        for issue in issue_rows
    ]
    if not rows:
        loaded = len(prompts) + len(project_local_prompts)
        return DiagnosticCheck(
            id="config.xprompt_definitions",
            group="config",
            status="OK",
            title="XPrompt definitions",
            summary=f"{loaded} xprompt/workflow definition(s) loaded cleanly",
            data={"loaded_count": loaded, "issues": []},
        )

    details = tuple(
        f"skipped: {row['source']}: {row['error']}" for row in rows[:MAX_DETAIL_ROWS]
    )
    return DiagnosticCheck(
        id="config.xprompt_definitions",
        group="config",
        status="WARN",
        title="XPrompt definitions",
        summary=f"{len(rows)} xprompt definition file(s) skipped or degraded",
        details=details,
        next_steps=(
            "Fix the reported xprompt/workflow definition files, then rerun "
            "`sase doctor -C config.xprompt_definitions`.",
        ),
        data={
            "loaded_count": len(prompts) + len(project_local_prompts),
            "issues": rows,
        },
    )


def _model_preset_tokens(content: str) -> _ModelPresetScan | None:
    """Return the final model token(s) a model-preset xprompt expands to.

    Returns ``None`` when *content* does not expand into any ``%model``/``%m``
    directive (so it is not a model preset) or cannot be parsed as a clean
    single/fan-out model directive. Multi-segment prompts carrying several
    explicit ``%model`` directives are split by the launcher, not here, so they
    are skipped rather than reported.
    """
    from sase.xprompt.directives import (
        DirectiveError,
        extract_prompt_directives,
        has_model_directive,
        split_prompt_for_models,
    )
    from sase.xprompt.models import XPrompt
    from sase.xprompt.processor import process_xprompt_references
    from sase.xprompt.segment_separators import xprompt_has_segment_separators

    try:
        expanded = process_xprompt_references(content)
    except Exception:  # noqa: BLE001 - a malformed preset must not break doctor.
        return None

    if xprompt_has_segment_separators(XPrompt(name="_doctor_scan", content=expanded)):
        return None

    if not has_model_directive(expanded):
        return None

    try:
        branches = split_prompt_for_models(expanded)
        sources = branches if branches else [expanded]
        tokens: list[str] = []
        override_tokens: list[tuple[str, str]] = []
        for source in sources:
            _, directives = extract_prompt_directives(source)
            if directives.model:
                tokens.append(directives.model)
            override_tokens.extend(directives.model_alias_overrides.items())
    except DirectiveError as exc:
        return _ModelPresetScan(errors=(str(exc),))
    except Exception:  # noqa: BLE001 - a malformed preset must not break doctor.
        return None
    return _ModelPresetScan(
        tokens=tuple(tokens),
        override_tokens=tuple(override_tokens),
    )


def _model_token_routes(token: str, aliases: set[str]) -> bool:
    """Return ``True`` when *token* routes to a concrete provider.

    A token is routable when it resolves to a known provider, is a configured
    alias (whose target provider plugin may simply be uninstalled on this
    machine), or uses explicit ``provider/model`` syntax. Only a bare, unknown
    token that is none of these silently falls back to the default provider.
    """
    from sase.llm_provider.registry import resolve_model_provider

    provider, _ = resolve_model_provider(token)
    if provider is not None:
        return True
    if token.removeprefix("@") in aliases:
        return True
    return "/" in token
