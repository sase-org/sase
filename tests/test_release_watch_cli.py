"""CLI contract for the replacement release-watch entry point."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from tests._release_steward_fixtures import releasable_request, releasable_snapshot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import _release_watch as watch  # noqa: E402
from _release_watch_decide import watcher_broken_result  # noqa: E402


NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)


def _decision(
    kind: str = "nothing_to_release",
    *,
    details: str = "idle",
    process_exit: int = 0,
    train_action: dict[str, Any] | None = None,
    evidence: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "primary": {"kind": kind},
        "details": details,
        "evidence": evidence or ["https://example.test/evidence"],
        "blocker_started_at": None,
        "blocker_duration_uncertain": False,
        "train_action": train_action,
        "escalation": None,
        "secondary": [],
        "process_exit": process_exit,
    }


class FakeClock:
    def __init__(self, start: datetime = NOW) -> None:
        self.current = start

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def _runtime(
    *,
    snapshot: dict[str, Any] | None = None,
    snapshots: list[dict[str, Any]] | None = None,
    decision: dict[str, Any] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    execute: Any = None,
    environ: dict[str, str] | None = None,
    clock: FakeClock | None = None,
) -> tuple[watch.WatchRuntime, StringIO, StringIO]:
    stdout = StringIO()
    stderr = StringIO()
    clock = clock or FakeClock()
    queued_snapshots = list(snapshots or [snapshot or releasable_snapshot()])
    queued_decisions = list(decisions or [decision or _decision()])
    seen_requests: list[dict[str, Any]] = []
    executed: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    def collect(_observed_at: datetime) -> dict[str, Any]:
        if not queued_snapshots:
            return dict(queued_snapshots[-1] if snapshots else releasable_snapshot())
        if len(queued_snapshots) == 1:
            return dict(queued_snapshots[0])
        return dict(queued_snapshots.pop(0))

    def decide(request: dict[str, Any]) -> dict[str, Any]:
        seen_requests.append(dict(request))
        if not queued_decisions:
            return dict(_decision())
        if len(queued_decisions) == 1:
            return dict(queued_decisions[0])
        return dict(queued_decisions.pop(0))

    def default_execute(
        result: dict[str, Any], request: dict[str, Any], *, live: bool
    ) -> dict[str, Any]:
        executed.append((dict(result), dict(request), live))
        copied = dict(result)
        if live and isinstance(copied.get("train_action"), dict):
            copied["train_action"] = {
                **copied["train_action"],
                "disposition": "executed",
            }
        return copied

    runtime = watch.WatchRuntime(
        collect_snapshot=collect,
        decide=decide,
        execute=execute or default_execute,
        now=clock.now,
        sleep=clock.sleep,
        stdout=stdout,
        stderr=stderr,
        environ=environ or {},
    )
    runtime.seen_requests = seen_requests  # type: ignore[attr-defined]
    runtime.executed = executed  # type: ignore[attr-defined]
    return runtime, stdout, stderr


def test_unknown_removed_flags_are_rejected() -> None:
    for argv in (
        ["--close-bead", "sase-1"],
        ["--fixed-sha", "a" * 40],
        ["--dry-run"],
        ["--no-dispatch"],
        ["--verdict-file", "/tmp/x"],
        ["--max-red-full-ci", "2"],
    ):
        runtime, _stdout, stderr = _runtime()
        assert watch.main(argv, runtime=runtime) == 2
        assert "release_watch:" in stderr.getvalue()


def test_mode_conflicts_and_live_without_tick() -> None:
    runtime, _, stderr = _runtime()
    assert watch.main(["--once", "--tick"], runtime=runtime) == 2
    assert "mutually exclusive" in stderr.getvalue()

    runtime, _, stderr = _runtime()
    assert watch.main(["--live"], runtime=runtime) == 2
    assert "--live is valid only with --tick" in stderr.getvalue()

    runtime, _, stderr = _runtime()
    assert watch.main(["--once", "--live"], runtime=runtime) == 2

    runtime, _, stderr = _runtime()
    assert watch.main(["--deadline", "1m"], runtime=runtime) == 2
    assert "--deadline is only valid with --until-released" in stderr.getvalue()


def test_help_lists_short_aliases_alphabetically() -> None:
    captured = StringIO()
    with redirect_stdout(captured), pytest.raises(SystemExit) as exc:
        watch.parse_args(["--help"])
    assert exc.value.code == 0
    text = captured.getvalue()
    listed: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-") or "--" not in stripped:
            continue
        tokens = stripped.replace(",", " ").split()
        shorts = [
            token
            for token in tokens
            if token.startswith("-") and not token.startswith("--")
        ]
        longs = [token for token in tokens if token.startswith("--")]
        if shorts and longs:
            listed.append((shorts[0], longs[0]))
    listed = [pair for pair in listed if pair[1] != "--help"]
    expected = [
        ("-d", "--deadline"),
        ("-j", "--json"),
        ("-l", "--live"),
        ("-o", "--once"),
        ("-p", "--poll"),
        ("-r", "--repo"),
        ("-t", "--tick"),
        ("-u", "--until-released"),
    ]
    assert listed == expected
    assert [long for _short, long in listed] == sorted(long for _short, long in listed)


def test_json_purity_and_default_once_is_read_only() -> None:
    runtime, stdout, stderr = _runtime(decision=_decision("releasable"))
    code = watch.main(["--json"], runtime=runtime)
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["primary"]["kind"] == "releasable"
    assert stdout.getvalue().strip() == json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert "releasable" in stderr.getvalue()
    assert runtime.executed == []  # type: ignore[attr-defined]
    request = runtime.seen_requests[0]  # type: ignore[attr-defined]
    assert request["policy"]["observe_only"] is True
    assert request["policy"]["merge_authority_enabled"] is False


def test_tick_live_executes_and_observe_tick_does_not() -> None:
    action = {
        "action": {"kind": "dispatch_publish_metadata"},
        "disposition": "proposed",
        "key": "metadata",
        "preconditions": [],
        "argv": ["gh", "workflow", "run", "publish.yml"],
        "reason": "refresh",
    }
    runtime, stdout, _stderr = _runtime(
        decision=_decision("releasable", train_action=action)
    )
    assert watch.main(["--tick", "--json"], runtime=runtime) == 0
    assert json.loads(stdout.getvalue())["train_action"]["disposition"] == "proposed"
    assert runtime.executed[0][2] is False  # type: ignore[attr-defined]

    runtime, stdout, _stderr = _runtime(
        decision=_decision("releasable", train_action=action)
    )
    assert watch.main(["--tick", "--live", "--json"], runtime=runtime) == 0
    payload = json.loads(stdout.getvalue())
    assert payload["train_action"]["disposition"] == "executed"
    assert runtime.executed[0][2] is True  # type: ignore[attr-defined]
    request = runtime.seen_requests[0]  # type: ignore[attr-defined]
    assert request["policy"]["observe_only"] is False


def test_merge_authority_requires_literal_true() -> None:
    runtime, _stdout, _stderr = _runtime(
        environ={"RELEASE_STEWARD_MERGE_ENABLED": "TRUE"}
    )
    watch.main(["--json"], runtime=runtime)
    assert runtime.seen_requests[0]["policy"]["merge_authority_enabled"] is False  # type: ignore[attr-defined]

    runtime, _stdout, _stderr = _runtime(
        environ={"RELEASE_STEWARD_MERGE_ENABLED": "true"}
    )
    watch.main(["--json"], runtime=runtime)
    assert runtime.seen_requests[0]["policy"]["merge_authority_enabled"] is True  # type: ignore[attr-defined]


def test_fatal_execute_error_emits_typed_failure() -> None:
    def exploding(
        decision: dict[str, Any], request: dict[str, Any], *, live: bool
    ) -> dict[str, Any]:
        del decision, request, live
        raise RuntimeError("ack lost")

    runtime, stdout, stderr = _runtime(execute=exploding)
    code = watch.main(["--tick", "--live", "--json"], runtime=runtime)
    assert code == 1
    payload = json.loads(stdout.getvalue())
    assert payload["primary"]["kind"] == "watcher_broken"
    assert payload["process_exit"] == 1
    assert "ack lost" in payload["details"]
    assert "watcher_broken" in stderr.getvalue()
    assert payload["train_action"] is None


def test_until_released_waits_for_new_target_not_historical() -> None:
    historical = releasable_snapshot()
    historical["trains"] = {
        "status": "ready",
        "value": [
            {
                "candidate_id": "old",
                "version": "0.40.0",
                "tag": "v0.40.0",
                "sha": "a" * 40,
                "generation": 1,
                "confirmed": True,
                "abandoned": False,
                "pre_train_legacy": False,
            }
        ],
    }
    released = releasable_snapshot()
    released["trains"] = {
        "status": "ready",
        "value": [
            historical["trains"]["value"][0],
            {
                "candidate_id": "new",
                "version": "0.51.0",
                "tag": "v0.51.0",
                "sha": "b" * 40,
                "generation": 1,
                "confirmed": True,
                "abandoned": False,
                "pre_train_legacy": False,
            },
        ],
    }
    clock = FakeClock()
    runtime, stdout, stderr = _runtime(
        snapshots=[historical, historical, released],
        decisions=[
            _decision("nothing_to_release"),
            _decision("nothing_to_release"),
            _decision("released", details="0.51.0 confirmed"),
        ],
        clock=clock,
    )
    code = watch.main(
        ["--until-released", "--poll", "1s", "--deadline", "10s", "--json"],
        runtime=runtime,
    )
    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["primary"]["kind"] == "released"
    assert "waiting for" in stderr.getvalue()


def test_until_released_deadline_is_nonzero_without_claiming_success() -> None:
    snapshot = releasable_snapshot()
    snapshot["trains"] = {"status": "ready", "value": []}
    clock = FakeClock()
    runtime, stdout, stderr = _runtime(
        snapshot=snapshot,
        decision=_decision("nothing_to_release"),
        clock=clock,
    )
    code = watch.main(
        ["--until-released", "0.99.0", "--poll", "1s", "--deadline", "2s", "--json"],
        runtime=runtime,
    )
    assert code == 1
    assert "deadline expired" in stderr.getvalue()
    payload = json.loads(stdout.getvalue())
    assert payload["primary"]["kind"] == "nothing_to_release"


def test_watcher_broken_is_nonzero() -> None:
    runtime, stdout, _stderr = _runtime(
        decision=watcher_broken_result(
            source="pypi", message="503", remedy="retry PyPI"
        )
    )
    code = watch.main(["--json"], runtime=runtime)
    assert code == 1
    payload = json.loads(stdout.getvalue())
    assert payload["primary"]["kind"] == "watcher_broken"


def test_step_summary_includes_failures(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    runtime, _stdout, _stderr = _runtime(
        decision=watcher_broken_result(
            source="gh", message="auth", remedy="restore SASE_RELEASE_TOKEN"
        ),
        environ={"GITHUB_STEP_SUMMARY": str(summary)},
    )
    assert watch.main(["--json"], runtime=runtime) == 1
    text = summary.read_text(encoding="utf-8")
    assert "## Release steward" in text
    assert "`watcher_broken`" in text
    assert "Live mutations:** no" in text


def test_tick_identity_uses_github_run_env() -> None:
    runtime, _stdout, _stderr = _runtime(
        environ={"GITHUB_RUN_ID": "99", "GITHUB_RUN_ATTEMPT": "2"}
    )
    watch.main(["--json"], runtime=runtime)
    assert runtime.seen_requests[0]["policy"]["tick_identity"] == (  # type: ignore[attr-defined]
        "run-99/attempt-2"
    )


def test_real_binding_round_trip_when_installed() -> None:
    sase_core_rs = pytest.importorskip("sase_core_rs")
    if not hasattr(sase_core_rs, "release_steward_decide"):
        pytest.skip("installed sase_core_rs predates release_steward_decide")
    stdout = StringIO()
    stderr = StringIO()
    request = releasable_request()

    def collect(_observed_at: datetime) -> dict[str, Any]:
        return dict(request["snapshot"])

    runtime = watch.WatchRuntime(
        collect_snapshot=collect,
        decide=watch.rust_decide,
        execute=lambda decision, _request, *, live: dict(decision),
        now=lambda: NOW,
        sleep=lambda _seconds: None,
        stdout=stdout,
        stderr=stderr,
        environ={"RELEASE_STEWARD_MERGE_ENABLED": "true"},
    )
    code = watch.main(["--once", "--json"], runtime=runtime)
    payload = json.loads(stdout.getvalue())
    assert code == 0
    assert payload["primary"]["kind"] == "releasable"
    assert payload["process_exit"] == 0
    assert payload.get("train_action", {}).get("disposition") != "executed"
