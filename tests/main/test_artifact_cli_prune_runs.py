from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

import sase.artifact_cli.prune_runs as prune_runs_cli
from sase.core.agent_artifact_run_retention import (
    AceRunProtectionSnapshot,
    AceRunRetentionPolicy,
    plan_ace_run_retention,
)


def _args(
    projects_root: Path,
    *,
    apply: bool = False,
    json_output: bool = True,
) -> argparse.Namespace:
    return argparse.Namespace(
        apply=apply,
        index_path=None,
        json=json_output,
        keep_recent_months=2,
        limit=None,
        project=None,
        projects_root=str(projects_root),
    )


def _terminal_run(projects_root: Path, timestamp: str) -> Path:
    path = (
        projects_root
        / "proj"
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    path.mkdir(parents=True)
    (path / "done.json").write_text('{"outcome":"completed"}', encoding="utf-8")
    return path


def test_prune_runs_defaults_to_dry_run(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    old = _terminal_run(projects_root, "20260501000000")
    monkeypatch.setattr(
        prune_runs_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: AceRunProtectionSnapshot(),
    )
    monkeypatch.setattr(
        prune_runs_cli,
        "datetime",
        type(
            "FrozenDatetime",
            (),
            {"now": staticmethod(lambda _tz=None: datetime(2026, 9, 12, 12, 0, 0))},
        ),
    )

    exit_code = prune_runs_cli.handle_prune_runs(_args(projects_root))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["mode"] == "dry_run"
    assert payload["blocked"] is False
    assert payload["plan"]["counts"]["selected"] == 1
    assert Path(payload["plan"]["selected"][0]["artifact_dir"]) == old
    assert old.exists()


def test_prune_runs_apply_refuses_when_protections_are_unavailable(
    monkeypatch: Any,
    capsys: Any,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    _terminal_run(projects_root, "20260501000000")
    monkeypatch.setattr(
        prune_runs_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: AceRunProtectionSnapshot(
            sources_unavailable=("plans sidecar",)
        ),
    )
    monkeypatch.setattr(
        prune_runs_cli,
        "datetime",
        type(
            "FrozenDatetime",
            (),
            {"now": staticmethod(lambda _tz=None: datetime(2026, 9, 12, 12, 0, 0))},
        ),
    )
    called = False

    def _apply(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(prune_runs_cli, "apply_ace_run_retention", _apply)

    exit_code = prune_runs_cli.handle_prune_runs(_args(projects_root, apply=True))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["mode"] == "apply"
    assert payload["blocked"] is True
    assert payload["plan"]["sources_unavailable"] == ["plans sidecar"]
    assert called is False
