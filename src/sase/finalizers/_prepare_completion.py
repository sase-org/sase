"""Conditional completion preparation: validate, seal, preview, and read."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import (
    preview_conditional_completion,
    seal_conditional_completion,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.finalizer_wire import FinalizerPlanWire
from sase.finalizers._prepare_intents import persist_prepared_completion
from sase.finalizers._prepare_shared import PreparedCompletion, command_argv
from sase.finalizers.declaration import (
    FinalizerDeclarationError,
    load_finalizer_plan,
    publish_final_context,
    require_artifacts_dir,
)
from sase.finalizers.declaration_manifest import reject_placeholder_commit_messages
from sase.finalizers.providers import BUILTIN_PROVIDER_REFS

#: Manifest spelling for the sealed completion acceptance policy.
PREPARE_ACCEPT_ALIASES = {"pass": "pass", "no-new": "no_new_failures"}
PREPARE_ACCEPT_DEFAULT = "pass"

_MAX_PREPARE_BYTES = 256 * 1024


def prepare_conditional_completion(
    wrapper: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
) -> PreparedCompletion:
    """Validate, seal, and persist a conditional completion intent.

    Publishes the current host-issued finalizer context and observes opened
    repositories. Does not submit a declaration, commit, or end the turn.
    """

    root = require_artifacts_dir(artifacts_dir, "sase final prepare")
    success_message, verification_command, declaration = _parse_wrapper(wrapper)
    accept = _parse_accept(wrapper)
    reject_placeholder_commit_messages(declaration)
    publication = publish_final_context(artifacts_dir=str(root))
    context = publication.context
    plan = load_finalizer_plan(root)
    if context.context_digest:
        declaration.setdefault("context_digest", context.context_digest)
    declaration.setdefault("plan_digest", plan.plan_digest)
    # Resolve through the public facade so monkeypatching
    # ``sase.finalizers.prepare.observe_completion_repositories`` keeps working.
    from sase.finalizers import prepare as prepare_facade

    observations = prepare_facade.observe_completion_repositories(root)
    creator: dict[str, str] = {
        "project": os.environ.get("SASE_PROJECT")
        or os.environ.get("SASE_PROJECT_NAME")
        or "sase",
        "run_id": context.run_id,
        "agent_name": context.agent_id,
    }
    workspace_id = (os.environ.get("SASE_WORKSPACE_NUM") or "").strip()
    if workspace_id:
        creator["workspace_id"] = workspace_id
    request = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "creator": creator,
        "context": {
            "run_id": context.run_id,
            "agent_id": context.agent_id,
            "turn_nonce": context.turn_nonce,
            "plan_digest": plan.plan_digest,
            "context_digest": context.context_digest or "",
            "obligation_ids": [
                obligation.obligation_id
                for obligation in context.obligations
                if obligation.kind == "repository"
            ],
        },
        "success_message": success_message,
        "verification_command": verification_command,
        "declaration": declaration,
        "observations": observations,
        "executors": _executor_capabilities(plan),
        "accept": accept,
    }
    try:
        intent = seal_conditional_completion(request)
    except ValueError as exc:
        raise FinalizerDeclarationError(
            f"{exc}\nFallback: run the verification command inline, then "
            "`sase final submit <same-wrapper-file>` (it accepts the prepare "
            "wrapper as-is; do not rebuild the manifest from manifest_template)",
            code="conditional_completion_invalid",
        ) from exc
    _require_sealed_accept(intent, accept)
    stored = persist_prepared_completion(intent, artifacts_dir=root)
    preview = preview_conditional_completion(stored.intent)
    return PreparedCompletion(
        intent=stored.intent,
        preview=preview,
        intent_ref=stored.intent_ref,
        path=stored.path,
    )


def format_prepare_preview(
    prepared: PreparedCompletion,
    *,
    json_output: bool,
) -> str:
    """Render the prepare command's user-facing preview."""

    if json_output:
        payload = {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent_id": prepared.intent["intent_id"],
            "intent_ref": prepared.intent_ref,
            "preview": prepared.preview,
        }
        if str(prepared.intent.get("accept", "pass")) != "pass":
            payload["accept"] = prepared.intent.get("accept")
        return json.dumps(payload, indent=2, sort_keys=True)
    preview = prepared.preview
    checks = preview.get("required_checks") or {}
    command = " ".join(str(part) for part in checks.get("command") or ())
    lines = [
        f"Prepared conditional completion {prepared.intent['intent_id']}",
        f"  ref           {prepared.intent_ref}",
        f"  success       {preview.get('success_action')}",
        f"  checks        {command} ({checks.get('level')})",
        f"  message       {preview.get('prepared_message')}",
        f"  on failure    {preview.get('failure_timeout_routing')}",
    ]
    if str(prepared.intent.get("accept", "pass")) != "pass":
        lines.insert(4, f"  accept        {prepared.intent.get('accept')}")
    for decision in preview.get("repository_decisions") or ():
        lines.append(
            f"  repository    {decision.get('repo_id')} {decision.get('action')} "
            f"{decision.get('message')}"
        )
    lines.append(
        "This does not submit, commit, or end the turn. Bind the ref with "
        "`sase monitor start -f <ref>`."
    )
    return "\n".join(lines)


