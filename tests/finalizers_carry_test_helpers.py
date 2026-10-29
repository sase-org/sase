"""Helpers for explicit carry-declaration tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from sase.core.finalizer_facade import validate_finalizer_context
from sase.core.finalizer_wire import FinalizerHandoffWire
from sase.finalizers.declaration import (
    _LiveFinalizerContext,
    _build_live_context,
    _context_payload,
    load_finalizer_plan,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.macro.directives import PromptDirectives

CARRY_STAGED_REF = "123e4567-e89b-12d3-a456-426614174000"


def attach_inheriting_handoff(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: str = "questions",
    staged_ref: str = CARRY_STAGED_REF,
    carry_allowed: bool = True,
) -> None:
    """Stamp a validated inheriting handoff onto live context publication."""

    original = _build_live_context

    def wrapped(
        root: Path,
        *,
        command: str,
        plan: object | None = None,
    ) -> _LiveFinalizerContext:
        live = original(root, command=command, plan=plan)  # type: ignore[misc]
        resolved_plan = plan if plan is not None else load_finalizer_plan(root)
        context = replace(
            live.context,
            handoff=FinalizerHandoffWire(
                kind=kind,
                staged_ref=staged_ref,
                successor_workspace="inherit",
                carry_allowed=carry_allowed,
            ),
            context_digest=None,
        )
        digest = validate_finalizer_context(resolved_plan, context)  # type: ignore[arg-type]
        context = replace(context, context_digest=digest)
        payload = _context_payload(
            resolved_plan,  # type: ignore[arg-type]
            context,
            root=root,
            host_records=live.host_records,
        )
        return _LiveFinalizerContext(
            payload=payload,
            context=context,
            host_records=live.host_records,
        )

    monkeypatch.setattr("sase.finalizers.declaration._build_live_context", wrapped)


def submit_repository_actions(
    artifacts: Path,
    actions: dict[int, str] | None = None,
    *,
    default_action: str = "commit",
    message: str = "fix(final): reconcile commit declaration",
    persist_plan: bool = True,
) -> None:
    """Submit one declaration with per-index repository actions."""

    if persist_plan:
        resolve_and_persist_finalizer_plan(
            PromptDirectives(), artifacts_dir=str(artifacts)
        )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    for index, decision in enumerate(repositories):
        action = (actions or {}).get(index, default_action)
        decision["action"] = action
        if action == "commit":
            decision["message"] = message
            continue
        decision.pop("message", None)
        decision.pop("bead_action", None)
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))
