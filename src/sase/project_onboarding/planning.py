"""Plan documents over the existing Rust onboarding planner."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase import workspace_provider
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_onboarding_facade import plan_project_onboarding
from sase.project_accents import accent_among_keys, project_accent
from sase.project_onboarding.facts import gather_facts
from sase.project_onboarding.human_only import detect_actor
from sase.project_onboarding.journal import ownership_facts
from sase.project_onboarding.refs import UserRefError, parse_user_ref

_PLAN_DOCUMENT_KIND = "project_onboarding_plan"
_PLAN_SCHEMA_VERSION = 1
_PLANNER_FACT_KEYS = (
    "remote",
    "checkout",
    "local_managed",
    "record",
    "projects",
    "creation_errors",
    "can_create",
)
_CHECKOUT_FACT_KEYS = ("state", "origin_url", "config_dirty", "on_default_branch")


def build_plan_document(
    request: Mapping[str, Any],
    *,
    facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a versioned plan document from *request* and observed facts.

    Omitted facts are gathered. A supplied observation supports local-only
    TUI previews. The Rust planner owns identity, setup, steps, and the
    intent fingerprint; this function only assembles the document envelope.
    """

    prepared = _prepare_request(request)
    observed = (
        dict(facts)
        if facts is not None
        else gather_facts(
            prepared["target"],
            str(prepared.get("mode") or "add"),
            actor=str(prepared.get("actor") or "human"),
        )
    )
    planner_facts = _planner_facts(observed)
    first = plan_project_onboarding(prepared, planner_facts)
    fingerprint = str(first.get("intent_fingerprint") or "")
    identity_key = str(prepared["target"].get("identity_key") or "")
    observed_checkout = observed.get("checkout")
    checkout_facts = observed_checkout if isinstance(observed_checkout, Mapping) else {}
    matched = ownership_facts(
        identity_key,
        fingerprint,
        current_config_hash=str(checkout_facts.get("config_hash") or ""),
    )
    if matched is not None:
        planner_facts = {**planner_facts, "journal": matched}
        plan = plan_project_onboarding(prepared, planner_facts)
    else:
        plan = first
    return _document(prepared, observed, plan)


def _prepare_request(request: Mapping[str, Any]) -> dict[str, Any]:
    prepared = {
        "mode": str(request.get("mode") or "add"),
        "actor": str(request.get("actor") or detect_actor()),
        "target": _canonical_target(request.get("target") or {}),
        "requested": _requested(request.get("requested") or {}),
    }
    creation = request.get("creation")
    if isinstance(creation, Mapping):
        prepared["creation"] = {
            "visibility": str(creation.get("visibility") or ""),
            "summary": [str(item) for item in list(creation.get("summary") or ())],
        }
    return prepared


def _canonical_target(target: Mapping[str, Any]) -> dict[str, Any]:
    workflow_type = str(target.get("workflow_type") or "")
    raw_ref = str(target.get("ref") or "")
    parsed_ref = raw_ref
    parsed_fields: dict[str, Any] = {}
    if raw_ref:
        try:
            parsed = parse_user_ref(raw_ref, workflow_type=workflow_type or None)
        except UserRefError:
            parsed = None
        if parsed is not None:
            parsed_ref = parsed.ref
            parsed_fields = {
                "workflow_type": parsed.workflow_type,
                "identity_key": parsed.identity_key,
                "display": parsed.display,
                "host": parsed.host,
                "owner": parsed.owner,
                "name": parsed.name,
                "web_url": parsed.web_url,
                "checkout_dir": parsed.checkout_dir,
                "project_key_base": parsed.project_key_base,
                "project_name_base": parsed.project_name_base,
            }
            if not workflow_type:
                workflow_type = parsed.workflow_type
    canonical = {
        "workflow_type": workflow_type or str(parsed_fields.get("workflow_type") or ""),
        "provider_display": str(target.get("provider_display") or ""),
        "identity_key": str(
            target.get("identity_key") or parsed_fields.get("identity_key") or ""
        ),
        "ref": parsed_ref,
        "display": str(
            target.get("display") or parsed_fields.get("display") or parsed_ref
        ),
        "host": str(target.get("host") or parsed_fields.get("host") or ""),
        "owner": str(target.get("owner") or parsed_fields.get("owner") or ""),
        "name": str(target.get("name") or parsed_fields.get("name") or ""),
        "web_url": str(target.get("web_url") or parsed_fields.get("web_url") or ""),
        "checkout_dir": str(
            target.get("checkout_dir") or parsed_fields.get("checkout_dir") or ""
        ),
        "project_key_base": str(
            target.get("project_key_base")
            or parsed_fields.get("project_key_base")
            or ""
        ),
        "project_name_base": str(
            target.get("project_name_base")
            or parsed_fields.get("project_name_base")
            or ""
        ),
        "storage_policy": str(
            target.get("storage_policy") or _storage_policy(workflow_type)
        ),
    }
    if not canonical["provider_display"]:
        canonical["provider_display"] = _provider_display(canonical["workflow_type"])
    return canonical


