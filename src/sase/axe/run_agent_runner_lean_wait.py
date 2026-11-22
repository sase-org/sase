"""Runner-side handoff to and result recovery from the lean waiter."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import time
from collections.abc import Mapping
from typing import Any

from sase.axe.run_agent_runner_refresh import (
    execv_with_sigterm_mask,
    prepare_runner_exec_handoff,
)
from sase.env_contracts import (
    SASE_RUNNER_LEAN_WAIT_ENV,
    SASE_RUNNER_LEAN_WAIT_RESULT_ENV,
    SASE_RUNNER_LEAN_WAIT_SPEC_ENV,
)

LEAN_WAIT_SPEC_VERSION = 1
_RELEASE_SOURCES = frozenset({"ready_json", "manual", "runner_fallback", "timer"})


def try_handoff_to_lean_waiter(
    mode: str,
    deadline_epoch: float | None,
    blocked_since: float,
    *,
    artifacts_dir: str,
    artifacts_timestamp: str,
    project_name: str | None,
    prompt_file: str,
    submitted_prompt: str,
    agent_name: str | None,
    local_macros: Mapping[str, Any] | None,
    wait_beads: list[str],
) -> bool:
    """Exec the lean waiter for an eligible dependency or time wait.

    Failure is deliberately fail-open: the full runner keeps its current wait
    loop, with the original prompt and macro handoffs restored.
    """
    if (
        os.name != "posix"
        or os.environ.get(SASE_RUNNER_LEAN_WAIT_ENV) == "0"
        or mode not in {"dependency", "duration", "until"}
    ):
        return False

    try:
        waiter_spec = importlib.util.find_spec("sase.axe.run_agent_lean_wait")
        if waiter_spec is None or waiter_spec.origin is None:
            raise ImportError("could not resolve the lean waiter script")
        waiter_path = os.path.abspath(waiter_spec.origin)

        waiter_contract = importlib.import_module("sase.axe.run_agent_lean_wait")
        heartbeat_module = importlib.import_module("sase.axe.wait_checks_heartbeat")

        bead_sync_hint = False
        bead_sync_role = ""
        if wait_beads:
            from sase.bead._sync_refresh import bead_refresh_mode
            from sase.sdd._store_types import BEADS_SIDECAR_ROLE

            bead_sync_hint = bead_refresh_mode() != "off"
            bead_sync_role = BEADS_SIDECAR_ROLE

        handed_off_at = time.time()
        spec = {
            "version": LEAN_WAIT_SPEC_VERSION,
            "artifacts_dir": os.path.abspath(artifacts_dir),
            "project_name": project_name,
            "runner_argv": [sys.executable, *sys.argv],
            "mode": mode,
            "deadline_epoch": deadline_epoch,
            "heartbeat_path": str(heartbeat_module.wait_checks_heartbeat_path()),
            "bead_sync_hint": bead_sync_hint,
            "bead_sync_role": bead_sync_role,
            "blocked_since": blocked_since,
            "handed_off_at": handed_off_at,
        }
        waiter_contract.validate_lean_wait_spec(spec)
    except Exception as exc:
        print(
            f"Warning: Keeping runner in-process; lean waiter setup failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return False

    prepared = prepare_runner_exec_handoff(
        prompt_file=prompt_file,
        submitted_prompt=submitted_prompt,
        agent_name=agent_name,
        artifacts_dir=artifacts_dir,
        local_macros=local_macros,
        local_macros_directory=artifacts_dir,
    )
    if prepared is None:
        return False

    old_spec = os.environ.get(SASE_RUNNER_LEAN_WAIT_SPEC_ENV)
    os.environ[SASE_RUNNER_LEAN_WAIT_SPEC_ENV] = json.dumps(spec, separators=(",", ":"))
    elapsed = max(0.0, handed_off_at - blocked_since)
    print(
        f"Handing waiting runner to lean waiter (mode={mode}, blocked={elapsed:.1f}s)",
        flush=True,
    )
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass
    try:
        from sase.telemetry import flush_metrics

        flush_metrics("agent_runner")
    except Exception:  # noqa: BLE001 - exec handoff must not depend on telemetry.
        pass

    try:
        execv_with_sigterm_mask(
            sys.executable,
            [sys.executable, waiter_path, artifacts_timestamp],
        )
    except OSError as exc:
        if old_spec is None:
            os.environ.pop(SASE_RUNNER_LEAN_WAIT_SPEC_ENV, None)
        else:
            os.environ[SASE_RUNNER_LEAN_WAIT_SPEC_ENV] = old_spec
        prepared.rollback()
        print(
            f"Warning: Failed to enter lean waiter; continuing in-process: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return False
    return True


def consume_lean_wait_result(expected_artifacts_dir: str) -> dict[str, Any] | None:
    """Pop and validate the one-shot result returned by the lean waiter."""
    raw = os.environ.pop(SASE_RUNNER_LEAN_WAIT_RESULT_ENV, None)
    if raw is None:
        return None
    try:
        result = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("lean waiter returned invalid result JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("lean waiter result must be a JSON object")
    version = result.get("version")
    if isinstance(version, bool) or version != LEAN_WAIT_SPEC_VERSION:
        raise ValueError("lean waiter result has an unsupported version")
    if result.get("artifacts_dir") != os.path.abspath(expected_artifacts_dir):
        raise ValueError("lean waiter result does not match this run's artifacts")
    outcome = result.get("outcome")
    if not isinstance(outcome, str) or outcome not in {"released", "killed"}:
        raise ValueError("lean waiter result has an invalid outcome")

    for key in ("dependencies_satisfied_at", "released_at", "killed_at"):
        value = result.get(key)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"lean waiter result field {key} must be finite or null")
    if outcome == "released":
        source = result.get("release_source")
        if not isinstance(source, str) or source not in _RELEASE_SOURCES:
            raise ValueError("released lean waiter result has an invalid source")
        if result.get("killed_at") is not None:
            raise ValueError("released lean waiter result cannot carry killed_at")
    else:
        if result.get("release_source") is not None:
            raise ValueError("killed lean waiter result cannot carry release_source")
        if result.get("killed_at") is None:
            raise ValueError("killed lean waiter result must carry killed_at")
        if (
            result.get("released_at") is not None
            or result.get("dependencies_satisfied_at") is not None
        ):
            raise ValueError("killed lean waiter result cannot carry release times")
    return result


__all__ = ["consume_lean_wait_result", "try_handoff_to_lean_waiter"]
