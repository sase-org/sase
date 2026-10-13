"""Textual-free Review-stage models for the New Project wizard.

These helpers turn one onboarding plan document into review rows, warnings,
blockers, the argv line, and the confirm verdict, plus the durable
``project.add`` / ``project.create`` submission the apply phase later
submits. They import no Textual modules.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from sase.project_onboarding.creation import create_apply_ref

from .init_plan_modal_rendering import operation_glyph

__all__ = [
    "ApplySubmission",
    "ReviewView",
    "apply_submission",
    "build_review",
    "options_from_argv",
    "requested_from_argv",
    "strip_transport_flags",
]

_VALUE_FLAGS = {
    "--alias",
    "--description",
    "--name",
    "--option",
    "--request-path",
    "--result-path",
    "--visibility",
    "-O",
    "-a",
    "-d",
    "-n",
    "-v",
}
_TRANSPORT_FLAGS = frozenset({"--check", "--json", "--yes"})
_TRANSPORT_VALUE_FLAGS = frozenset({"--request-path", "--result-path"})
_PUBLIC_STYLE = "#FFAF5F"


@dataclass(frozen=True, slots=True)
class _ReviewRow:
    """One review line derived from a plan step."""

    glyph: str
    style: str
    label: str
    detail: str


@dataclass(frozen=True, slots=True)
class _ReviewBlocker:
    """One plan blocker with its follow-up hint."""

    message: str
    hint: str


@dataclass(frozen=True, slots=True)
class ReviewView:
    """Render-ready Review stage content for one plan document."""

    rows: tuple[_ReviewRow, ...]
    warnings: tuple[str, ...]
    blockers: tuple[_ReviewBlocker, ...]
    argv: tuple[str, ...]
    argv_line: str
    can_confirm: bool
    is_public: bool
    mode: str = "add"
    heading: str = "ADD PLAN"
    confirm_label: str = "Add project  [y]"
    notice: str = "Review the steps before adding this project."
    keep_notice: str = ""
    is_danger: bool = False
    visibility: str = ""
    repo_name: str = ""
    host: str = ""
    public_style: str = _PUBLIC_STYLE


@dataclass(frozen=True, slots=True)
class ApplySubmission:
    """Durable ``project.add`` or ``project.create`` submission."""

    argv: tuple[str, ...]
    operation: str
    request_fingerprint: str
    concurrency_keys: tuple[str, ...]
    request: dict[str, Any]
    project_key: str = ""


def _steps(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = document.get("steps")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _iter_flag_tokens(argv: Sequence[str]) -> list[tuple[str, str | None]]:
    """Walk *argv* as flag/value pairs so option values stay data."""
    tokens: list[tuple[str, str | None]] = []
    pending: str | None = None
    for token in argv:
        if pending is not None:
            tokens.append((pending, token))
            pending = None
            continue
        if token in _VALUE_FLAGS:
            pending = token
            continue
        tokens.append((token, None))
    if pending is not None:
        tokens.append((pending, None))
    return tokens


def strip_transport_flags(argv: Sequence[str]) -> list[str]:
    """Drop proc transport/result flags without touching option values.

    ``--yes``, ``--json``, ``--check``, and ``--request-path`` /
    ``--result-path`` pairs are structural. A value equal to those
    spellings (``--description --yes``, ``--option foo=--json``) is data.
    """
    stripped: list[str] = []
    for flag, value in _iter_flag_tokens(argv):
        if flag in _TRANSPORT_FLAGS:
            continue
        if flag in _TRANSPORT_VALUE_FLAGS:
            continue
        stripped.append(flag)
        if value is not None:
            stripped.append(value)
    return stripped


def requested_from_argv(argv: Sequence[str]) -> dict[str, Any]:
    """Recover the ``requested`` intent encoded in a plan ``apply_argv``."""
    name = ""
    aliases: list[str] = []
    setup = "auto"
    make_current = False
    for flag, value in _iter_flag_tokens(argv):
        if flag in {"--name", "-n"} and value is not None:
            name = value
        elif flag in {"--alias", "-a"} and value is not None:
            aliases.append(value)
        elif flag == "--setup":
            setup = "on"
        elif flag in {"--no-setup", "-S"}:
            setup = "off"
        elif flag in {"--make-current", "-m"}:
            make_current = True
    return {
        "name": name,
        "aliases": aliases,
        "setup": setup,
        "make_current": make_current,
    }


def options_from_argv(argv: Sequence[str]) -> dict[str, str]:
    """Reconstruct create ``options`` from argv the way the CLI parser does.

    ``--option`` / ``-O`` pairs land first; ``--description`` and
    ``--visibility`` sugar overlay them. Values equal to transport flag
    spellings remain option data.
    """
    options: dict[str, str] = {}
    for flag, value in _iter_flag_tokens(argv):
        if flag in {"--option", "-O"} and value is not None:
            key, separator, item = value.partition("=")
            if separator:
                options[key] = item
        elif flag in {"--description", "-d"} and value is not None:
            options["description"] = value
        elif flag in {"--visibility", "-v"} and value is not None:
            options["visibility"] = value
    return options


def _host_from_target(target: Mapping[str, Any]) -> str:
    host = str(target.get("host") or "")
    if host:
        return host
    web_url = str(target.get("web_url") or "")
    if web_url:
        return str(urlparse(web_url).netloc or "")
    return ""


def _requested_visibility(
    document: Mapping[str, Any], target: Mapping[str, Any]
) -> str:
    fields = document.get("creation_fields")
    if isinstance(fields, list) and not any(
        isinstance(field, Mapping) and str(field.get("name") or "") == "visibility"
        for field in fields
    ):
        return ""
    creation = _mapping(document.get("creation"))
    visibility = str(creation.get("visibility") or "")
    if visibility:
        return visibility
    return str(target.get("visibility") or "")


def build_review(document: Mapping[str, Any]) -> ReviewView:
    """Turn one plan document into review rows and the confirm verdict."""
    target_map = _mapping(document.get("target"))
    creation = _mapping(document.get("creation"))
    mode = str(document.get("mode") or "add")
    is_create = mode == "create"
    visibility = _requested_visibility(document, target_map)
    repo_name = str(target_map.get("display") or target_map.get("ref") or "")
    host = _host_from_target(target_map)
    rows: list[_ReviewRow] = []
    if is_create:
        vis_label = visibility.upper() if visibility else ""
        web_url = str(target_map.get("web_url") or "")
        detail_parts = [part for part in (host, vis_label, web_url) if part]
        glyph, style = operation_glyph("create")
        rows.append(
            _ReviewRow(
                glyph=glyph,
                style=style,
                label="REMOTE",
                detail=" ".join(detail_parts),
            )
        )
        for line in list(creation.get("summary") or ()):
            text = str(line)
            if text:
                rows.append(
                    _ReviewRow(glyph=glyph, style=style, label="CREATE", detail=text)
                )
    for step in _steps(document):
        if str(step.get("state") or "") == "skipped":
            continue
        glyph, style = operation_glyph(str(step.get("operation") or ""))
        rows.append(
            _ReviewRow(
                glyph=glyph,
                style=style,
                label=str(step.get("label") or step.get("id") or "step"),
                detail=str(step.get("detail") or ""),
            )
        )
    raw_warnings = document.get("warnings")
    warnings = tuple(
        str(item.get("message") or "")
        for item in (list(raw_warnings) if isinstance(raw_warnings, list) else [])
        if isinstance(item, Mapping) and str(item.get("message") or "")
    )
    raw_blockers = document.get("blockers")
    blockers = tuple(
        _ReviewBlocker(
            message=str(item.get("message") or ""),
            hint=str(item.get("hint") or ""),
        )
        for item in (list(raw_blockers) if isinstance(raw_blockers, list) else [])
        if isinstance(item, Mapping) and str(item.get("message") or "")
    )
    raw_argv = document.get("apply_argv")
    argv = tuple(str(item) for item in raw_argv) if isinstance(raw_argv, list) else ()
    blocked = str(document.get("status") or "") == "blocked" or bool(blockers)
    vis_label = visibility.upper() if visibility else "—"
    if is_create:
        heading = f"CREATE {vis_label} {repo_name}".strip()
        if not visibility:
            heading = f"CREATE {repo_name}".strip()
        confirm_label = "Create repository  [y]"
        host_label = host or "the remote"
        notice = f"Creates a repository on {host_label}."
        keep_notice = "Later failure keeps the created repository; retry resumes setup."
    else:
        heading = "ADD PLAN"
        confirm_label = "Add project  [y]"
        notice = "Review the steps before adding this project."
        keep_notice = ""
    return ReviewView(
        rows=tuple(rows),
        warnings=warnings,
        blockers=blockers,
        argv=argv,
        argv_line=shlex.join(argv),
        can_confirm=not blocked,
        is_public=visibility.casefold() == "public",
        mode=mode,
        heading=heading,
        confirm_label=confirm_label,
        notice=notice,
        keep_notice=keep_notice,
        is_danger=is_create,
        visibility=visibility,
        repo_name=repo_name,
        host=host,
    )


def apply_submission(document: Mapping[str, Any]) -> ApplySubmission:
    """Build the durable add or create submission for *document*.

    ``argv`` is the document's ``apply_argv`` unchanged. The request object
    carries exactly what the CLI compares (mode, actor, target, requested,
    and for create the reconstructed ``options``).
    """
    raw_argv = document.get("apply_argv")
    argv = tuple(str(item) for item in raw_argv) if isinstance(raw_argv, list) else ()
    target_map = _mapping(document.get("target"))
    provider_map = _mapping(document.get("provider"))
    creation = _mapping(document.get("creation"))
    identity_key = str(target_map.get("identity_key") or "")
    checkout_dir = str(target_map.get("checkout_dir") or "")
    mode = str(document.get("mode") or "add")
    operation = "project.create" if mode == "create" else "project.add"
    target_request: dict[str, Any] = {
        "ref": str(target_map.get("ref") or ""),
        "workflow_type": str(provider_map.get("workflow_type") or ""),
        "identity_key": identity_key,
    }
    if mode == "create":
        target_request["ref"] = create_apply_ref(
            target_request["workflow_type"], target_request["ref"]
        )
    owner = str(target_map.get("owner") or "")
    if owner:
        target_request["owner"] = owner
    request: dict[str, Any] = {
        "mode": mode,
        "actor": "human",
        "target": target_request,
        "requested": requested_from_argv(argv),
    }
    if mode == "create":
        options = options_from_argv(argv)
        creation_fields = document.get("creation_fields")
        visibility_supported = not isinstance(creation_fields, list) or any(
            isinstance(field, Mapping) and str(field.get("name") or "") == "visibility"
            for field in creation_fields
        )
        if not visibility_supported:
            options.pop("visibility", None)
        request["options"] = options
        visibility = str(options.get("visibility") or creation.get("visibility") or "")
        creation_request: dict[str, Any] = {
            "summary": [str(item) for item in list(creation.get("summary") or ())]
        }
        if visibility and visibility_supported:
            creation_request["visibility"] = visibility
        request["creation"] = creation_request
    return ApplySubmission(
        argv=argv,
        operation=operation,
        request_fingerprint=str(document.get("intent_fingerprint") or ""),
        concurrency_keys=(
            f"project-onboard:{identity_key}",
            f"checkout:{checkout_dir}",
        ),
        request=request,
        project_key=str(_mapping(document.get("project")).get("key") or ""),
    )
