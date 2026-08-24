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
    finalizer_json_digest,
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
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerConfigDiagnostic,
    finalizer_config_from_json,
    finalizer_config_to_json,
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
FINALIZER_CONFIG_SNAPSHOT_KEY = "config_snapshot"
FINALIZER_CONFIG_SNAPSHOT_SCHEMA_VERSION = 1


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


@dataclass(frozen=True)
class _AuthenticatedFinalizerPlan:
    """The sealed plan, its authenticated config snapshot, and any live drift."""

    plan: FinalizerPlanWire
    config: FinalizerConfig
    drift: tuple[FinalizerConfigDiagnostic, ...] = ()


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
        config=config,
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
    """Return the host-owned sealed plan after rejecting artifact drift."""

    return authenticate_resolved_finalizer_plan_full(artifacts_dir, config=config).plan


def authenticate_resolved_finalizer_plan_full(
    artifacts_dir: str | None,
    *,
    config: FinalizerConfig | None = None,
) -> _AuthenticatedFinalizerPlan:
    """Return the sealed plan, its authenticated config, and any live drift.

    The plan and, when a snapshot was sealed with it, the configuration bodies
    are authenticated against the digest chain. Live configuration is never
    consulted for what to execute; it is only diffed against the sealed
    snapshot to produce non-fatal drift diagnostics.
    """

    try:
        return _authenticate_resolved_finalizer_plan_full(
            artifacts_dir,
            config=config,
        )
    except FinalizerPlanIntegrityError as exc:
        _write_plan_integrity_failure(artifacts_dir, str(exc))
        raise


def _authenticate_resolved_finalizer_plan_full(
    artifacts_dir: str | None,
    *,
    config: FinalizerConfig | None,
) -> _AuthenticatedFinalizerPlan:
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
    if FINALIZER_CONFIG_SNAPSHOT_KEY not in authority_payload:
        sealed_config = config if config is not None else load_finalizer_config()
        missing_snapshot_drift = (
            FinalizerConfigDiagnostic(
                severity="warning",
                code="plan_config_snapshot_missing",
                message=(
                    "this turn's finalizer plan was sealed before configuration "
                    "snapshots existed; live configuration was used without a "
                    "drift comparison against the sealed plan"
                ),
                layer="authority",
                path=FINALIZER_CONFIG_SNAPSHOT_KEY,
            ),
        )
        return _AuthenticatedFinalizerPlan(
            plan=authority,
            config=sealed_config,
            drift=missing_snapshot_drift,
        )
    sealed_config = _sealed_config_snapshot(authority_payload, authority)
    drift = _diagnose_live_configuration(authority, sealed_config, config)
    return _AuthenticatedFinalizerPlan(
        plan=authority, config=sealed_config, drift=drift
    )


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


def _sealed_config_snapshot(
    authority_payload: Mapping[str, Any],
    authority: FinalizerPlanWire,
) -> FinalizerConfig:
    """Rebuild and authenticate the sealed config snapshot for *authority*.

    The snapshot carries no independent signature; it is authentic only
    because rebuilding each entry from it and recomputing ``to_wire()``
    reproduces the already-digest-authenticated plan entry exactly.
    """

    raw_snapshot = authority_payload[FINALIZER_CONFIG_SNAPSHOT_KEY]
    if not isinstance(raw_snapshot, Mapping):
        raise FinalizerPlanIntegrityError(
            "sealed finalizer configuration snapshot is malformed"
        )
    if raw_snapshot.get("schema_version") != FINALIZER_CONFIG_SNAPSHOT_SCHEMA_VERSION:
        raise FinalizerPlanIntegrityError(
            "sealed finalizer configuration snapshot has an unsupported schema version"
        )
    try:
        snapshot_config = finalizer_config_from_json(raw_snapshot.get("config"))
    except ValueError as exc:
        raise FinalizerPlanIntegrityError(
            f"sealed finalizer configuration snapshot is malformed: {exc}"
        ) from exc
    for entry in authority.entries:
        instance = snapshot_config.instances.get(entry.instance_id)
        if instance is None:
            raise FinalizerPlanIntegrityError(
                "sealed configuration snapshot is missing finalizer instance "
                f"{entry.instance_id!r}"
            )
        wire = instance.to_wire()
        for field_name, sealed_value, snapshot_value in (
            ("provider_ref", entry.provider_ref, wire.provider_ref),
            ("after", list(entry.after), list(wire.after)),
            ("max_attempts", entry.policy.max_attempts, wire.policy.max_attempts),
            ("refusal", entry.policy.refusal, wire.policy.refusal),
            ("config_digest", entry.config_digest, wire.config_digest),
            ("provenance_id", entry.provenance_id, wire.provenance_id),
        ):
            if sealed_value != snapshot_value:
                raise FinalizerPlanIntegrityError(
                    f"sealed config for {entry.instance_id!r} does not match the "
                    f"authenticated plan: {field_name} sealed={sealed_value!r} "
                    f"snapshot={snapshot_value!r}"
                )
    return snapshot_config