def read_prepare_manifest(path: str) -> dict[str, Any]:
    """Read one JSON prepare wrapper from a file or stdin."""

    if path == "-":
        import sys

        raw = sys.stdin.buffer.read(_MAX_PREPARE_BYTES + 1)
    else:
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            raise FinalizerDeclarationError(
                f"could not read completion prepare manifest: {exc}",
                code="manifest_read_failed",
            ) from exc
    if len(raw) > _MAX_PREPARE_BYTES:
        raise FinalizerDeclarationError(
            "completion prepare manifest is too large",
            code="manifest_too_large",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizerDeclarationError(
            f"completion prepare manifest is not valid JSON: {exc}",
            code="manifest_invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise FinalizerDeclarationError(
            "completion prepare manifest must be a JSON object",
            code="manifest_invalid_json",
        )
    return payload


def _parse_accept(wrapper: Mapping[str, Any]) -> str:
    """Return the sealed acceptance policy wire value for a prepare wrapper.

    The manifest spells it ``accept: pass|no-new`` and omits it for the
    default ``pass`` path. Anything else is malformed and rejected before
    any intent is sealed.
    """

    raw = wrapper.get("accept", PREPARE_ACCEPT_DEFAULT)
    if not isinstance(raw, str):
        raise FinalizerDeclarationError(
            "prepare manifest `accept` must be 'pass' or 'no-new'",
            code="invalid_completion_accept",
        )
    token = raw.strip().lower()
    try:
        return PREPARE_ACCEPT_ALIASES[token]
    except KeyError:
        raise FinalizerDeclarationError(
            f"prepare manifest `accept` {raw!r} must be 'pass' or 'no-new'",
            code="invalid_completion_accept",
        ) from None


def _require_sealed_accept(intent: Mapping[str, Any], accept: str) -> None:
    """Fail closed when the sealed intent did not keep the requested policy.

    An older core without the accept wire silently seals every intent as
    ``pass``; a requested ``no-new`` must never proceed on such a seal.
    """

    sealed = str(intent.get("accept", PREPARE_ACCEPT_DEFAULT) or "")
    if sealed != accept:
        raise FinalizerDeclarationError(
            "the installed core sealed this intent "
            f"as {sealed or 'pass'!r} instead of the requested "
            f"{accept!r}; reinstall with `just install` (or "
            "`just rust-install` for an editable build) so the "
            "receipt-capable core is active before preparing `no-new`",
            code="completion_accept_not_sealed",
        )


def _parse_wrapper(
    wrapper: Mapping[str, Any],
) -> tuple[str, list[str], dict[str, Any]]:
    success_message = wrapper.get("success_message") or wrapper.get("prepared_message")
    if not isinstance(success_message, str) or not success_message.strip():
        raise FinalizerDeclarationError(
            "prepare manifest requires success_message",
            code="missing_success_message",
        )
    verification = wrapper.get("verification")
    command: object
    if isinstance(verification, Mapping):
        command = verification.get("command")
    else:
        command = wrapper.get("verification_command")
    argv = command_argv(command)
    declaration = wrapper.get("declaration")
    if not isinstance(declaration, dict):
        if "payloads" in wrapper:
            declaration = {
                key: value
                for key, value in wrapper.items()
                if key
                not in {
                    "success_message",
                    "prepared_message",
                    "verification",
                    "verification_command",
                    "kind",
                    "accept",
                }
            }
        else:
            raise FinalizerDeclarationError(
                "prepare manifest requires a declaration object",
                code="missing_declaration",
            )
    return success_message, argv, dict(declaration)


def _executor_capabilities(plan: FinalizerPlanWire) -> list[dict[str, Any]]:
    capabilities: list[dict[str, Any]] = []
    for entry in plan.entries:
        builtin = entry.provider_ref in BUILTIN_PROVIDER_REFS
        capabilities.append(
            {
                "instance_id": entry.instance_id,
                "provider_ref": entry.provider_ref,
                "headless": builtin,
                "durable_replay": builtin,
                "requires_model": not builtin,
            }
        )
    return capabilities
