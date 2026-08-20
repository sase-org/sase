"""Finalizer plan resolution and artifact persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from sase.core.finalizer_facade import resolve_finalizer_plan
from sase.core.finalizer_wire import (
    FinalizerPlanWire,
    finalizer_wire_to_json_dict,
)
from sase.feature_flags import FeatureFlag, current_flags
from sase.finalizers.config import (
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


class FinalizerPlanError(RuntimeError):
    """Raised when finalizer selection cannot be resolved before launch."""


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
    """Validate prompt selection and persist the sealed plan when beta-enabled."""

    raw_operations = tuple(directives.final)
    if not _pluggable_finalizers_enabled():
        if raw_operations:
            raise FinalizerPlanError(
                "%final requires feature flag `pluggable_finalizers`; enable the "
                "beta with `sase --enable-feature pluggable_finalizers ...` "
                "or remove the directive"
            )
        return None

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


def load_persisted_finalizer_plan(
    artifacts_dir: str | None,
) -> Mapping[str, Any] | None:
    """Load a previously persisted finalizer plan artifact."""

    if not artifacts_dir:
        return None
    path = Path(artifacts_dir) / FINALIZER_PLAN_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, Mapping) else None


def _pluggable_finalizers_enabled() -> bool:
    return current_flags().enabled(FeatureFlag.pluggable_finalizers)


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
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        _write_json_atomic(path, payload)
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
    "FINALIZER_PLAN_FILENAME",
    "FinalizerPlanError",
    "ResolvedFinalizerPlan",
    "load_persisted_finalizer_plan",
    "resolve_and_persist_finalizer_plan",
]
