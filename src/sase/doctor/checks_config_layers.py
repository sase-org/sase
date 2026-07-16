"""Config layer checks for ``sase doctor``."""

from __future__ import annotations

from typing import Any

from sase.config.core import DEPRECATED_TOP_LEVEL_KEYS, load_config_layers
from sase.content_layout import LayoutCollisionError
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS


def check_config_layers() -> DiagnosticCheck:
    """Report config layer visibility and parse/unsupported-key problems."""
    try:
        layers = load_config_layers()
    except LayoutCollisionError as exc:
        return DiagnosticCheck(
            id="config.layers",
            group="config",
            status="ERROR",
            title="Config layers",
            summary="project config exists in canonical and legacy locations",
            details=(str(exc),),
            next_steps=(
                "Move the legacy project config to sase/sase.yml, then rerun "
                "`sase config layers`.",
            ),
            data={
                "layers": [],
                "problem_count": 1,
                "collision_paths": [str(path) for path in exc.paths],
            },
        )
    layer_rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for layer in layers:
        present = bool(layer.present) if layer.present is not None else layer.exists
        loaded = bool(layer.loaded)
        row = {
            "name": layer.name,
            "path": layer.path,
            "present": present,
            "loaded": loaded,
            "list_strategy": layer.list_strategy,
            "keys": list(layer.keys),
            "unsupported_keys": list(layer.unsupported_keys),
            "deprecated_keys": list(layer.deprecated_keys),
            "retired_keys": list(layer.retired_keys),
            "error": layer.error,
        }
        layer_rows.append(row)
        if layer.error:
            location = layer.path or layer.name
            problems.append(f"{location}: {layer.error}")
        if layer.unsupported_keys:
            location = layer.path or layer.name
            keys = ", ".join(layer.unsupported_keys)
            problems.append(f"{location}: unsupported keys ignored: {keys}")
        if layer.deprecated_keys:
            location = layer.path or layer.name
            renames = ", ".join(
                f"{key} -> {DEPRECATED_TOP_LEVEL_KEYS[key]}"
                for key in layer.deprecated_keys
            )
            problems.append(f"{location}: deprecated keys (rename): {renames}")
        if layer.retired_keys:
            location = layer.path or layer.name
            keys = ", ".join(layer.retired_keys)
            problems.append(f"{location}: retired keys ignored (remove): {keys}")

    loaded_count = sum(1 for row in layer_rows if row["loaded"])
    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{loaded_count}/{len(layer_rows)} config layers loaded"
        if not problems
        else f"{len(problems)} config layer problem(s) found"
    )
    next_steps = []
    if problems:
        next_steps.append(
            "Fix the reported YAML/config keys, then rerun `sase config layers`."
        )

    return DiagnosticCheck(
        id="config.layers",
        group="config",
        status=status,
        title="Config layers",
        summary=summary,
        details=tuple(problems[:MAX_DETAIL_ROWS]),
        next_steps=tuple(next_steps),
        data={"layers": layer_rows, "problem_count": len(problems)},
    )
