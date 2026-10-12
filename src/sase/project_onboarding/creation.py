"""Create-mode repository references and strict provider-option validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from sase import workspace_provider
from sase.core.project_onboarding_facade import evaluate_repo_creation_form
from sase.project_onboarding.refs import UserRefError, parse_user_ref
from sase.workspace_provider._hookspec import ParsedRepoRef, RepoCreationForm

_CREATE_REF_HELP = "gh:OWNER/NAME, OWNER/NAME, or git:NAME"


def parse_create_ref(text: str) -> ParsedRepoRef:
    """Parse a create-mode repository reference.

    Create accepts ``gh:OWNER/NAME``, GitHub shorthand ``OWNER/NAME``, or
    ``git:NAME``. Paths, URLs, and SSH spellings are refused so the command
    cannot be pointed at an existing clone by accident.
    """

    raw = text.strip()
    if not raw:
        raise UserRefError(
            f"not recognized as a create reference: {text!r} (expected {_CREATE_REF_HELP})"
        )
    lowered = raw.casefold()
    if lowered.startswith("git:"):
        name = raw[4:]
        if _looks_like_path(name) or "/" in name or "\\" in name:
            raise UserRefError(
                f"create accepts git:NAME, not a path: {raw!r} (expected {_CREATE_REF_HELP})"
            )
        return parse_user_ref(raw, workflow_type="git")
    if lowered.startswith("gh:"):
        rest = raw[3:]
        if "/" not in rest or _looks_like_path(rest) or "://" in rest:
            raise UserRefError(
                f"create expects gh:OWNER/NAME: {raw!r} (expected {_CREATE_REF_HELP})"
            )
        return parse_user_ref(raw, workflow_type="gh")
    if _looks_like_path(raw) or "://" in raw or raw.startswith("git@"):
        raise UserRefError(
            f"create accepts {_CREATE_REF_HELP}, not a path or URL: {raw!r}"
        )
    if "/" in raw:
        return parse_user_ref(raw, workflow_type="gh")
    raise UserRefError(
        f"not recognized as a create reference: {raw!r} (expected {_CREATE_REF_HELP})"
    )


def parse_option_item(value: str) -> tuple[str, str]:
    """Split one ``KEY=VALUE`` create option. Empty keys are rejected."""

    if "=" not in value:
        raise ValueError(f"create option must be KEY=VALUE, got {value!r}")
    key, _, raw = value.partition("=")
    name = key.strip()
    if not name:
        raise ValueError(f"create option is missing a key: {value!r}")
    return name, raw


def _form_to_wire(form: RepoCreationForm) -> dict[str, Any]:
    """Return the core ``evaluate_repo_creation_form`` wire shape for *form*."""

    return asdict(form)


def evaluate_creation_options(
    workflow_type: str,
    namespace: str,
    values: Mapping[str, str],
) -> dict[str, Any]:
    """Fetch the provider form and evaluate *values* in strict mode.

    A missing form is reported as a single ``unknown_option`` error so the
    planner can block before ``ws_create_repo``. Successful evaluations always
    include ``effective_options`` so create always passes an explicit
    visibility.
    """

    payload: dict[str, Any] = {
        "can_create": None,
        "errors": [],
        "fields": [],
        "effective_options": {},
        "valid": False,
        "form": None,
    }
    if not workflow_type:
        payload["errors"] = [
            {
                "field": "",
                "code": "unknown_option",
                "message": "cannot create a repository without a workspace provider",
            }
        ]
        return payload
    try:
        form = workspace_provider.describe_repo_creation(workflow_type, namespace)
    except Exception as exc:
        payload["errors"] = [
            {
                "field": "",
                "code": "unknown_option",
                "message": f"could not load the provider creation form: {exc}",
            }
        ]
        return payload
    if form is None:
        payload["errors"] = [
            {
                "field": "",
                "code": "unknown_option",
                "message": (
                    f"provider {workflow_type!r} does not support repository creation"
                ),
            }
        ]
        return payload
    payload["form"] = form
    payload["can_create"] = form.can_create
    evaluation = evaluate_repo_creation_form(
        _form_to_wire(form),
        {str(key): str(value) for key, value in dict(values).items()},
        "strict",
    )
    payload["errors"] = [
        {
            "field": str(item.get("field") or ""),
            "code": str(item.get("code") or ""),
            "message": str(item.get("message") or ""),
        }
        for item in list(evaluation.get("errors") or [])
        if isinstance(item, Mapping)
    ]
    payload["fields"] = _fields_with_defaults(
        list(evaluation.get("fields") or []), form
    )
    if not payload["fields"]:
        payload["fields"] = [
            {
                "name": item.name,
                "label": item.label,
                "default": item.default,
                "value": dict(values).get(item.name, item.default),
                "available": not item.disabled_reason,
                "reason": item.disabled_reason,
            }
            for item in form.fields
        ]
    effective = evaluation.get("effective_options")
    payload["effective_options"] = (
        {str(key): str(value) for key, value in dict(effective).items()}
        if isinstance(effective, Mapping)
        else {}
    )
    payload["valid"] = bool(evaluation.get("valid"))
    return payload


def _fields_with_defaults(
    fields: list[Any], form: RepoCreationForm
) -> list[dict[str, Any]]:
    specs = {item.name: item for item in form.fields}
    enriched: list[dict[str, Any]] = []
    for raw in fields:
        if not isinstance(raw, Mapping):
            continue
        field = dict(raw)
        spec = specs.get(str(field.get("name") or ""))
        if spec is not None:
            field.setdefault("default", spec.default)
            field.setdefault("label", spec.label)
        enriched.append(field)
    return enriched


def _looks_like_path(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith(("/", "~", ".", "\\"))


__all__ = [
    "evaluate_creation_options",
    "parse_create_ref",
    "parse_option_item",
]