def _diagnose_live_configuration(
    plan: FinalizerPlanWire,
    sealed_config: FinalizerConfig,
    live_config_override: FinalizerConfig | None,
) -> tuple[FinalizerConfigDiagnostic, ...]:
    """Diff live configuration against the sealed snapshot as a diagnostic only.

    Nothing here can fail the turn: the sealed snapshot is what executes.
    """

    if live_config_override is not None:
        live_config = live_config_override
    else:
        try:
            live_config = load_finalizer_config()
        except Exception as exc:
            return (
                FinalizerConfigDiagnostic(
                    severity="warning",
                    code="plan_config_unreadable",
                    message=(
                        "could not read live finalizer configuration to check for "
                        f"drift from the sealed plan: {exc}; this turn ran the "
                        "sealed configuration"
                    ),
                    layer="live",
                    path="finalizers",
                ),
            )
    diagnostics: list[FinalizerConfigDiagnostic] = []
    for entry in plan.entries:
        sealed_instance = sealed_config.instances.get(entry.instance_id)
        live_instance = live_config.instances.get(entry.instance_id)
        if sealed_instance is None or live_instance is None:
            continue
        diagnostics.extend(
            _diagnose_instance_drift(entry.instance_id, sealed_instance, live_instance)
        )
    return tuple(diagnostics)


def _diagnose_instance_drift(
    instance_id: str,
    sealed: ConfiguredFinalizerInstance,
    live: ConfiguredFinalizerInstance,
) -> list[FinalizerConfigDiagnostic]:
    fields: tuple[tuple[str, str, object, object], ...] = (
        ("provider_ref", "use", sealed.provider_ref, live.provider_ref),
        ("after", "after", list(sealed.after), list(live.after)),
        ("max_attempts", "max_attempts", sealed.max_attempts, live.max_attempts),
        ("refusal", "refusal", sealed.refusal, live.refusal),
        (
            "config",
            "config",
            finalizer_json_digest(dict(sealed.config)),
            finalizer_json_digest(dict(live.config)),
        ),
    )
    diagnostics: list[FinalizerConfigDiagnostic] = []
    for field_name, provenance_key, sealed_display, live_display in fields:
        if sealed_display == live_display:
            continue
        provenance = live.provenance.get(provenance_key)
        location = provenance.layer if provenance else "unknown"
        if provenance and provenance.path:
            location = f"{location}:{provenance.path}"
        diagnostics.append(
            FinalizerConfigDiagnostic(
                severity="warning",
                code="plan_config_drift",
                message=(
                    f"finalizer {instance_id!r} {field_name} drifted after the "
                    f"plan was sealed: sealed={sealed_display} live={live_display} "
                    f"({location}); this turn ran the sealed value"
                ),
                layer=provenance.layer if provenance else "live",
                path=f"finalizers.instances.{instance_id}.{field_name}",
            )
        )
    return diagnostics


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
    config: FinalizerConfig,
) -> Path | None:
    if not artifacts_dir:
        return None
    root = Path(artifacts_dir).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    path = root / FINALIZER_PLAN_FILENAME
    visible_payload = {
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
    authority_payload = {
        **visible_payload,
        FINALIZER_CONFIG_SNAPSHOT_KEY: {
            "schema_version": FINALIZER_CONFIG_SNAPSHOT_SCHEMA_VERSION,
            "config": finalizer_config_to_json(config),
        },
    }
    authority_path = root / FINALIZER_PLAN_AUTHORITY_FILENAME
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        _write_json_atomic(path, visible_payload)
        _write_json_atomic(authority_path, authority_payload)
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
    "FINALIZER_CONFIG_SNAPSHOT_KEY",
    "FINALIZER_CONFIG_SNAPSHOT_SCHEMA_VERSION",
    "FINALIZER_PLAN_AUTHORITY_FILENAME",
    "FINALIZER_PLAN_FILENAME",
    "SASE_FINALIZER_PLAN_DIGEST_ENV",
    "FinalizerPlanError",
    "FinalizerPlanIntegrityError",
    "ResolvedFinalizerPlan",
    "authenticate_resolved_finalizer_plan",
    "authenticate_resolved_finalizer_plan_full",
    "resolve_and_persist_finalizer_plan",
]
