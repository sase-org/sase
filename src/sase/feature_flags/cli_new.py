"""``sase flag new`` — create the flag bead and print a registry scaffold."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from rich.console import Console

import sase
from sase.bead.model import FlagRecord
from sase.core import time as core_time
from sase.feature_flags.beads import create_flag_bead
from sase.feature_flags.cli_render import resolve_console
from sase.feature_flags.defaults import default_flag_record
from sase.feature_flags.managed import project_is_sase_managed
from sase.feature_flags.models import (
    FeatureFlagDefinition,
    FeatureFlagError,
    FlagKind,
    FlagScope,
    is_feature_flag_key,
)
from sase.feature_flags.registry import feature_flag_definitions


_SNAKE_CASE_KEY_MESSAGE = "feature flag key must be snake_case"
_KIND_CHOICES: tuple[FlagKind, ...] = ("beta", "ops", "sunset", "wip")
_SCOPE_CHOICES: tuple[FlagScope, ...] = ("global", "project")
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
            remove_by=getattr(args, "remove_by", None),
            scope=getattr(args, "scope", None),
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
    remove_by: str | None = None,
    scope: FlagScope | str | None = None,
    size: str | None = None,
    definitions: Mapping[str, FeatureFlagDefinition] | None = None,
    today: date | None = None,
    version: str | None = None,
    cwd: Path | None = None,
    create_bead: bool = True,
) -> str:
    """Create the flag bead (when needed) and return the paste-ready scaffold."""
    if not is_feature_flag_key(key):
        raise FeatureFlagError(f"{_SNAKE_CASE_KEY_MESSAGE}: {key!r}")
    resolved_definitions = (
        feature_flag_definitions() if definitions is None else definitions
    )
    if key in resolved_definitions:
        raise FeatureFlagError(f"feature flag {key!r} is already registered")

    resolved_kind: FlagKind = _coerce_kind(kind)
    resolved_scope: FlagScope = _coerce_scope(scope)
    resolved_description = (description or "").strip() or (
        f"Remove the {key} feature flag once both thresholds pass."
    )
    if resolved_kind == "ops" and not (description or "").strip():
        raise FeatureFlagError(
            "ops feature flags need a rationale; pass it with -d/--description"
        )

    bead_id: str | None = None
    record: FlagRecord | None = None
    if resolved_kind != "ops":
        record = default_flag_record(
            key,
            today=today or core_time.local_now().date(),
            version=version or sase.__version__,
            remove_by=remove_by,
        )
        if create_bead:
            issue = create_flag_bead(
                record,
                title=f"Retire {key}",
                description=resolved_description,
                size=size,
                cwd=cwd,
            )
            bead_id = issue.id
        else:
            bead_id = "<flag-bead-id>"

    return _scaffold_text(
        key,
        kind=resolved_kind,
        description=resolved_description,
        scope=resolved_scope,
        bead_id=bead_id,
        record=record,
        default=_default_for_kind(resolved_kind),
    )


def _scaffold_text(
    key: str,
    *,
    kind: FlagKind,
    description: str,
    scope: FlagScope,
    bead_id: str | None,
    record: FlagRecord | None,
    default: bool,
) -> str:
    bead_line = (
        f"        bead={bead_id!r}," if bead_id is not None else "        bead=None,"
    )
    rationale_line = f"        rationale={description!r},\n" if kind == "ops" else ""
    thresholds = ""
    if record is not None:
        thresholds = (
            f"remove_by: {record.remove_by_date} / {record.remove_by_release}\n"
        )
    created = (
        f"Created flag bead: {bead_id} — Retire {key}\n" if bead_id is not None else ""
    )
    if kind == "ops":
        created = (
            "No flag bead created (ops flags are permanent and carry a rationale).\n"
        )
    return (
        f"{created}{thresholds}\n"
        "Paste this registry entry into src/sase/feature_flags/registry.py:\n\n"
        f"    {key} = {key!r}\n\n"
        f"    FeatureFlag.{key}: FeatureFlagDefinition(\n"
        f"        key=FeatureFlag.{key},\n"
        f"        kind={kind!r},\n"
        f"        description={description!r},\n"
        f"        default={default},\n"
        f"        scope={scope!r},\n"
        f"{bead_line}\n"
        f"{rationale_line}"
        "    ),\n\n"
        "Both-states test checklist:\n"
        "- [ ] enabled=true path is covered\n"
        "- [ ] enabled=false path is covered\n"
        f"- [ ] snapshot.enabled(FeatureFlag.{key}) is used at every call site\n"
        "- [ ] no import-time resolution\n"
    )


def _coerce_kind(value: FlagKind | str | None) -> FlagKind:
    if value is None:
        return "beta"
    if value in _KIND_CHOICES:
        return value  # type: ignore[return-value]
    raise FeatureFlagError(f"unknown flag kind: {value!r}")


def _coerce_scope(value: FlagScope | str | None) -> FlagScope:
    if value is None:
        return "global"
    if value in _SCOPE_CHOICES:
        return value  # type: ignore[return-value]
    raise FeatureFlagError(f"unknown flag scope: {value!r}")


def _default_for_kind(kind: FlagKind) -> bool:
    return kind == "sunset"


__all__ = [
    "handle_flag_new",
]
