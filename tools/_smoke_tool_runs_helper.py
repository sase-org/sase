#!/usr/bin/env python3
"""In-process ToolRun helper for the black-box harness.

The harness runs this file with the interpreter behind the ``sase`` executable it
is testing, so seeded rows and retention passes use the same Python and
``sase_core_rs`` build as the CLI under test. Every command reads one JSON payload
from argv and prints one JSON object. The store and ``SASE_HOME`` always come from
the environment, never from a default location.
"""

from __future__ import annotations

import json
import os
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

import sase
import sase_core_rs

from sase.core.process_identity import process_identity_token
from sase.core.tool_run import (
    tool_run_append_event,
    tool_run_begin,
    tool_run_canonicalize_fingerprint,
    tool_run_finish,
    tool_run_list,
    tool_run_normalize_definition,
    tool_run_reconcile,
    tool_run_show,
    tool_run_store_path,
    tool_run_store_stats,
    tool_run_summary,
    tool_run_unknown_evidence,
    tool_run_wire_schema_version,
    tools_dir,
)


DAY = 86_400


def _definition(name: str, argv: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": name,
        "argv": argv,
        "description": name,
        "stages": "none",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


def _identity() -> dict[str, Any]:
    return {
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "sase_module": str(Path(sase.__file__).resolve()),
        "sase_version": metadata.version("sase"),
        "core_module": str(Path(str(getattr(sase_core_rs, "__file__", ""))).resolve()),
        "core_version": metadata.version("sase-core-rs"),
        "core_has_tool_run": hasattr(sase_core_rs, "tool_run_begin"),
    }


def _core_round_trip(_: dict[str, Any]) -> dict[str, Any]:
    store_path = str(tool_run_store_path())
    if tool_run_wire_schema_version() != 1:
        raise RuntimeError("unexpected tool_run schema version")
    if tool_run_unknown_evidence("not observed")["completeness"]["complete"]:
        raise RuntimeError("unknown evidence must stay incomplete")
    definition = _definition("check", ["just", "check"])
    definition["stages"] = "run_silent"
    definition["args"] = "deny"
    definition["inputs"] = ["Justfile"]
    digest = tool_run_normalize_definition(definition)["digest"]
    tool_run_canonicalize_fingerprint(
        {
            "schema_version": 1,
            "completeness": {"complete": False, "missing": ["evidence not observed"]},
        }
    )
    started = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": definition,
            "display_argv": ["just", "check"],
            "project": "sase",
            "now_ts": 10,
            "commit_running": True,
        },
        store_path=store_path,
    )
    run_id = started["run"]["run_id"]
    finished = tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "succeeded",
            "exit_code": 0,
            "duration_ms": 9,
            "now_ts": 19,
        },
        store_path=store_path,
    )
    listed = tool_run_list({"schema_version": 1, "limit": 10}, store_path=store_path)
    shown = tool_run_show(run_id, store_path=store_path)
    stats = tool_run_store_stats(store_path=store_path)
    summary = tool_run_summary(
        {
            "schema_version": 1,
            "project": "sase",
            "tool_name": "check",
            "definition_digest": digest,
            "now_ts": 19,
        },
        store_path=store_path,
    )
    tool_run_append_event(
        {
            "schema_version": 1,
            "event": {
                "schema_version": 1,
                "event_id": "evt-sample-1",
                "run_id": run_id,
                "attempt": 1,
                "kind": "sample",
                "created_ts": 15,
                "sample": {
                    "schema_version": 1,
                    "sample_id": "smp-1",
                    "run_id": run_id,
                    "attempt": 1,
                    "observed_ts": 15,
                    "availability": ["loadavg unavailable"],
                },
            },
        },
        store_path=store_path,
    )
    reconciled = tool_run_reconcile(
        {"schema_version": 1, "facts": [], "now_ts": 19}, store_path=store_path
    )
    ok = (
        started["run"]["state"] == "running"
        and finished["run"]["state"] == "succeeded"
        and bool(listed["runs"])
        and shown["run"]["run_id"] == run_id
        and stats["run_count"] == 1
        and summary.get("last", {}).get("run_id") == run_id
        and reconciled.get("persisted") is True
        and int(sase_core_rs.tool_run_wire_schema_version()) == 1
    )
    return {
        "ok": ok,
        "run_id": run_id,
        "begin_state": started["run"]["state"],
        "finish_state": finished["run"]["state"],
        "run_count": stats["run_count"],
    }


