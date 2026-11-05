"""Strict same-workspace dispatcher for recovery admission requests."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack._recovery_admission_common import (
    bundle_dir_for_request,
    canonical_json,
    descriptor_digest,
    descriptor_from_data,
    is_hijack_recovery_typed_request,
    positive_int,
    read_prepared_recovery_descriptor,
    record_owns_descriptor,
    required_string,
    split_model_effort,
    string_or_none,
    validate_descriptor_fields,
    validate_request_id,
)
from sase.agent.hijack.recovery_successor import (
    RECOVERY_DESCRIPTOR_ENV,
    RecoveryInheritanceError,
    RecoveryLineage,
    build_recovery_descriptor,
    encode_recovery_descriptor,
)
from sase.agent.launch_admission_store import read_json
from sase.core.agent_launch_facade import dispatch_fingerprint
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    launch_plan_from_dict,
)

__all__ = [
    "make_hijack_recovery_agent_dispatcher",
]


def make_hijack_recovery_agent_dispatcher(
    data: Mapping[str, Any],
    *,
    bundle_dir: Path | None = None,
    spawn_successor: Callable[..., Any] | None = None,
    resolve_session_plan: Callable[[str, str | None], Any] | None = None,
) -> Callable[..., Any]:
    """Reconstruct a strict, same-workspace dispatcher from request metadata."""
    descriptor = descriptor_from_data(data)
    if descriptor is None:
        return _missing_descriptor_dispatcher()
    response_dir = bundle_dir or bundle_dir_for_request(
        required_string(data, "request_id")
    )

    def dispatch(
        unit: Any,
        fingerprint: str,
    ) -> tuple[bool, str | None, str | None, list[Any], dict[str, Any]]:
        error = _validate_dispatch_binding(
            data,
            descriptor,
            response_dir,
            unit,
            fingerprint,
        )
        if error:
            return False, None, error, [], {"receipt_state": "rejected"}
        current = ledger.load_record(required_string(descriptor, "hijack_id"))
        if current is None:
            return (
                False,
                None,
                "recovery record disappeared before dispatch",
                [],
                {"receipt_state": "rejected"},
            )
        if not record_owns_descriptor(current, descriptor):
            return (
                False,
                None,
                "recovery reservation changed before dispatch",
                [],
                {"receipt_state": "rejected"},
            )
        available, message = _target_available(required_string(descriptor, "target"))
        if not available:
            return False, None, message, [], {"receipt_state": "rejected"}
        try:
            claim_owner = _current_claim_owner(descriptor)
            plan = _resolve_reserved_plan(descriptor, resolve_session_plan)
            from dataclasses import replace

            plan = replace(
                plan,
                predecessor_artifacts_dir=string_or_none(current.get("artifacts_dir")),
                predecessor_name=str(descriptor["lineage"]["predecessor"]),
            )
        except RecoveryInheritanceError as exc:
            return False, None, str(exc), [], {"receipt_state": "rejected"}
        except Exception as exc:  # noqa: BLE001 - no spawn has started
            return (
                False,
                None,
                f"recovery successor could not be prepared: {exc}",
                [],
                {"receipt_state": "rejected"},
            )
        if str(getattr(plan, "agent_name", "") or "") != str(
            descriptor.get("reserved_successor_name") or ""
        ):
            return (
                False,
                None,
                "reserved recovery successor identity is no longer available",
                [],
                {"receipt_state": "rejected"},
            )
        spawn = spawn_successor or _spawn_strict_successor
        try:
            bootstrap_descriptor = _bootstrap_reservation_descriptor(
                descriptor, fingerprint
            )
            extra_env = _launch_environment(descriptor, unit.logical_id, fingerprint)
            extra_env[RECOVERY_DESCRIPTOR_ENV] = encode_recovery_descriptor(
                bootstrap_descriptor
            )
        except (RecoveryInheritanceError, TypeError, ValueError) as exc:
            return False, None, str(exc), [], {"receipt_state": "rejected"}
        try:
            result = spawn(
                session_base=required_string(descriptor, "session_base"),
                plan=plan,
                project_name=required_string(descriptor, "project_name"),
                project_file=string_or_none(descriptor.get("project_file")),
                prompt=required_string(descriptor, "prompt"),
                workspace_dir=required_string(descriptor, "workspace_dir"),
                workspace_num=int(descriptor["workspace_num"]),
                transfer_from_pid=claim_owner,
                lineage=RecoveryLineage(**dict(descriptor["lineage"])),
                descriptor=bootstrap_descriptor,
                extra_env=extra_env,
            )
        except RecoveryInheritanceError as exc:
            return False, None, str(exc), [], {"receipt_state": "rejected"}
        except Exception as exc:
            from sase.running_field import WorkspaceClaimError

            if isinstance(exc, WorkspaceClaimError):
                return False, None, str(exc), [], {"receipt_state": "failed"}
            raise
        identity = str(getattr(result, "agent_name", "") or "")
        if not identity:
            identity = str(getattr(result, "pid", "") or fingerprint)
        extra = {
            "workspace_reference": str(descriptor.get("workspace_dir") or ""),
            "dispatch_target": required_string(descriptor, "target"),
        }
        return True, identity, None, [result], extra

    return dispatch


def _validate_dispatch_binding(
    data: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    bundle_dir: Path,
    unit: Any,
    fingerprint: str,
) -> str | None:
    if not is_hijack_recovery_typed_request(data):
        return "typed request is not owned by hijack recovery"
    if str(data.get("request_id") or "") != str(
        descriptor.get("admission_request_id") or ""
    ):
        return "recovery admission request id does not match its descriptor"
    if str(data.get("plan_digest") or "") != str(descriptor.get("plan_digest") or ""):
        return "recovery admission plan digest changed"
    try:
        validate_descriptor_fields(descriptor)
        validate_request_id(str(data.get("request_id") or ""))
    except (TypeError, ValueError) as exc:
        return str(exc)
    if descriptor_digest(descriptor) != str(descriptor.get("descriptor_digest") or ""):
        return "recovery admission descriptor checksum changed"
    try:
        plan = launch_plan_from_dict(dict(data.get("typed_plan") or {}))
    except (TypeError, ValueError) as exc:
        return f"recovery admission typed plan is invalid: {exc}"
    if plan.content_digest != str(descriptor.get("plan_digest") or ""):
        return "recovery admission plan changed"
    if len(plan.units) != 1 or plan.units[0].logical_id != str(
        descriptor.get("logical_id") or ""
    ):
        return "recovery admission unit identity changed"
    if not isinstance(unit.payload, AgentUnitWire):
        return "recovery admission contains a non-agent unit"
    if unit.logical_id != str(descriptor.get("logical_id") or ""):
        return "recovery admission unit identity changed"
    if unit.payload.identity != str(descriptor.get("reserved_successor_name") or ""):
        return "recovery admission reserved successor changed"
    expected_model, expected_effort = split_model_effort(
        required_string(descriptor, "target")
    )
    if (
        unit.payload.model != expected_model
        or unit.payload.reasoning_effort != expected_effort
    ):
        return "recovery admission model or effort changed"
    actual = dispatch_fingerprint(plan.content_digest, unit.logical_id, unit.payload)
    if actual != fingerprint or actual != str(
        descriptor.get("dispatch_fingerprint") or ""
    ):
        return "recovery admission dispatch fingerprint changed"
    if not _descriptor_is_persisted(descriptor):
        return "recovery admission has no matching prepared descriptor"
    from sase.notification_gates.paths import REQUEST_FILENAME

    request_path = bundle_dir / REQUEST_FILENAME
    envelope = read_json(request_path)
    if (
        not isinstance(envelope, Mapping)
        or envelope.get("kind") != "direct_typed_launch"
        or envelope.get("request_id") != data.get("request_id")
        or canonical_json(envelope.get("payload")) != canonical_json(data)
    ):
        return "recovery admission request envelope changed"
    return None


def _descriptor_is_persisted(descriptor: Mapping[str, Any]) -> bool:
    try:
        persisted = read_prepared_recovery_descriptor(
            required_string(descriptor, "admission_request_id")
        )
    except (TypeError, ValueError):
        return False
    return persisted is not None and canonical_json(persisted) == canonical_json(
        dict(descriptor)
    )


def _current_claim_owner(descriptor: Mapping[str, Any]) -> int | None:
    from sase.ace.patch import patch_lock
    from sase.running_field._model import WorkspaceClaim
    from sase.workflows.utils import get_project_file_path

    project_name = required_string(descriptor, "project_name")
    project_file = string_or_none(
        descriptor.get("project_file")
    ) or get_project_file_path(project_name)
    workspace_num = descriptor.get("workspace_num")
    expected_owner = positive_int(descriptor.get("expected_claim_owner_pid"))
    if (
        not isinstance(workspace_num, int)
        or isinstance(workspace_num, bool)
        or workspace_num <= 0
    ):
        raise RecoveryInheritanceError("recovery requires a fixed positive workspace")
    try:
        with patch_lock(project_file):
            content = Path(project_file).read_text(encoding="utf-8")
    except OSError as exc:
        raise RecoveryInheritanceError(
            f"recovery cannot read the held workspace claim: {exc}"
        ) from exc
    claims = [
        claim
        for line in content.splitlines()
        if (claim := WorkspaceClaim.from_line(line)) is not None
        and claim.workspace_num == workspace_num
    ]
    if len(claims) > 1:
        raise RecoveryInheritanceError(
            f"workspace #{workspace_num} has multiple current claims"
        )
    if not claims:
        # The old claim may already be missing. The exact workspace will be
        # claimed atomically at child spawn, and a new/foreign row will fail
        # that operation rather than redirecting to an allocator.
        return None
    actual_owner = int(claims[0].pid)
    if expected_owner is None or actual_owner != expected_owner:
        raise RecoveryInheritanceError(
            f"workspace #{workspace_num} is owned by pid {actual_owner}, not the "
            f"held owner {expected_owner!r}"
        )
    return actual_owner


def _resolve_reserved_plan(
    descriptor: Mapping[str, Any],
    resolve_session_plan: Callable[[str, str | None], Any] | None,
) -> Any:
    session_base = required_string(descriptor, "session_base")
    project_name = required_string(descriptor, "project_name")
    if resolve_session_plan is not None:
        return resolve_session_plan(session_base, project_name)
    from sase.agent import _agent_session_attach_resolution as resolution
    from sase.agent.detached_child import AgentSessionAttachDirective

    return resolution.resolve_agent_session_attach_plan(
        AgentSessionAttachDirective(parent=session_base, suffix="@"),
        project_name=project_name,
    )


def _spawn_strict_successor(**kwargs: Any) -> Any:
    from sase.agent.detached_child import (
        AgentSessionAttachDirective,
        spawn_recovery_successor,
    )

    lineage = kwargs["lineage"]
    plan = kwargs["plan"]
    return spawn_recovery_successor(
        AgentSessionAttachDirective(parent=kwargs["session_base"], suffix="@"),
        project_name=kwargs["project_name"],
        project_file=kwargs.get("project_file"),
        prompt=kwargs["prompt"],
        workspace_dir=kwargs["workspace_dir"],
        workspace_num=kwargs["workspace_num"],
        transfer_from_pid=kwargs["transfer_from_pid"],
        lineage=lineage,
        descriptor=kwargs["descriptor"],
        cl_name=plan.agent_name,
        extra_env=dict(kwargs["extra_env"]),
        resolve_plan=lambda *args, **kw: plan,
    )


def _launch_environment(
    descriptor: Mapping[str, Any], logical_id: str, fingerprint: str
) -> dict[str, str]:
    import json as json_module

    from sase.agent.hijack.recover_common import RECOVERY_LAUNCH_IDENTITY_ENV
    from sase.agent.hijack.recovery_successor import (
        RECOVERY_LINEAGE_ENV,
        RECOVERY_STRICT_ENV,
    )
    from sase.env_contracts import SASE_LAUNCH_SUBMITTED_AT_ENV

    return {
        RECOVERY_LAUNCH_IDENTITY_ENV: required_string(descriptor, "launch_identity"),
        RECOVERY_LINEAGE_ENV: json_module.dumps(
            dict(descriptor["lineage"]), sort_keys=True
        ),
        RECOVERY_STRICT_ENV: "1",
        "SASE_LAUNCH_DISPATCH_FINGERPRINT": fingerprint,
        "SASE_LAUNCH_LOGICAL_ID": logical_id,
        SASE_LAUNCH_SUBMITTED_AT_ENV: required_string(
            descriptor, "launch_submitted_at"
        ),
    }


def _bootstrap_reservation_descriptor(
    descriptor: Mapping[str, Any], fingerprint: str
) -> dict[str, Any]:
    """Bind strict child bootstrap to the typed admission reservation."""
    prompt = required_string(descriptor, "prompt")
    return build_recovery_descriptor(
        hijack_id=required_string(descriptor, "hijack_id"),
        launch_identity=required_string(descriptor, "launch_identity"),
        concrete_target=required_string(descriptor, "target"),
        reserved_successor_name=required_string(descriptor, "reserved_successor_name"),
        project=required_string(descriptor, "project_name"),
        workspace_dir=required_string(descriptor, "workspace_dir"),
        lineage=RecoveryLineage(**dict(descriptor["lineage"])),
        reserved_member=required_string(descriptor, "reserved_successor_name"),
        admission_request_id=required_string(descriptor, "admission_request_id"),
        admission_identity=fingerprint,
        workspace_num=int(descriptor["workspace_num"]),
        expected_owner_pid=positive_int(descriptor.get("expected_claim_owner_pid")),
        resolver_pid=int(descriptor["resolver_pid"]),
        resolver_process_identity_token=string_or_none(
            descriptor.get("resolver_process_identity_token")
        ),
        prompt_digest=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        attempt_revision=int(descriptor["attempt_revision"]),
    )


def _target_available(target: str) -> tuple[bool, str | None]:
    from sase.llm_provider.model_alias_resolution_types import (
        resolved_target_is_available,
    )
    from sase.llm_provider.provider_disable_peek import peek_active_provider_disables

    try:
        model_ref, _effort = split_model_effort(target)
        provider, separator, model = model_ref.partition("/")
        if not separator or not provider or not model:
            return False, "recovery target is not a concrete provider/model"
        disables = peek_active_provider_disables()
        if provider in disables:
            return False, f"provider {provider!r} is disabled"
        if not resolved_target_is_available(
            f"{provider}/{model}", provider_disables=disables
        ):
            return False, f"provider/model {provider}/{model} is unavailable"
    except Exception as exc:  # noqa: BLE001 - unavailable facts fail closed
        return False, f"could not revalidate pinned recovery target: {exc}"
    return True, None


def _missing_descriptor_dispatcher() -> Callable[..., Any]:
    def missing(
        *args: Any, **kwargs: Any
    ) -> tuple[bool, None, str, list[Any], dict[str, str]]:
        del args, kwargs
        return (
            False,
            None,
            "hijack recovery typed request is missing its durable descriptor",
            [],
            {"receipt_state": "rejected"},
        )

    return missing
