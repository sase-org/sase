"""Shared low-level helpers used by the ``sase update`` sub-handlers."""

from __future__ import annotations

from inspect import Parameter, signature
import json
import os
from typing import Any

from rich.console import Console

from sase.dev_update import DevUpdatePlan
from sase.main.update_types import UPDATE_JSON_SCHEMA_VERSION, PlanDevFn
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import UvToolError
from sase.uv_tool.receipt import ToolReceipt
from sase.uv_tool.render import render_uv_tool_error
from sase.version.inventory import VersionPackageRecord


def fail_update(error: UvToolError, *, as_json: bool, err: Console) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "schema_version": UPDATE_JSON_SCHEMA_VERSION,
                    "error": str(error),
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        render_uv_tool_error(str(error), console=err)
    return 1


def tool_python(install: UvToolInstall) -> str:
    executable = "python.exe" if os.name == "nt" else "python"
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    return str(install.sase_dir / scripts_dir / executable)


def _callable_accepts_keyword(fn: Any, name: str) -> bool:
    try:
        params = signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    for param in params:
        if param.kind is Parameter.VAR_KEYWORD:
            return True
        if param.name == name and param.kind in (
            Parameter.KEYWORD_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


def call_plan_dev_update(
    fn: PlanDevFn,
    records: tuple[VersionPackageRecord, ...] | list[VersionPackageRecord],
    *,
    host_record: VersionPackageRecord,
    receipt: ToolReceipt | None,
    tool_python: str,
    stale_core_record: VersionPackageRecord | None = None,
) -> DevUpdatePlan:
    kwargs: dict[str, Any] = {"host_record": host_record, "receipt": receipt}
    if _callable_accepts_keyword(fn, "tool_python"):
        kwargs["tool_python"] = tool_python
    if _callable_accepts_keyword(fn, "stale_core_record"):
        kwargs["stale_core_record"] = stale_core_record
    return fn(records, **kwargs)
