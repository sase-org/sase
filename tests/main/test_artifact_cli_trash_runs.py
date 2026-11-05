from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import sase.artifact_cli.prune_runs as prune_runs_cli
import sase.artifact_cli.trash as trash_cli
from sase.core.agent_artifact_run_retention import AceRunProtectionSnapshot
from sase.core.disk_footprint_reap_artifacts import artifact_run_reap_step
from sase.core.paths import sase_home


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
    (path / "payload.txt").write_text(f"run {timestamp}\n", encoding="utf-8")
    return path


def _quarantine_batch(projects_root: Path, monkeypatch: Any) -> str:
    monkeypatch.setattr(
        prune_runs_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: AceRunProtectionSnapshot(),
    )
    args = argparse.Namespace(
        apply=True,
        index_path=None,
        json=True,
        keep_recent_months=2,
        limit=None,
        notify=False,
        project=None,
        projects_root=str(projects_root),
        snapshot=None,
    )
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = prune_runs_cli.handle_prune_runs(args)
    assert exit_code == 0
    payload = json.loads(buffer.getvalue())
    assert payload["execution"]["quarantined"] == 1
    return str(payload["execution"]["batch_id"])


def _trash_args(
    subcommand: str, projects_root: Path | None = None, **overrides: object
) -> argparse.Namespace:
    args = argparse.Namespace(
        trash_subcommand=subcommand,
        json=True,
        limit=50,
        all=False,
        reference="",
        projects_root=None if projects_root is None else str(projects_root),
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_trash_list_shows_run_batches(
    monkeypatch: Any, capsys: Any, tmp_path: Path
) -> None:
    projects_root = tmp_path / "projects"
    _terminal_run(projects_root, "20260501000000")
    batch_id = _quarantine_batch(projects_root, monkeypatch)

    exit_code = trash_cli.handle_trash(_trash_args("list"))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["run_batches"]
    batch = next(b for b in payload["run_batches"] if b["id"] == batch_id)
    assert batch["run_count"] == 1
    assert batch["projects"] == ["proj"]
    assert batch["status"] in ("complete", "partial")


def test_trash_restore_runs_batch_is_byte_identical(
    monkeypatch: Any, capsys: Any, tmp_path: Path
) -> None:
    projects_root = tmp_path / "projects"
    run_dir = _terminal_run(projects_root, "20260501000000")
    before = {
        path.name: path.read_bytes()
        for path in sorted(run_dir.iterdir())
        if path.is_file()
    }
    batch_id = _quarantine_batch(projects_root, monkeypatch)
    assert not run_dir.exists()

    exit_code = trash_cli.handle_trash(
        _trash_args("restore", projects_root, reference=f"runs:{batch_id}")
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["restored"] == 1
    assert payload["conflicts"] == 0
    assert payload["reindexed"] >= 1
    after = {
        path.name: path.read_bytes()
        for path in sorted(run_dir.iterdir())
        if path.is_file()
    }
    assert after == before


def test_trash_restore_rejects_bad_batch_id(capsys: Any, tmp_path: Path) -> None:
    exit_code = trash_cli.handle_trash(
        _trash_args("restore", reference="runs:../../etc")
    )

    assert exit_code == 2
    assert "invalid run-trash batch id" in capsys.readouterr().err


def test_trash_purge_restores_newly_protected_run(
    monkeypatch: Any, capsys: Any, tmp_path: Path
) -> None:
    projects_root = tmp_path / "projects"
    run_dir = _terminal_run(projects_root, "20260501000000")
    batch_id = _quarantine_batch(projects_root, monkeypatch)
    assert not run_dir.exists()

    # The quarantined run gains an index reference before the purge runs.
    monkeypatch.setattr(
        trash_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: AceRunProtectionSnapshot(
            protected_timestamps=frozenset({"20260501000000"})
        ),
    )

    exit_code = trash_cli.handle_trash(_trash_args("purge", projects_root, all=True))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    run_result = payload["run_batches"]
    assert run_result["restored"] == 1
    assert batch_id in run_result["purged_batches"]
    assert run_dir.exists()
    assert (run_dir / "payload.txt").read_text(
        encoding="utf-8"
    ) == "run 20260501000000\n"


def test_trash_purge_blocked_when_protections_unavailable(
    monkeypatch: Any, capsys: Any, tmp_path: Path
) -> None:
    projects_root = tmp_path / "projects"
    run_dir = _terminal_run(projects_root, "20260501000000")
    _quarantine_batch(projects_root, monkeypatch)

    monkeypatch.setattr(
        trash_cli,
        "collect_ace_run_retention_protections",
        lambda **_kwargs: AceRunProtectionSnapshot(
            sources_unavailable=("plans sidecar",)
        ),
    )

    exit_code = trash_cli.handle_trash(_trash_args("purge", projects_root, all=True))

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["run_batches"]["blocked_reason"] == "protection_unavailable"
    assert payload["run_batches"]["purged"] == 0
    assert not run_dir.exists()


def test_disk_reap_apply_moves_no_run() -> None:
    projects_root = sase_home() / "projects"
    run_dir = _terminal_run(projects_root, "20260501000000")

    step = artifact_run_reap_step(apply=True, project=None)

    assert run_dir.exists()
    assert step.mode in ("blocked", "error", "dry_run", "apply")
    if step.mode == "apply":
        assert "removed_runs" in (step.details or {})
        assert (step.details or {})["removed_runs"] == 0