def _requested(requested: Mapping[str, Any]) -> dict[str, Any]:
    setup = str(requested.get("setup") or "auto")
    if setup not in {"auto", "on", "off"}:
        setup = "auto"
    aliases = requested.get("aliases") or []
    return {
        "name": str(requested.get("name") or ""),
        "aliases": [str(alias) for alias in aliases],
        "setup": setup,
        "make_current": bool(requested.get("make_current")),
    }


def _planner_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in _PLANNER_FACT_KEYS:
        if key not in facts:
            continue
        value = facts[key]
        if key == "remote" and isinstance(value, Mapping):
            payload[key] = {
                name: value[name]
                for name in (
                    "status",
                    "visibility",
                    "is_empty",
                    "is_archived",
                    "can_push",
                    "sase_managed",
                    "repo_id",
                    "default_branch",
                    "message",
                )
                if name in value
            }
        elif key == "checkout" and isinstance(value, Mapping):
            payload[key] = {
                name: value[name] for name in _CHECKOUT_FACT_KEYS if name in value
            }
        else:
            payload[key] = value
    return payload


def _document(
    request: Mapping[str, Any],
    facts: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    target = request["target"]
    raw_remote = facts.get("remote")
    remote: Mapping[str, Any] = raw_remote if isinstance(raw_remote, Mapping) else {}
    raw_identity = plan.get("identity")
    identity: Mapping[str, Any] = (
        raw_identity if isinstance(raw_identity, Mapping) else {}
    )
    steps = list(plan.get("steps") or [])
    key = str(identity.get("key") or target.get("project_key_base") or "")
    raw_record = facts.get("record")
    record: Mapping[str, Any] | None = (
        raw_record if isinstance(raw_record, Mapping) else None
    )
    return {
        "schema_version": _PLAN_SCHEMA_VERSION,
        "kind": _PLAN_DOCUMENT_KIND,
        "mode": str(plan.get("mode") or request.get("mode") or "add"),
        "status": str(plan.get("status") or ""),
        "intent_fingerprint": str(plan.get("intent_fingerprint") or ""),
        "provider": {
            "workflow_type": str(target.get("workflow_type") or ""),
            "display": str(target.get("provider_display") or ""),
        },
        "target": {
            "ref": str(target.get("ref") or ""),
            "display": str(target.get("display") or target.get("ref") or ""),
            "identity_key": str(target.get("identity_key") or ""),
            "web_url": str(remote.get("web_url") or target.get("web_url") or ""),
            "visibility": str(remote.get("visibility") or ""),
            "default_branch": str(remote.get("default_branch") or ""),
            "checkout_dir": str(target.get("checkout_dir") or ""),
            "can_push": remote.get("can_push"),
            "sase_managed": remote.get("sase_managed"),
        },
        "project": {
            "key": key,
            "name": str(identity.get("name") or ""),
            "aliases": list(identity.get("aliases") or []),
            "accent": _accent_for(key),
            "state": str((record or {}).get("state") or "enabled"),
            "existing": record is not None,
        },
        "setup": dict(plan.get("setup") or {}),
        "steps": steps,
        "warnings": list(plan.get("warnings") or []),
        "blockers": list(plan.get("blockers") or []),
        "apply_argv": _apply_argv(request),
        "next_argv": _next_argv(steps, key),
    }


def _apply_argv(request: Mapping[str, Any]) -> list[str]:
    mode = str(request.get("mode") or "add")
    target = request.get("target") or {}
    argv = ["sase", "project", mode, str(target.get("ref") or "")]
    requested = request.get("requested") or {}
    for alias in list(requested.get("aliases") or []):
        argv.extend(["--alias", str(alias)])
    if requested.get("make_current"):
        argv.append("--make-current")
    name = str(requested.get("name") or "")
    if name:
        argv.extend(["--name", name])
    setup = str(requested.get("setup") or "auto")
    if setup == "on":
        argv.append("--setup")
    elif setup == "off":
        argv.append("--no-setup")
    creation = request.get("creation")
    if mode == "create" and isinstance(creation, Mapping):
        visibility = str(creation.get("visibility") or "")
        if visibility:
            argv.extend(["--visibility", visibility])
    argv.extend(["--yes", "--json"])
    return argv


def _next_argv(steps: list[Any], key: str) -> list[str]:
    pending_init = any(
        isinstance(step, Mapping)
        and step.get("id") == "init"
        and step.get("state") == "pending"
        for step in steps
    )
    if pending_init and key:
        return ["sase", "init", "-p", key]
    return []


def _accent_for(project_key: str) -> str:
    if not project_key:
        return ""
    try:
        records = list_project_records(sase_projects_dir(), "all")
    except Exception:
        records = []
    among = accent_among_keys(records)
    return project_accent(project_key, among=among)


def _provider_display(workflow_type: str) -> str:
    if not workflow_type:
        return ""
    try:
        display = workspace_provider.get_display_name(workflow_type)
    except Exception:
        display = None
    return str(display or workflow_type)


def _storage_policy(workflow_type: str) -> str:
    if not workflow_type:
        return ""
    try:
        metadata = workspace_provider.get_all_workflow_metadata()
    except Exception:
        return ""
    for item in metadata:
        if item.workflow_type == workflow_type and item.sdd_storage_policy:
            return item.sdd_storage_policy
    return ""


__all__ = ["build_plan_document"]
