"""Builtin external PR mirror chop coverage."""

from __future__ import annotations

from pathlib import Path

from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
from sase.external_mirror.report import MirrorReport
from sase.scripts import sase_chop_external_pr_mirror as chop


def _runtime(
    tmp_path: Path,
    *,
    target: dict[str, object] | None,
    dry_run: bool = False,
) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="external_pr_mirror",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="checks",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
            target=target,
            dry_run=dry_run,
        ),
        log=ChopLogger(),
    )


def test_external_pr_mirror_fails_closed_without_workspace(tmp_path: Path) -> None:
    result = chop._run(_runtime(tmp_path, target={"project": "proj", "name": "Proj"}))

    assert result.status == "check_error"
    assert result.reason == "missing_target_workspace"
    assert result.counters["errors"] == 1


def test_external_pr_mirror_returns_sync_report(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def _sync(**kwargs: object) -> MirrorReport:
        calls.append(kwargs)
        return MirrorReport(fetched=2, seen=2, created=1)

    monkeypatch.setattr(chop, "get_vcs_provider", lambda workspace_dir: object())
    monkeypatch.setattr(chop, "sync_external_pull_requests", _sync)

    result = chop._run(
        _runtime(
            tmp_path,
            target={
                "project": "proj",
                "name": "Proj",
                "workspace_dir": "/repo",
            },
            dry_run=True,
        )
    )

    assert result.status == "ok"
    assert result.counters["fetched"] == 2
    assert result.counters["created"] == 1
    assert calls[0]["project_key"] == "proj"
    assert calls[0]["workspace_dir"] == "/repo"
    assert calls[0]["dry_run"] is True


def test_external_pr_mirror_respects_backoff(monkeypatch, tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    from sase.external_mirror.pr_sync import KIND
    from sase.external_mirror.state import (
        BackoffEntry,
        pr_mirror_state_dir,
        write_backoff_state,
    )

    write_backoff_state(
        pr_mirror_state_dir(),
        KIND,
        {
            "proj": BackoffEntry(
                failures=1,
                next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        },
    )
    monkeypatch.setattr(chop, "get_vcs_provider", lambda _workspace_dir: object())

    result = chop._run(
        _runtime(
            tmp_path,
            target={
                "project": "proj",
                "name": "Proj",
                "workspace_dir": "/repo",
            },
        )
    )

    assert result.status == "no_op"
    assert result.reason == "backoff"
    assert result.counters["fetched"] == 0
