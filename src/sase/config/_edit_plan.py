"""Config edit planning and write execution."""

from __future__ import annotations

import difflib
from pathlib import Path

from sase.config._edit_types import (
    AppliedResult,
    ConfigEditError,
    ConfigEditOp,
    ConfigEffectivePreview,
    ConfigWritePlan,
    EditPlanResult,
)
from sase.config._edit_yaml import set_key, unset_key
from sase.config.core import (
    DEPRECATED_TOP_LEVEL_KEYS,
    UNSUPPORTED_TOP_LEVEL_KEYS,
    clear_config_cache,
    get_use_chezmoi,
)
from sase.config.inventory import ConfigDiagnostic, ConfigInventory
from sase.config.targets import resolve_write_path
from sase.core.rust import require_rust_binding


def _apply_to_text(text: str, write_plan: ConfigWritePlan) -> str:
    if write_plan.op == "set":
        return set_key(text, write_plan.key_path, write_plan.new_value)
    return unset_key(text, write_plan.key_path)


def _unified_diff(old: str, new: str, target: Path | None) -> str:
    label = str(target) if target is not None else "config"
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
        )
    )


def plan_config_edit(
    inventory: ConfigInventory,
    path: str,
    target: str,
    op: ConfigEditOp,
    *,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan a single set/unset edit against *target* layer for field *path*.

    Calls the Rust core for the write-plan, candidate merged config, effective
    preview, and validation, then computes the target-file text diff in memory.
    No file is written during planning.
    """
    request = {
        "schema": inventory.schema,
        "layers": list(inventory.layer_inputs),
        "target_layer": target,
        "path": path,
        "op": op.to_wire(),
        "deprecations": dict(DEPRECATED_TOP_LEVEL_KEYS),
        "unsupported": sorted(UNSUPPORTED_TOP_LEVEL_KEYS),
    }
    binding = require_rust_binding("config_plan_edit")
    try:
        payload = binding(request)
    except ValueError as exc:
        raise ConfigEditError(str(exc)) from exc

    write_plan = ConfigWritePlan.from_wire(payload["write_plan"])

    chezmoi = get_use_chezmoi() if use_chezmoi is None else use_chezmoi
    write_path = resolve_write_path(write_plan.file, use_chezmoi=chezmoi)
    current_text = (
        write_path.read_text(encoding="utf-8")
        if write_path is not None and write_path.is_file()
        else ""
    )
    new_text = _apply_to_text(current_text, write_plan)
    text_diff = _unified_diff(current_text, new_text, write_path)

    return EditPlanResult(
        schema_version=payload["schema_version"],
        write_plan=write_plan,
        candidate_config=payload["candidate_config"],
        effective_preview=ConfigEffectivePreview.from_wire(
            payload["effective_preview"]
        ),
        validation=tuple(
            ConfigDiagnostic.from_wire(item) for item in payload["validation"]
        ),
        diagnostics=tuple(
            ConfigDiagnostic.from_wire(item) for item in payload["diagnostics"]
        ),
        target_path=str(write_path) if write_path is not None else None,
        used_chezmoi=chezmoi,
        current_text=current_text,
        new_text=new_text,
        text_diff=text_diff,
    )


def apply_config_edit(plan: EditPlanResult) -> AppliedResult:
    """Write the planned edit to disk using the previewed text."""
    if plan.target_path is None:
        raise ConfigEditError("edit plan has no writable target file")
    path = Path(plan.target_path)
    created = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.new_text, encoding="utf-8")
    clear_config_cache()
    return AppliedResult(
        path=str(path),
        op=plan.write_plan.op,
        key_path=plan.write_plan.key_path,
        created=created,
        used_chezmoi=plan.used_chezmoi,
    )