def _seed_liveness(payload: dict[str, Any]) -> dict[str, Any]:
    """Begin four running rows whose wrapper liveness facts differ."""

    boot = str(payload["boot_id"])
    alive_pid = int(payload["alive_pid"])
    alive_identity = process_identity_token(alive_pid)
    if not alive_identity:
        raise RuntimeError("could not read the fixture process identity")
    _, _, start = alive_identity.partition(":")
    rows = {
        "alive": {
            "wrapper_pid": alive_pid,
            "boot_id": boot,
            "process_start_identity": alive_identity,
        },
        "boot-changed": {
            "wrapper_pid": alive_pid,
            "boot_id": "previous-boot-fixture",
            "process_start_identity": f"previous-boot-fixture:{start}",
        },
        "pid-reused": {
            "wrapper_pid": alive_pid,
            "boot_id": boot,
            "process_start_identity": f"{boot}:{int(start) + 7}",
        },
        "unknown": {
            "wrapper_pid": None,
            "boot_id": boot,
            "process_start_identity": None,
        },
    }
    out: dict[str, str] = {}
    for label, facts in rows.items():
        started = tool_run_begin(
            {
                "schema_version": 1,
                "definition": _definition("sleep", ["sleep", "60"]),
                "display_argv": ["sleep", "60"],
                "project": str(payload["project"]),
                "commit_running": True,
                **facts,
            }
        )
        out[label] = started["run"]["run_id"]
    return {"run_ids": out}


def _seed_torn(payload: dict[str, Any]) -> dict[str, Any]:
    """Begin a running row whose wrapper is dead and whose events file is external."""

    started = tool_run_begin(
        {
            "schema_version": 1,
            "definition": _definition("staged", ["true"]),
            "display_argv": ["true"],
            "project": str(payload["project"]),
            "commit_running": True,
            "wrapper_pid": int(payload["dead_pid"]),
            "events_path": str(payload["events_path"]),
        }
    )
    return {"run_id": started["run"]["run_id"]}


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _seed_run(
    label: str,
    *,
    age_days: float,
    settled: bool,
    stdout_bytes: int,
    stderr_bytes: int = 0,
    stdout_path: Path | None = None,
    owner_kind: str | None = None,
    owner_id: str | None = None,
    stage: bool = False,
) -> dict[str, Any]:
    """Create one run whose timestamps are ``age_days`` old, with real log files."""

    now = int(time.time())
    created = now - int(age_days * DAY)
    logs = tools_dir() / "logs"
    directory = logs / f"seed-{label}"
    files = {
        "events": directory / "events.jsonl",
        "stdout": directory / "stdout.log",
        "stderr": directory / "stderr.log",
    }
    _write(files["events"], 200)
    if stdout_path is None and owner_kind is None:
        _write(files["stdout"], stdout_bytes)
        if stderr_bytes:
            _write(files["stderr"], stderr_bytes)
    request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": f"seed-{label}",
        "definition": _definition("seeded", ["true"]),
        "display_argv": ["true"],
        "project": "retention-fixture",
        "now_ts": created,
        "commit_running": True,
        "wrapper_pid": None,
        "events_path": str(files["events"]),
    }
    if owner_kind is not None:
        request["owner_kind"] = owner_kind
        request["owner_id"] = owner_id
    else:
        request["log_stdout_path"] = str(stdout_path or files["stdout"])
        if stderr_bytes:
            request["log_stderr_path"] = str(files["stderr"])
    tool_run_begin(request)
    if stage:
        tool_run_append_event(
            {
                "schema_version": 1,
                "event": {
                    "schema_version": 1,
                    "event_id": f"seed-{label}-stage-start",
                    "run_id": f"seed-{label}",
                    "attempt": 1,
                    "kind": "stage_started",
                    "created_ts": created + 1,
                    "stage": {
                        "schema_version": 1,
                        "stage_id": f"seed-{label}-stage",
                        "run_id": f"seed-{label}",
                        "attempt": 1,
                        "description": "seeded stage",
                        "started_ts": created + 1,
                        "incomplete": True,
                        "diagnostics": [],
                    },
                    "diagnostics": [],
                },
            }
        )
    if settled:
        tool_run_finish(
            {
                "schema_version": 1,
                "run_id": f"seed-{label}",
                "state": "succeeded",
                "exit_code": 0,
                "duration_ms": 5,
                "now_ts": created + 5,
            }
        )
    return {"run_id": f"seed-{label}", **{k: str(v) for k, v in files.items()}}


