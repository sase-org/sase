"""Finalizer plan resolution and artifact persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from sase.core.finalizer_facade import (
    authenticate_finalizer_plan,
    resolve_finalizer_plan,
    validate_finalizer_plan,
)
from sase.core.finalizer_wire import (
    FinalizerDiagnosticWire,
    FinalizerPlanWire,
    finalizer_plan_from_dict,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.artifacts import write_finalizer_result
from sase.finalizers.config import (
    FinalizerConfig,
    FinalizerConfigDiagnostic,
    load_finalizer_config,
)
from sase.finalizers.providers import (
    diagnose_finalizer_providers,
    fatal_provider_diagnostics,
)
from sase.finalizers.selection import (
    FinalizerSelectorError,
    parse_finalizer_selector_ops,
)
from sase.memory.locks import locked_file
from sase.xprompt.directives import PromptDirectives


FINALIZER_PLAN_FILENAME = "finalizer_plan.json"
FINALIZER_PLAN_AUTHORITY_FILENAME = "finalizer_plan.authority.json"
SASE_FINALIZER_PLAN_DIGEST_ENV = "SASE_FINALIZER_PLAN_DIGEST"


class FinalizerPlanError(RuntimeError):
    """Raised when finalizer selection cannot be resolved before launch."""


class FinalizerPlanIntegrityError(RuntimeError):
    """Raised when the sealed plan cannot be authenticated for execution."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "plan_integrity_failed",
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedFinalizerPlan:
    """Resolved plan data persisted before the provider turn."""

    raw_operations: tuple[str, ...]
    plan: FinalizerPlanWire
    diagnostics: tuple[FinalizerConfigDiagnostic, ...]
    artifact_path: Path | None = None

    @property
    def selected_instances(self) -> tuple[str, ...]:
        return tuple(entry.instance_id for entry in self.plan.entries)

    def agent_meta_projection(self) -> dict[str, Any]:
        return {
            "plan_digest": self.plan.plan_digest,
            "selected": list(self.selected_instances),
            "raw_operations": list(self.raw_operations),
        }


def resolve_and_persist_finalizer_plan(
    directives: PromptDirectives,
    *,
    artifacts_dir: str | None,
) -> ResolvedFinalizerPlan | None:
    """Validate prompt selection and persist the sealed plan."""

    raw_operations = tuple(directives.final)
    try:
        selectors = parse_finalizer_selector_ops(raw_operations)
    except FinalizerSelectorError as exc:
        raise FinalizerPlanError(str(exc)) from exc

    config = load_finalizer_config()
    fatal = config.fatal_diagnostics()
    if fatal:
        raise FinalizerPlanError(_diagnostics_message(fatal))
    try:
        plan = resolve_finalizer_plan(config.to_plan_input(selectors))
    except Exception as exc:
        raise FinalizerPlanError(f"invalid finalizer plan: {exc}") from exc
    provider_fatal = fatal_provider_diagnostics(
        diagnose_finalizer_providers(config, plan=plan, selected_only=True)
    )
    if provider_fatal:
        raise FinalizerPlanError(_provider_diagnostics_message(provider_fatal))

    artifact_path = _persist_plan(
        artifacts_dir,
        raw_operations=raw_operations,
        plan=plan,
        diagnostics=config.diagnostics,
    )
    return ResolvedFinalizerPlan(
        raw_operations=raw_operations,
        plan=plan,
        diagnostics=config.diagnostics,
        artifact_path=artifact_path,
    )


def authenticate_resolved_finalizer_plan(
    artifacts_dir: str | None,
    *,
    config: FinalizerConfig | None = None,
) -> FinalizerPlanWire:
    """Return the host-owned sealed plan after rejecting artifact and config drift."""

    try:
        return _authenticate_resolved_finalizer_plan(
            artifacts_dir,
            config=config,
        )
    except FinalizerPlanIntegrityError as exc:
        _write_plan_integrity_failure(artifacts_dir, str(exc))
        raise


def _authenticate_resolved_finalizer_plan(
    artifacts_dir: str | None,
    *,
    config: FinalizerConfig | None,
) -> FinalizerPlanWire:
    if not artifacts_dir:
        raise FinalizerPlanIntegrityError("finalizer plan authority is missing")
    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    authority_payload = _require_plan_payload(
        root / FINALIZER_PLAN_AUTHORITY_FILENAME,
        "host-owned finalizer plan authority is missing",
    )
    visible_payload = _require_plan_payload(
        root / FINALIZER_PLAN_FILENAME,
        "model-visible finalizer plan artifact is missing",
    )
    expected = (os.environ.get(SASE_FINALIZER_PLAN_DIGEST_ENV) or "").strip() or None
    authority = _strict_plan(authority_payload.get("plan"), expected_digest=expected)
    visible = _strict_plan(visible_payload.get("plan"), expected_digest=None)
    if finalizer_wire_to_json_dict(authority) != finalizer_wire_to_json_dict(visible):
        raise FinalizerPlanIntegrityError(
            "model-visible finalizer plan drifted from host-owned authority"
        )
    live_config = config if config is not None else load_finalizer_config()
    _compare_live_configuration(authority, live_config)
    return authority


