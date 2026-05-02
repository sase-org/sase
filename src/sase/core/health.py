"""Core health check for the required ``sase_core_rs`` extension.

The check verifies that the Rust extension is installed and exposes a known
cheap binding set so release smokes and user scripts can
branch on the exit code without parsing output. ``sase_core_rs`` is a hard
runtime dependency; there is no Python-mode escape hatch.

Behavior summary:

- The extension must import. A missing wheel produces ``status="error"`` and
  the CLI exits non-zero. Non-``ImportError`` import-time failures (e.g. ABI
  mismatch) surface verbatim so a misbuilt wheel does not look like a
  missing install.
- The extension must expose representative parser, agent-launch, and bead
  bindings. Any missing or failing probe produces ``status="error"``.
"""

from __future__ import annotations

import platform
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sase.core.rust import RUST_EXTENSION_MODULE_NAME, require_rust_extension

HEALTH_OK = "ok"
HEALTH_ERROR = "error"

_HEALTH_PROBE_QUERY = "status:Ready"
_HEALTH_PROBE_PROMPT = "health check launch prompt"
_HEALTH_PROBE_LAUNCH_KIND = "multi_prompt"
_HEALTH_PROBE_BEAD_ID = "health-1"


@dataclass(frozen=True)
class BackendHealthReport:
    """Result of :func:`check_backend_health`.

    The dataclass is frozen so callers cannot accidentally mutate the
    JSON-shaped report between collection and serialization.
    """

    status: str
    rust_extension_module: str
    rust_extension_loaded: bool
    rust_extension_path: str | None
    rust_extension_version: str | None
    python_version: str
    platform: str
    probe_query: str
    probe_ok: bool
    error: str | None = None
    error_kind: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON output."""
        return asdict(self)


def _module_version(module: object) -> str | None:
    """Return ``module.__version__`` if exposed, else ``None``.

    PyO3 extensions don't always set ``__version__``; this is best-effort and
    safe to call on a real or fake module.
    """
    return getattr(module, "__version__", None)


def _module_path(module: object) -> str | None:
    """Return ``module.__file__`` if available, else ``None``.

    Built-in or namespace-style modules may omit ``__file__``.
    """
    return getattr(module, "__file__", None)


def check_backend_health() -> BackendHealthReport:
    """Run a cheap end-to-end check of the installed Rust core.

    Steps:

    1. Try to import ``sase_core_rs`` via the strict loader.
    2. Call cheap shipped parser, launch-planning, and bead bindings. The
       launch and bead probes catch stale wheels before a user discovers the
       missing binding during an agent launch or ``sase bead`` command.

    A missing or broken ``sase_core_rs`` is reported as ``status="error"``.
    """
    rust_module: Any = None
    error: str | None = None
    error_kind: str | None = None
    probes: dict[str, bool] = {
        "parse_query": False,
        "agent_launch_wire_schema_version": False,
        "plan_agent_launch_fanout": False,
        "bead_cli_execute": False,
    }

    try:
        rust_module = require_rust_extension()
    except Exception as exc:  # noqa: BLE001 — surface misbuilt-wheel errors verbatim.
        rust_module = None
        error = f"failed to import {RUST_EXTENSION_MODULE_NAME}: {exc}"
        error_kind = type(exc).__name__

    rust_loaded = rust_module is not None

    probe_ok = False
    if rust_loaded and error is None:
        try:
            parse_query = rust_module.parse_query
        except AttributeError:
            error = (
                f"{RUST_EXTENSION_MODULE_NAME} is importable but does not "
                "expose parse_query; the extension is too old or was built "
                "without the shipped Phase 6 bindings."
            )
            error_kind = "AttributeError"
        else:
            try:
                parse_query(_HEALTH_PROBE_QUERY)
                probes["parse_query"] = True
            except Exception as exc:  # noqa: BLE001 — surface broken wheel.
                error = (
                    f"{RUST_EXTENSION_MODULE_NAME}.parse_query("
                    f"{_HEALTH_PROBE_QUERY!r}) raised {type(exc).__name__}: "
                    f"{exc}"
                )
                error_kind = type(exc).__name__

    if rust_loaded and error is None:
        try:
            wire_schema_version = rust_module.agent_launch_wire_schema_version
        except AttributeError:
            error = (
                f"{RUST_EXTENSION_MODULE_NAME} is importable but does not "
                "expose agent_launch_wire_schema_version; the extension is "
                "too old or was built without the Rust-backed launch bindings."
            )
            error_kind = "AttributeError"
        else:
            try:
                version = int(wire_schema_version())
                if version != 1:
                    raise RuntimeError(f"unexpected schema version {version}")
                probes["agent_launch_wire_schema_version"] = True
            except Exception as exc:  # noqa: BLE001 — surface broken wheel.
                error = (
                    f"{RUST_EXTENSION_MODULE_NAME}.agent_launch_wire_schema_version() "
                    f"raised {type(exc).__name__}: {exc}"
                )
                error_kind = type(exc).__name__

    if rust_loaded and error is None:
        try:
            plan_agent_launch_fanout = rust_module.plan_agent_launch_fanout
        except AttributeError:
            error = (
                f"{RUST_EXTENSION_MODULE_NAME} is importable but does not "
                "expose plan_agent_launch_fanout; the extension is too old "
                "or was built without the Rust-backed launch planner."
            )
            error_kind = "AttributeError"
        else:
            try:
                plan = plan_agent_launch_fanout(
                    _HEALTH_PROBE_PROMPT,
                    _HEALTH_PROBE_LAUNCH_KIND,
                )
                if not isinstance(plan, dict) or not plan.get("slots"):
                    raise RuntimeError("launch planner returned no slots")
                probes["plan_agent_launch_fanout"] = True
            except Exception as exc:  # noqa: BLE001 — surface broken wheel.
                error = (
                    f"{RUST_EXTENSION_MODULE_NAME}.plan_agent_launch_fanout("
                    f"{_HEALTH_PROBE_LAUNCH_KIND!r}) raised "
                    f"{type(exc).__name__}: {exc}"
                )
                error_kind = type(exc).__name__

    if rust_loaded and error is None:
        try:
            bead_cli_execute = rust_module.bead_cli_execute
        except AttributeError:
            error = (
                f"{RUST_EXTENSION_MODULE_NAME} is importable but does not "
                "expose bead_cli_execute; the extension is too old or was "
                "built without the Rust-backed bead bindings."
            )
            error_kind = "AttributeError"
        else:
            try:
                with tempfile.TemporaryDirectory(prefix="sase_core_health_bead_") as td:
                    root = Path(td)
                    beads_dir = root / "sdd" / "beads"
                    beads_dir.mkdir(parents=True)
                    (beads_dir / "config.json").write_text(
                        '{"issue_prefix":"health","next_counter":2,"owner":""}\n',
                        encoding="utf-8",
                    )
                    (beads_dir / "issues.jsonl").write_text(
                        (
                            '{"id":"health-1","title":"Health","status":"open",'
                            '"issue_type":"plan","parent_id":null,"owner":"",'
                            '"assignee":"","created_at":"2026-01-01T00:00:00Z",'
                            '"created_by":"","updated_at":"2026-01-01T00:00:00Z",'
                            '"closed_at":null,"close_reason":null,'
                            '"description":"","notes":"","design":"",'
                            '"is_ready_to_work":false,"changespec_name":"",'
                            '"changespec_bug_id":"","dependencies":[]}\n'
                        ),
                        encoding="utf-8",
                    )
                    outcome = bead_cli_execute(
                        ["show", _HEALTH_PROBE_BEAD_ID],
                        [str(beads_dir)],
                        str(beads_dir),
                        str(root),
                        True,
                    )
                if not isinstance(outcome, dict) or not outcome.get("handled"):
                    raise RuntimeError("bead CLI probe was not handled")
                if int(outcome.get("exit_code") or 0) != 0:
                    raise RuntimeError(
                        f"bead CLI probe exited {outcome.get('exit_code')}"
                    )
                if _HEALTH_PROBE_BEAD_ID not in str(outcome.get("stdout") or ""):
                    raise RuntimeError("bead CLI probe did not print the issue")
                probes["bead_cli_execute"] = True
            except Exception as exc:  # noqa: BLE001 — surface broken wheel.
                error = (
                    f"{RUST_EXTENSION_MODULE_NAME}.bead_cli_execute("
                    f"{_HEALTH_PROBE_BEAD_ID!r}) raised {type(exc).__name__}: "
                    f"{exc}"
                )
                error_kind = type(exc).__name__

    probe_ok = all(probes.values())
    status = HEALTH_OK if probe_ok and error is None else HEALTH_ERROR

    return BackendHealthReport(
        status=status,
        rust_extension_module=RUST_EXTENSION_MODULE_NAME,
        rust_extension_loaded=rust_loaded,
        rust_extension_path=_module_path(rust_module) if rust_loaded else None,
        rust_extension_version=(_module_version(rust_module) if rust_loaded else None),
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        probe_query=_HEALTH_PROBE_QUERY,
        probe_ok=probe_ok,
        error=error,
        error_kind=error_kind,
        extras={"probes": probes},
    )
