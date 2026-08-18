"""``sase flag new`` — create the flag bead and print a registry scaffold."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from rich.console import Console

import sase
from sase.core import time as core_time
from sase.feature_flags.beads import FLAG_TASK_TYPE, create_flag_bead
from sase.feature_flags.cli_render import resolve_console
from sase.feature_flags.defaults import default_remove_by_thresholds
from sase.feature_flags.managed import project_is_sase_managed
from sase.feature_flags.models import (
    FeatureFlagDefinition,
    FeatureFlagError,
    FlagKind,
    is_feature_flag_key,
)
from sase.feature_flags.registry import feature_flag_definitions
from sase.task_types.fields import (
    TaskTypeCreateError,
    resolve_field_value,
    task_type_field_problems,
)


_SNAKE_CASE_KEY_MESSAGE = "feature flag key must be snake_case"
_KIND_CHOICES: tuple[FlagKind, ...] = ("beta", "sunset")
_UNMANAGED_NEW_ERROR = (
    "`sase flag new` can only run in a SASE-managed checkout "
    "(set is_sase_managed: true in sase/sase.yml). The registry lives in "
    "the SASE source tree, so a scaffold from another project has nowhere "
    "to paste."
)


def handle_flag_new(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    today: date | None = None,
    version: str | None = None,
    cwd: Path | None = None,
    create_bead: bool = True,
) -> int:
    """Run ``sase flag new <key>``."""
    if not project_is_sase_managed(cwd):
        print(f"Error: {_UNMANAGED_NEW_ERROR}", file=sys.stderr)
        return 1

    key = str(getattr(args, "flag_key", "") or "")
    try:
        scaffold = _build_flag_scaffold(
            key,
            description=getattr(args, "description", None),
            kind=getattr(args, "kind", None),
            when_enabled=getattr(args, "when_enabled", None),
            when_disabled=getattr(args, "when_disabled", None),
            remove_when=getattr(args, "remove_when", None),
            remove_by=getattr(args, "remove_by", None),
            size=getattr(args, "size", None),
            definitions=definitions,
            today=today,
            version=version,
            cwd=cwd,
            create_bead=create_bead,
        )
    except FeatureFlagError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    resolve_console(console).print(scaffold)
    return 0


def _build_flag_scaffold(
    key: str,
    *,
    description: str | None = None,
    kind: FlagKind | str | None = None,
    when_enabled: str | None = None,
    when_disabled: str | None = None,
    remove_when: str | None = None,
    remove_by: str | None = None,
    size: str | None = None,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    today: date | None = None,
    version: str | None = None,
    cwd: Path | None = None,
    create_bead: bool = True,
) -> str:
    """Create the flag bead and return the paste-ready scaffold."""
    if not is_feature_flag_key(key):
        raise FeatureFlagError(f"{_SNAKE_CASE_KEY_MESSAGE}: {key!r}")
    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    if key in resolved_definitions:
        raise FeatureFlagError(f"feature flag {key!r} is already registered")

    resolved_kind: FlagKind = _coerce_kind(kind)
    resolved_when_enabled = _resolve_prose(when_enabled, option="--when-enabled")
    resolved_when_disabled = _resolve_prose(when_disabled, option="--when-disabled")
    resolved_remove_when = _resolve_prose(remove_when, option="--remove-when")
    resolved_description = (description or "").strip() or resolved_when_enabled

    remove_by_date, remove_by_release = default_remove_by_thresholds(
        today=today or core_time.local_now().date(),
        version=version or sase.__version__,
        remove_by=remove_by,
    )

    field_values = {
        "key": key,
        "kind": resolved_kind,
        "when_enabled": resolved_when_enabled,
        "when_disabled": resolved_when_disabled,
        "remove_when": resolved_remove_when,
        "remove_by_date": remove_by_date,
        "remove_by_release": remove_by_release,
    }
    _validate_flag_field_values(field_values)

    if create_bead:
        issue = create_flag_bead(
            key=key,
            kind=resolved_kind,
            when_enabled=resolved_when_enabled,
            when_disabled=resolved_when_disabled,
            remove_when=resolved_remove_when,
            remove_by_date=remove_by_date,
            remove_by_release=remove_by_release,
            title=f"Retire {key}",
            description=resolved_description,
            size=size or "small",
            cwd=cwd,
        )
        bead_id = issue.id
    else:
        bead_id = "<flag-bead-id>"

    return _scaffold_text(
        key,
        kind=resolved_kind,
        description=resolved_description,
        when_enabled=resolved_when_enabled,
        when_disabled=resolved_when_disabled,
        bead_id=bead_id,
        remove_by_date=remove_by_date,
        remove_by_release=remove_by_release,
    )


def _scaffold_text(
    key: str,
    *,
    kind: FlagKind,
    description: str,
    when_enabled: str,
    when_disabled: str,
    bead_id: str,
    remove_by_date: str,
    remove_by_release: str,
) -> str:
    return (
        f"Created flag bead: {bead_id} — Retire {key}\n"
        f"remove_by: {remove_by_date} / {remove_by_release}\n\n"
        "Paste this registry entry into src/sase/feature_flags/registry.py:\n\n"
        f"    {key} = {key!r}\n\n"
        f"    FeatureFlag.{key}: FeatureFlagDefinition(\n"
        f"        key=FeatureFlag.{key},\n"
        f"        kind={kind!r},\n"
        f"        description={description!r},\n"
        f"        bead={bead_id!r},\n"
        "    ),\n\n"
        "Both-states test checklist:\n"
        f"- [ ] enabled=true path is covered: {when_enabled}\n"
        f"- [ ] enabled=false path is covered: {when_disabled}\n"
        f"- [ ] snapshot.enabled(FeatureFlag.{key}) is used at every call site\n"
        "- [ ] no import-time resolution\n"
    )


def _resolve_prose(value: str | None, *, option: str) -> str:
    if not value or not value.strip():
        raise FeatureFlagError(f"{option} is required")
    try:
        resolved = resolve_field_value("", value, option=option)
    except TaskTypeCreateError as exc:
        raise FeatureFlagError(str(exc)) from exc
    if not resolved.strip():
        raise FeatureFlagError(f"{option} is required")
    return resolved


def _validate_flag_field_values(field_values: Mapping[str, str]) -> None:
    from sase.task_types.registry import get_task_type_registry

    record = get_task_type_registry().by_slug.get(FLAG_TASK_TYPE)
    if record is None:
        raise FeatureFlagError(
            "the 'flag' task type is not declared in this project's config"
        )
    problems = task_type_field_problems(record.spec, field_values)
    if problems:
        details = "\n".join(f"  {name}: {message}" for name, message in problems)
        raise FeatureFlagError(f"invalid flag fields:\n{details}")


def _coerce_kind(value: FlagKind | str | None) -> FlagKind:
    if value is None:
        return "beta"
    if value in _KIND_CHOICES:
        return value  # type: ignore[return-value]
    raise FeatureFlagError(f"unknown flag kind: {value!r}")


__all__ = [
    "handle_flag_new",
]
