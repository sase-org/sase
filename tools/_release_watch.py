#!/usr/bin/env python3
"""CLI for one read/decide/execute/report release-steward tick.

``tools/release_watch`` is the entry point. Python owns transport, CLI,
orchestration, and output. Shared eligibility, precedence, idempotency-key,
and escalation policy live in ``sase_core`` and are called through
``sase_core_rs``. There is no Python policy fallback.

Modes (mutually exclusive; ``--once`` is the default when none is selected):

* ``--once/-o``: one read-only decision.
* ``--tick/-t``: one decision; ``--live/-l`` permits its actions and is
  valid only with ``--tick``.
* ``--until-released/-u [VERSION]``: repeat read-only snapshots until that
  exact version is confirmed. When VERSION is omitted, wait for the
  in-flight train if one exists; otherwise wait for a newly confirmed
  version that was not already released at the start of this invocation.
  An unrelated historical release does not end the wait. ``--deadline/-d``
  and ``--poll/-p`` apply only to this mode.

Exit 0 for every well-formed state, including blocked states. Non-zero for
``WATCHER_BROKEN``, bad arguments, or deadline expiry. Ctrl-C stops
polling cleanly and never closes a bead.

``RELEASE_STEWARD_MERGE_ENABLED`` is an explicit policy input. Only the
literal value ``true`` enables merge authority; missing or any other value
is disabled. Observe output never reports that an action occurred.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

from _release_core import CORE_REPO
from _release_watch_actions import ReleaseWatchActionExecutor
from _release_watch_decide import (
    RELEASE_STEWARD_WIRE_SCHEMA_VERSION,
    decide as rust_decide,
    watcher_broken_result,
)
from _release_watch_facts import ReleaseFactsReader
from _release_watch_health import ReleaseHealthReader
from _release_watch_transport import GithubTransport, PypiTransport


DEFAULT_REPO = "sase-org/sase"
DEFAULT_POLL = "5m"
DEFAULT_DEADLINE = "12h"
# One paginated Actions history read can exceed the transport's 20s default.
CLI_GH_TIMEOUT_SECONDS = 120.0
MERGE_AUTHORITY_ENV = "RELEASE_STEWARD_MERGE_ENABLED"
MERGE_AUTHORITY_ENABLED = "true"
CADENCE = {
    "kind": "daily",
    "merge_after_hour_utc": 9,
    "max_merges_per_utc_day": 1,
}
_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?")
_DURATION_RE = re.compile(r"([1-9][0-9]*)(s|m|h|d)", re.IGNORECASE)
_DURATION_SCALE = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class WatchArgumentError(Exception):
    """User-facing CLI argument error."""


class _WatchArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise WatchArgumentError(message)


@dataclass(frozen=True)
class WatchOptions:
    repo: str
    mode: str
    live: bool
    json: bool
    poll: float | None = None
    deadline: float | None = None
    until_version: str | None = None


@dataclass
class WatchRuntime:
    """Injectable adapters for tests; production fills the Nones."""

    collect_snapshot: Callable[[datetime], dict[str, Any]] | None = None
    decide: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None
    execute: Callable[..., dict[str, Any]] | None = None
    now: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(UTC)
    )
    sleep: Callable[[float], None] = field(default=time.sleep)
    stdout: TextIO = field(default_factory=lambda: sys.stdout)
    stderr: TextIO = field(default_factory=lambda: sys.stderr)
    environ: Mapping[str, str] | None = None


def _parse_duration(value: str) -> float:
    match = _DURATION_RE.fullmatch(value.strip())
    if not match:
        raise argparse.ArgumentTypeError(
            "duration must be a positive value such as 5m or 12h"
        )
    amount = int(match.group(1))
    scale = _DURATION_SCALE[match.group(2).lower()]
    return float(amount * scale)


def parse_args(argv: Sequence[str] | None = None) -> WatchOptions:
    """Parse the release-watch CLI. Options are listed alphabetically."""
    parser = _WatchArgumentParser(
        prog="release_watch",
        description=(
            "Read GitHub and PyPI facts, ask the Rust steward for one typed "
            "decision, and optionally execute its train action and "
            "escalation. Scheduled ticks run live; manual ticks need --live."
        ),
    )
    parser.add_argument(
        "-d",
        "--deadline",
        type=_parse_duration,
        default=None,
        metavar="D",
        help=(
            "Stop --until-released after this duration, for example 12h "
            f"(default: {DEFAULT_DEADLINE}; only valid with --until-released)"
        ),
    )
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help=(
            "Write the machine-readable result only on stdout; diagnostics go to stderr"
        ),
    )
    parser.add_argument(
        "-l",
        "--live",
        action="store_true",
        help="Permit the tick's train action and escalation (valid only with --tick)",
    )
    parser.add_argument(
        "-o",
        "--once",
        action="store_true",
        help="One read-only decision; the safe default when no mode is selected",
    )
    parser.add_argument(
        "-p",
        "--poll",
        type=_parse_duration,
        default=None,
        metavar="INTERVAL",
        help=(
            "Sleep this long between --until-released snapshots, for example 5m "
            f"(default: {DEFAULT_POLL}; only valid with --until-released)"
        ),
    )
    parser.add_argument(
        "-r",
        "--repo",
        default=DEFAULT_REPO,
        help=f"GitHub owner/repository (default: {DEFAULT_REPO})",
    )
    parser.add_argument(
        "-t",
        "--tick",
        action="store_true",
        help="One decision; pass --live to execute its proposed actions",
    )
    parser.add_argument(
        "-u",
        "--until-released",
        nargs="?",
        const="",
        default=None,
        metavar="VERSION",
        help=(
            "Repeat read-only snapshots until VERSION is confirmed. When "
            "VERSION is omitted, wait for the in-flight train if one exists; "
            "otherwise wait for a newly confirmed version that was not already "
            "released at the start of this invocation. An unrelated historical "
            "release does not end the wait"
        ),
    )
    ns = parser.parse_args(list(argv) if argv is not None else None)
    modes = [ns.once, ns.tick, ns.until_released is not None]
    if sum(bool(item) for item in modes) > 1:
        parser.error("--once, --tick, and --until-released are mutually exclusive")
    if ns.live and not ns.tick:
        parser.error("--live is valid only with --tick")
    if not _REPO_RE.fullmatch(ns.repo):
        parser.error("--repo must be owner/repository")
    mode = "once"
    until_version: str | None = None
    poll: float | None = None
    deadline: float | None = None
    if ns.tick:
        mode = "tick"
    elif ns.until_released is not None:
        mode = "until_released"
        if ns.until_released != "":
            if not _VERSION_RE.fullmatch(ns.until_released):
                parser.error("--until-released VERSION must be a semantic version")
            until_version = ns.until_released
        poll = ns.poll if ns.poll is not None else _parse_duration(DEFAULT_POLL)
        deadline = (
            ns.deadline
            if ns.deadline is not None
            else _parse_duration(DEFAULT_DEADLINE)
        )
    if mode != "until_released":
        if ns.poll is not None:
            parser.error("--poll is only valid with --until-released")
        if ns.deadline is not None:
            parser.error("--deadline is only valid with --until-released")
    return WatchOptions(
        repo=ns.repo,
        mode=mode,
        live=bool(ns.live),
        json=bool(ns.json),
        poll=poll,
        deadline=deadline,
        until_version=until_version,
    )


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return (
        aware.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _environ(runtime: WatchRuntime) -> Mapping[str, str]:
    return os.environ if runtime.environ is None else runtime.environ


def merge_authority_enabled(environ: Mapping[str, str]) -> bool:
    """True only when the host variable is the literal string ``true``."""
    return environ.get(MERGE_AUTHORITY_ENV) == MERGE_AUTHORITY_ENABLED


def tick_identity(environ: Mapping[str, str]) -> str:
    run_id = environ.get("GITHUB_RUN_ID", "").strip()
    attempt = environ.get("GITHUB_RUN_ATTEMPT", "").strip() or "1"
    if run_id:
        return f"run-{run_id}/attempt-{attempt}"
    return "cli"


def _int_env(environ: Mapping[str, str], name: str) -> int | None:
    raw = environ.get(name, "").strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if value > 0 else None


def build_request(
    snapshot: Mapping[str, Any],
    *,
    observed_at: datetime,
    environ: Mapping[str, str],
    live: bool,
) -> dict[str, Any]:
    return {
        "schema_version": RELEASE_STEWARD_WIRE_SCHEMA_VERSION,
        "observed_at": _iso(observed_at),
        "policy": {
            "merge_authority_enabled": merge_authority_enabled(environ),
            "observe_only": not live,
            "tick_identity": tick_identity(environ),
            "cadence": dict(CADENCE),
        },
        "snapshot": dict(snapshot),
    }


def _ready_value(fact: object) -> Any:
    if isinstance(fact, dict) and fact.get("status") == "ready":
        return fact.get("value")
    return None


def confirmed_versions(snapshot: Mapping[str, Any]) -> set[str]:
    trains = _ready_value(snapshot.get("trains"))
    if not isinstance(trains, list):
        return set()
    versions: set[str] = set()
    for train in trains:
        if (
            isinstance(train, dict)
            and train.get("confirmed")
            and isinstance(train.get("version"), str)
            and train["version"]
        ):
            versions.add(train["version"])
    return versions


def active_train_version(snapshot: Mapping[str, Any]) -> str | None:
    trains = _ready_value(snapshot.get("trains"))
    if not isinstance(trains, list):
        return None
    active = [
        train
        for train in trains
        if isinstance(train, dict)
        and not train.get("confirmed")
        and not train.get("abandoned")
        and not train.get("pre_train_legacy")
        and isinstance(train.get("version"), str)
        and train["version"]
    ]
    if len(active) != 1:
        return None
    version = active[0]["version"]
    return version if isinstance(version, str) else None


def _until_target(
    snapshot: Mapping[str, Any],
    *,
    until_version: str | None,
    baseline: set[str],
) -> str | None:
    if until_version:
        return until_version
    active = active_train_version(snapshot)
    if active is not None:
        return active
    newly = confirmed_versions(snapshot) - baseline
    if len(newly) == 1:
        return next(iter(newly))
    return None


def _target_confirmed(snapshot: Mapping[str, Any], target: str) -> bool:
    return target in confirmed_versions(snapshot)


def _primary_kind(result: Mapping[str, Any]) -> str:
    primary = result.get("primary")
    if isinstance(primary, dict) and isinstance(primary.get("kind"), str):
        return primary["kind"]
    return "unknown"


def result_exit_code(result: Mapping[str, Any]) -> int:
    if result.get("process_exit") == 1:
        return 1
    if _primary_kind(result) == "watcher_broken":
        return 1
    return 0


def _human_action(wrapped: object) -> str:
    if not isinstance(wrapped, dict):
        return "none"
    disposition = wrapped.get("disposition") or "unknown"
    action = wrapped.get("action")
    kind = action.get("kind") if isinstance(action, dict) else None
    operation = wrapped.get("operation")
    op_kind = operation.get("kind") if isinstance(operation, dict) else None
    name = kind or op_kind or "action"
    reason = wrapped.get("reason")
    suffix = f" ({reason})" if isinstance(reason, str) and reason else ""
    return f"{disposition} {name}{suffix}"


def render_human(result: Mapping[str, Any]) -> str:
    kind = _primary_kind(result)
    details = result.get("details") or ""
    lines = [f"state: {kind}"]
    if details:
        lines.append(f"details: {details}")
    evidence = result.get("evidence") or []
    if isinstance(evidence, list) and evidence:
        lines.append("evidence:")
        for item in evidence:
            lines.append(f"  - {item}")
    lines.append(f"train_action: {_human_action(result.get('train_action'))}")
    lines.append(f"escalation: {_human_action(result.get('escalation'))}")
    secondary = result.get("secondary") or []
    if isinstance(secondary, list) and secondary:
        lines.append("secondary:")
        for item in secondary:
            lines.append(f"  - {item}")
    return "\n".join(lines) + "\n"


def render_summary(result: Mapping[str, Any], *, live: bool) -> str:
    kind = _primary_kind(result)
    details = result.get("details") or ""
    lines = [
        "## Release steward",
        "",
        f"- **State:** `{kind}`",
    ]
    if details:
        lines.append(f"- **Details:** {details}")
    lines.append(f"- **Train action:** {_human_action(result.get('train_action'))}")
    lines.append(f"- **Escalation:** {_human_action(result.get('escalation'))}")
    lines.append(f"- **Live mutations:** {'yes' if live else 'no'}")
    evidence = result.get("evidence") or []
    if isinstance(evidence, list) and evidence:
        lines.append("- **Evidence:**")
        for item in evidence:
            lines.append(f"  - {item}")
    lines.append("")
    return "\n".join(lines)


def append_step_summary(
    result: Mapping[str, Any],
    *,
    live: bool,
    environ: Mapping[str, str],
) -> None:
    path = environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    summary = Path(path)
    summary.parent.mkdir(parents=True, exist_ok=True)
    with summary.open("a", encoding="utf-8") as handle:
        handle.write(render_summary(result, live=live))


def emit_result(
    result: Mapping[str, Any],
    options: WatchOptions,
    runtime: WatchRuntime,
) -> None:
    kind = _primary_kind(result)
    print(f"release_watch: {kind}", file=runtime.stderr, flush=True)
    if options.json:
        json.dump(
            dict(result),
            runtime.stdout,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        runtime.stdout.write("\n")
        runtime.stdout.flush()
    else:
        runtime.stdout.write(render_human(result))
        runtime.stdout.flush()
    append_step_summary(result, live=options.live, environ=_environ(runtime))


def _broken(source: str, message: str, remedy: str) -> dict[str, Any]:
    return watcher_broken_result(source=source, message=message, remedy=remedy)


def _passthrough_execute(
    decision: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    live: bool,
) -> dict[str, Any]:
    del request, live
    return dict(decision)


def _ensure_runtime(options: WatchOptions, runtime: WatchRuntime) -> WatchRuntime:
    environ = _environ(runtime)
    if runtime.collect_snapshot is None or runtime.decide is None:
        github = GithubTransport(options.repo, timeout=CLI_GH_TIMEOUT_SECONDS)
        pypi = PypiTransport()
        reader = ReleaseFactsReader(options.repo, github=github, pypi=pypi)

        def collect_snapshot(observed_at: datetime) -> dict[str, Any]:
            health = ReleaseHealthReader(
                reader,
                core_github=GithubTransport(CORE_REPO, timeout=CLI_GH_TIMEOUT_SECONDS),
            )
            return reader.collect_snapshot(observed_at=observed_at, health=health)

        def decide_fn(request: Mapping[str, Any]) -> dict[str, Any]:
            return rust_decide(request)

        def recheck() -> tuple[Mapping[str, Any], Mapping[str, Any]]:
            observed_at = runtime.now()
            snapshot = collect_snapshot(observed_at)
            request = build_request(
                snapshot,
                observed_at=observed_at,
                environ=environ,
                live=options.live,
            )
            return request, decide_fn(request)

        executor = ReleaseWatchActionExecutor(
            recheck=recheck,
            github=github,
            pypi=pypi,
            repo=options.repo,
            run_id=_int_env(environ, "GITHUB_RUN_ID"),
            attempt=_int_env(environ, "GITHUB_RUN_ATTEMPT"),
        )

        def execute(
            decision: Mapping[str, Any],
            request: Mapping[str, Any],
            *,
            live: bool,
        ) -> dict[str, Any]:
            return executor.execute(decision, request, live=live)

        runtime.collect_snapshot = runtime.collect_snapshot or collect_snapshot
        runtime.decide = runtime.decide or decide_fn
        runtime.execute = runtime.execute or execute
    elif runtime.execute is None:
        runtime.execute = _passthrough_execute
    return runtime


def _read_decide(
    options: WatchOptions, runtime: WatchRuntime
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    observed_at = runtime.now()
    try:
        assert runtime.collect_snapshot is not None
        snapshot = runtime.collect_snapshot(observed_at)
    except Exception as exc:
        result = _broken(
            "facts",
            f"{type(exc).__name__}: {exc}",
            "restore GitHub and PyPI read access, then retry the tick",
        )
        return (
            result,
            {},
            build_request(
                {},
                observed_at=observed_at,
                environ=_environ(runtime),
                live=options.live,
            ),
        )
    request = build_request(
        snapshot,
        observed_at=observed_at,
        environ=_environ(runtime),
        live=options.live,
    )
    try:
        assert runtime.decide is not None
        result = dict(runtime.decide(request))
    except Exception as exc:
        result = _broken(
            "sase_core_rs",
            f"{type(exc).__name__}: {exc}",
            "build or install sase-core-rs from the pinned sase-core revision",
        )
    return result, snapshot, request


def _run_once(options: WatchOptions, runtime: WatchRuntime) -> int:
    result, snapshot, request = _read_decide(options, runtime)
    del snapshot
    if options.mode == "tick":
        try:
            assert runtime.execute is not None
            result = dict(runtime.execute(result, request, live=options.live))
        except Exception as exc:
            result = _broken(
                "action_executor",
                f"{type(exc).__name__}: {exc}",
                "re-read remote facts and reconcile before another attempt",
            )
    emit_result(result, options, runtime)
    return result_exit_code(result)


def _run_until_released(options: WatchOptions, runtime: WatchRuntime) -> int:
    assert options.deadline is not None
    assert options.poll is not None
    started = runtime.now()
    deadline_at = started + timedelta(seconds=options.deadline)
    baseline: set[str] | None = None
    target = options.until_version
    while True:
        result, snapshot, _request = _read_decide(options, runtime)
        if result_exit_code(result) == 1:
            emit_result(result, options, runtime)
            return 1
        if baseline is None:
            baseline = confirmed_versions(snapshot)
        if target is None:
            target = _until_target(
                snapshot, until_version=options.until_version, baseline=baseline
            )
        if target is not None and _target_confirmed(snapshot, target):
            emit_result(result, options, runtime)
            return 0
        now = runtime.now()
        if now >= deadline_at:
            print("release_watch: deadline expired", file=runtime.stderr, flush=True)
            emit_result(result, options, runtime)
            return 1
        waiting = target or "a newly confirmed version"
        print(
            f"release_watch: waiting for {waiting}; state={_primary_kind(result)}",
            file=runtime.stderr,
            flush=True,
        )
        remaining = (deadline_at - now).total_seconds()
        runtime.sleep(min(options.poll, max(remaining, 0.0)))


def main(
    argv: Sequence[str] | None = None, *, runtime: WatchRuntime | None = None
) -> int:
    runtime = runtime or WatchRuntime()
    if runtime.environ is None:
        runtime.environ = os.environ
    try:
        options = parse_args(argv)
    except WatchArgumentError as exc:
        print(f"release_watch: {exc}", file=runtime.stderr, flush=True)
        broken = _broken(
            "arguments",
            str(exc),
            "fix the invocation; removed flags are rejected rather than reinterpreted",
        )
        append_step_summary(broken, live=False, environ=_environ(runtime))
        return 2
    except SystemExit as exc:
        return int(exc.code or 0)
    runtime = _ensure_runtime(options, runtime)
    try:
        if options.mode == "until_released":
            return _run_until_released(options, runtime)
        return _run_once(options, runtime)
    except KeyboardInterrupt:
        print("release_watch: interrupted", file=runtime.stderr, flush=True)
        return 130


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    raise SystemExit(main())