def _require_plan_payload(path: Path, missing_message: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise FinalizerPlanIntegrityError(missing_message)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizerPlanIntegrityError(
            f"finalizer plan artifact is malformed: {exc}"
        ) from exc
    if not isinstance(data, Mapping):
        raise FinalizerPlanIntegrityError("finalizer plan artifact is malformed")
    return data


def _strict_plan(
    raw: object,
    *,
    expected_digest: str | None,
) -> FinalizerPlanWire:
    if not isinstance(raw, Mapping):
        raise FinalizerPlanIntegrityError("finalizer plan is malformed")
    payload = dict(raw)
    try:
        if expected_digest is None:
            validate_finalizer_plan(payload)
        else:
            authenticate_finalizer_plan(payload, expected_digest)
        return finalizer_plan_from_dict(payload)
    except FinalizerPlanIntegrityError:
        raise
    except Exception as exc:
        raise FinalizerPlanIntegrityError(
            f"finalizer plan failed authentication: {exc}"
        ) from exc


def _compare_live_configuration(
    plan: FinalizerPlanWire,
    config: FinalizerConfig,
) -> None:
    for entry in plan.entries:
        live = config.instances.get(entry.instance_id)
        if live is None:
            raise FinalizerPlanIntegrityError(
                f"sealed finalizer instance {entry.instance_id!r} is not configured"
            )
        live_wire = live.to_wire()
        if live.provider_ref != entry.provider_ref:
            raise FinalizerPlanIntegrityError(
                f"live provider_ref for {entry.instance_id!r} drifted from the sealed plan"
            )
        if live.max_attempts != entry.policy.max_attempts:
            raise FinalizerPlanIntegrityError(
                f"live max_attempts for {entry.instance_id!r} drifted from the sealed plan"
            )
        if live.refusal != entry.policy.refusal:
            raise FinalizerPlanIntegrityError(
                f"live refusal policy for {entry.instance_id!r} drifted from the sealed plan"
            )
        if list(live.after) != list(entry.after):
            raise FinalizerPlanIntegrityError(
                f"live dependencies for {entry.instance_id!r} drifted from the sealed plan"
            )
        if live_wire.config_digest != entry.config_digest:
            raise FinalizerPlanIntegrityError(
                f"live configuration for {entry.instance_id!r} drifted from the sealed plan"
            )
        if live_wire.provenance_id != entry.provenance_id:
            raise FinalizerPlanIntegrityError(
                f"live provenance for {entry.instance_id!r} drifted from the sealed plan"
            )


def _write_plan_integrity_failure(artifacts_dir: str | None, message: str) -> None:
    payload = {
        "schema_version": 1,
        "status": "failed",
        "cycles": 0,
        "instances": [],
        "diagnostics": [
            finalizer_wire_to_json_dict(
                FinalizerDiagnosticWire(
                    code="plan_integrity_failed",
                    severity="error",
                    message=message,
                    instance_id=None,
                )
            )
        ],
    }
    write_finalizer_result(artifacts_dir, payload)


def _persist_plan(
    artifacts_dir: str | None,
    *,
    raw_operations: Sequence[str],
    plan: FinalizerPlanWire,
    diagnostics: Sequence[FinalizerConfigDiagnostic],
) -> Path | None:
    if not artifacts_dir:
        return None
    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    path = root / FINALIZER_PLAN_FILENAME
    payload = {
        "schema_version": 1,
        "raw_operations": list(raw_operations),
        "plan": finalizer_wire_to_json_dict(plan),
        "diagnostics": [
            {
                "severity": item.severity,
                "code": item.code,
                "message": item.message,
                "layer": item.layer,
                "path": item.path,
            }
            for item in diagnostics
        ],
    }
    authority_path = root / FINALIZER_PLAN_AUTHORITY_FILENAME
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        _write_json_atomic(path, payload)
        _write_json_atomic(authority_path, payload)
    os.environ[SASE_FINALIZER_PLAN_DIGEST_ENV] = plan.plan_digest
    return path


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _diagnostics_message(diagnostics: Sequence[FinalizerConfigDiagnostic]) -> str:
    first = diagnostics[0]
    return (
        f"invalid finalizer configuration: {first.layer}:{first.path}: {first.message}"
    )


def _provider_diagnostics_message(diagnostics: Sequence[Any]) -> str:
    first = diagnostics[0]
    location = getattr(first, "path", None) or getattr(first, "provider_ref", None)
    prefix = f"{location}: " if location else ""
    return f"invalid finalizer provider: {prefix}{first.message}"


__all__ = [
    "FINALIZER_PLAN_AUTHORITY_FILENAME",
    "FINALIZER_PLAN_FILENAME",
    "FinalizerPlanError",
    "FinalizerPlanIntegrityError",
    "ResolvedFinalizerPlan",
    "SASE_FINALIZER_PLAN_DIGEST_ENV",
    "authenticate_resolved_finalizer_plan",
    "resolve_and_persist_finalizer_plan",
]