def _seed_retention(payload: dict[str, Any]) -> dict[str, Any]:
    """Seed runs across every retention horizon plus the protected cases."""

    outside = Path(str(payload["outside_dir"]))
    outside.mkdir(parents=True, exist_ok=True)
    escape_target = outside / "escape-target.log"
    escape_target.write_bytes(b"e" * 321)
    owner_log = outside / "monitor-owner.log"
    owner_log.write_bytes(b"o" * 654)

    logs = tools_dir() / "logs" / "seed-symlink"
    logs.mkdir(parents=True, exist_ok=True)
    link = logs / "stdout.log"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(escape_target)

    seeded = {
        "old-summary": _seed_run(
            "old-summary",
            age_days=300,
            settled=True,
            stdout_bytes=1000,
            stderr_bytes=500,
        ),
        "old-detail": _seed_run(
            "old-detail",
            age_days=100,
            settled=True,
            stdout_bytes=800,
            stage=True,
        ),
        "old-logs": _seed_run("old-logs", age_days=30, settled=True, stdout_bytes=700),
        "recent": _seed_run("recent", age_days=0.01, settled=True, stdout_bytes=600),
        "unsettled": _seed_run(
            "unsettled", age_days=300, settled=False, stdout_bytes=900, stage=True
        ),
        "symlink": _seed_run(
            "symlink", age_days=30, settled=True, stdout_bytes=0, stdout_path=link
        ),
        "monitor-owned": _seed_run(
            "monitor-owned",
            age_days=30,
            settled=True,
            stdout_bytes=0,
            owner_kind="monitor",
            owner_id="mon-fixture",
        ),
    }
    return {
        "seeded": seeded,
        "outside": {"escape_target": str(escape_target), "owner_log": str(owner_log)},
        "stats": tool_run_store_stats(),
    }


def _seed_cap(_: dict[str, Any]) -> dict[str, Any]:
    """Seed recent runs whose retained logs together exceed a small aggregate cap."""

    seeded = {
        "cap-oldest": _seed_run(
            "cap-oldest", age_days=0.3, settled=True, stdout_bytes=1000
        ),
        "cap-middle": _seed_run(
            "cap-middle", age_days=0.2, settled=True, stdout_bytes=1000
        ),
        "cap-newest": _seed_run(
            "cap-newest", age_days=0.1, settled=True, stdout_bytes=1000
        ),
        "cap-live": _seed_run(
            "cap-live", age_days=0.4, settled=False, stdout_bytes=900
        ),
    }
    return {"seeded": seeded}


def _tree(root: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            out[str(path.relative_to(root))] = path.stat().st_size
    return out


def _retention(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the disk owner's real reap step against the isolated store."""

    from sase.core.disk_footprint_reap_tool_run import tool_run_reap_step

    root = tools_dir()
    before_tree = _tree(root / "logs")
    before_stats = tool_run_store_stats()
    step = tool_run_reap_step(apply=bool(payload.get("apply")))
    after_tree = _tree(root / "logs")
    return {
        "owner": step.owner,
        "mode": step.mode,
        "summary": step.summary,
        "reclaimed_bytes": step.reclaimed_bytes,
        "changed": step.changed,
        "exit_code": step.exit_code,
        "owner_error": step.owner_error,
        "byte_accounting_complete": step.byte_accounting_complete,
        "details": step.details,
        "before_tree": before_tree,
        "after_tree": after_tree,
        "before_stats": before_stats,
        "after_stats": tool_run_store_stats(),
        "store_exists": tool_run_store_path().exists(),
        "tools_dir_exists": root.exists(),
    }


def _list_runs(payload: dict[str, Any]) -> dict[str, Any]:
    return tool_run_list({"schema_version": 1, "limit": 200, **payload})


_COMMANDS = {
    "core-round-trip": _core_round_trip,
    "identity": lambda _: _identity(),
    "list-runs": _list_runs,
    "retention": _retention,
    "seed-cap": _seed_cap,
    "seed-liveness": _seed_liveness,
    "seed-retention": _seed_retention,
    "seed-torn": _seed_torn,
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in _COMMANDS:
        print(
            f"usage: {argv[0]} {{{','.join(sorted(_COMMANDS))}}} [JSON]",
            file=sys.stderr,
        )
        return 2
    payload = json.loads(argv[2]) if len(argv) > 2 else {}
    print(json.dumps(_COMMANDS[argv[1]](payload), sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    raise SystemExit(main(sys.argv))
