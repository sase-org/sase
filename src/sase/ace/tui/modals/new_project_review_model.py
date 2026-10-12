"""Textual-free Review-stage models for the New Project wizard.

These helpers turn one onboarding plan document into review rows, warnings,
blockers, the argv line, and the confirm verdict, plus the durable
``project.add`` submission the apply phase later submits. They import no
Textual modules.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .init_plan_modal_rendering import operation_glyph

__all__ = [
    "ApplySubmission",
    "ReviewBlocker",
    "ReviewRow",
    "ReviewView",
    "apply_submission",
    "build_review",
]


@dataclass(frozen=True, slots=True)
class ReviewRow:
    """One review line derived from a plan step."""

    glyph: str
    style: str
    label: str
    detail: str


@dataclass(frozen=True, slots=True)
class ReviewBlocker:
    """One plan blocker with its follow-up hint."""

    message: str
    hint: str


@dataclass(frozen=True, slots=True)
class ReviewView:
    """Render-ready Review stage content for one plan document."""

    rows: tuple[ReviewRow, ...]
    warnings: tuple[str, ...]
    blockers: tuple[ReviewBlocker, ...]
    argv: tuple[str, ...]
    argv_line: str
    can_confirm: bool
    is_public: bool


@dataclass(frozen=True, slots=True)
class ApplySubmission:
    """Durable ``project.add`` submission built from a reviewed document."""

    argv: tuple[str, ...]
    operation: str
    request_fingerprint: str
    concurrency_keys: tuple[str, ...]
    request: dict[str, Any]


def _steps(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = document.get("steps")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def build_review(document: Mapping[str, Any]) -> ReviewView:
    """Turn one plan document into review rows and the confirm verdict."""
    target = document.get("target")
    target_map = target if isinstance(target, Mapping) else {}
    rows: list[ReviewRow] = []
    if str(document.get("mode") or "") == "create":
        visibility = str(target_map.get("visibility") or "").upper() or "—"
        web_url = str(target_map.get("web_url") or "")
        detail = f"{visibility} {web_url}".strip()
        glyph, style = operation_glyph("create")
        rows.append(ReviewRow(glyph=glyph, style=style, label="REMOTE", detail=detail))
    for step in _steps(document):
        if str(step.get("state") or "") == "skipped":
            continue
        glyph, style = operation_glyph(str(step.get("operation") or ""))
        rows.append(
            ReviewRow(
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
        ReviewBlocker(
            message=str(item.get("message") or ""),
            hint=str(item.get("hint") or ""),
        )
        for item in (list(raw_blockers) if isinstance(raw_blockers, list) else [])
        if isinstance(item, Mapping) and str(item.get("message") or "")
    )
    raw_argv = document.get("apply_argv")
    argv = tuple(str(item) for item in raw_argv) if isinstance(raw_argv, list) else ()
    blocked = str(document.get("status") or "") == "blocked" or bool(blockers)
    visibility = str(target_map.get("visibility") or "").casefold()
    return ReviewView(
        rows=tuple(rows),
        warnings=warnings,
        blockers=blockers,
        argv=argv,
        argv_line=shlex.join(argv),
        can_confirm=not blocked,
        is_public=visibility == "public",
    )


def _requested_from_argv(argv: Sequence[str]) -> dict[str, Any]:
    """Recover the ``requested`` intent encoded in a plan ``apply_argv``."""
    name = ""
    aliases: list[str] = []
    setup = "auto"
    make_current = False
    pending: str | None = None
    for token in argv:
        if pending == "--name":
            name = token
            pending = None
        elif pending == "--alias":
            aliases.append(token)
            pending = None
        elif token in ("--name", "--alias"):
            pending = token
        elif token == "--setup":
            setup = "on"
        elif token == "--no-setup":
            setup = "off"
        elif token == "--make-current":
            make_current = True
    return {
        "name": name,
        "aliases": aliases,
        "setup": setup,
        "make_current": make_current,
    }


def apply_submission(document: Mapping[str, Any]) -> ApplySubmission:
    """Build the durable ``project.add`` submission for *document*.

    ``argv`` is the document's ``apply_argv`` unchanged; the request object
    carries exactly what the CLI compares (mode, actor, target, requested).
    """
    raw_argv = document.get("apply_argv")
    argv = tuple(str(item) for item in raw_argv) if isinstance(raw_argv, list) else ()
    target = document.get("target")
    target_map = target if isinstance(target, Mapping) else {}
    provider = document.get("provider")
    provider_map = provider if isinstance(provider, Mapping) else {}
    identity_key = str(target_map.get("identity_key") or "")
    checkout_dir = str(target_map.get("checkout_dir") or "")
    return ApplySubmission(
        argv=argv,
        operation="project.add",
        request_fingerprint=str(document.get("intent_fingerprint") or ""),
        concurrency_keys=(
            f"project-onboard:{identity_key}",
            f"checkout:{checkout_dir}",
        ),
        request={
            "mode": str(document.get("mode") or "add"),
            "actor": "human",
            "target": {
                "ref": str(target_map.get("ref") or ""),
                "workflow_type": str(provider_map.get("workflow_type") or ""),
                "identity_key": identity_key,
            },
            "requested": _requested_from_argv(argv),
        },
    )
