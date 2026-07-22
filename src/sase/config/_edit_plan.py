"""Config edit planning and write execution."""

from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from sase.config._edit_types import (
    AppliedResult,
    ConfigEditConflict,
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
    path: str | None,
    target: str,
    op: ConfigEditOp,
    *,
    key_path: tuple[str, ...] | list[str] | None = None,
    use_chezmoi: bool | None = None,
) -> EditPlanResult:
    """Plan a single set/unset edit against *target* layer for field *path*.

    Calls the Rust core for the write-plan, candidate merged config, effective
    preview, and validation, then computes the target-file text diff in memory.
    No file is written during planning.
    """
    request: dict[str, object] = {
        "schema": inventory.schema,
        "layers": list(inventory.layer_inputs),
        "target_layer": target,
        "op": op.to_wire(),
        "deprecations": dict(DEPRECATED_TOP_LEVEL_KEYS),
        "unsupported": sorted(UNSUPPORTED_TOP_LEVEL_KEYS),
    }
    if path is not None:
        request["path"] = path
    if key_path is not None:
        request["key_path"] = list(key_path)
    binding = require_rust_binding("config_plan_edit")
    try:
        payload = binding(request)
    except ValueError as exc:
        raise ConfigEditError(str(exc)) from exc

    chezmoi = get_use_chezmoi() if use_chezmoi is None else use_chezmoi
    return build_edit_plan_result(payload, use_chezmoi=chezmoi)


def build_edit_plan_result(
    payload: dict[str, Any],
    *,
    use_chezmoi: bool,
) -> EditPlanResult:
    """Add source-preserving target bytes and a diff to a Rust edit plan."""
    write_plan_payload = payload["write_plan"]
    if not isinstance(write_plan_payload, dict):
        raise ConfigEditError("config backend returned an invalid write plan")
    write_plan = ConfigWritePlan.from_wire(write_plan_payload)

    chezmoi = use_chezmoi
    write_path = resolve_write_path(write_plan.file, use_chezmoi=chezmoi)
    target_bytes = (
        write_path.read_bytes()
        if write_path is not None and write_path.is_file()
        else None
    )
    try:
        current_text = target_bytes.decode("utf-8") if target_bytes is not None else ""
    except UnicodeDecodeError as exc:
        raise ConfigEditError(
            f"config target is not valid UTF-8: {write_path}"
        ) from exc
    new_text = _apply_to_text(current_text, write_plan)
    text_diff = _unified_diff(current_text, new_text, write_path)

    return EditPlanResult(
        schema_version=int(payload["schema_version"]),
        write_plan=write_plan,
        candidate_config=dict(payload["candidate_config"]),
        effective_preview=ConfigEffectivePreview.from_wire(
            dict(payload["effective_preview"])
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
        target_existed=target_bytes is not None,
        target_bytes=target_bytes,
        target_token=_target_token(target_bytes),
    )


def apply_config_edit(plan: EditPlanResult) -> AppliedResult:
    """Atomically write a non-stale previewed edit to disk."""
    if plan.target_path is None:
        raise ConfigEditError("edit plan has no writable target file")
    path = Path(plan.target_path)
    current_bytes = path.read_bytes() if path.is_file() else None
    if (
        _target_token(current_bytes) != plan.target_token
        or current_bytes != plan.target_bytes
    ):
        raise ConfigEditConflict(
            f"config target changed after preview: {path}; reload and re-plan the edit"
        )

    created = current_bytes is None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            if not created:
                mode = stat.S_IMODE(path.stat().st_mode)
                os.fchmod(stream.fileno(), mode)
            stream.write(plan.new_text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        replaced = True
    finally:
        if not replaced and temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    _fsync_directory(path.parent)
    clear_config_cache()
    return AppliedResult(
        path=str(path),
        op=plan.write_plan.op,
        key_path=plan.write_plan.key_path,
        created=created,
        used_chezmoi=plan.used_chezmoi,
    )


def _target_token(data: bytes | None) -> str:
    """Return a strong token that distinguishes absence from empty bytes."""
    if data is None:
        return "absent"
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _fsync_directory(path: Path) -> None:
    """Best-effort durability barrier for the completed atomic replacement."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
