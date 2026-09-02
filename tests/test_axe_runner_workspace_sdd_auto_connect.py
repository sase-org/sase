"""Launch workspace prep must auto-connect the SDD store before the strict clone."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.axe.runner_workspace import prepare_launch_workspace_repos
from sase.sdd.store import SddMaterializationError


def _stub_eviction_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.linked_repos.clear_workspace_repos",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.axe.runner_workspace._protect_unpushed_sidecar_bead_commits",
        lambda *_args, **_kwargs: True,
    )


def test_auto_connect_runs_before_the_strict_workspace_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_eviction_guard(monkeypatch)
    workspace_dir = tmp_path / "repo_2"
    workspace_dir.mkdir()
    calls: list[str] = []

    def fake_auto_connect(_workspace_dir: str, _workspace_num: int) -> bool:
        calls.append("auto_connect")
        return False

    def fake_ensure_clone(_workspace_dir: str, _workspace_num: int, **_kwargs: object):
        calls.append("ensure_clone")

    monkeypatch.setattr("sase.sdd.store.auto_connect_sdd_store", fake_auto_connect)
    monkeypatch.setattr("sase.sdd.store.ensure_workspace_sdd_clone", fake_ensure_clone)

    prepare_launch_workspace_repos(str(workspace_dir), 2)

    assert calls == ["auto_connect", "ensure_clone"]


def test_auto_connect_materialization_error_propagates_before_the_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_eviction_guard(monkeypatch)
    workspace_dir = tmp_path / "repo_2"
    workspace_dir.mkdir()

    def failing_auto_connect(_workspace_dir: str, _workspace_num: int) -> bool:
        raise SddMaterializationError("boom")

    monkeypatch.setattr("sase.sdd.store.auto_connect_sdd_store", failing_auto_connect)
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        lambda *_args, **_kwargs: pytest.fail(
            "must not attempt the strict clone after a connect failure"
        ),
    )

    with pytest.raises(SddMaterializationError, match="boom"):
        prepare_launch_workspace_repos(str(workspace_dir), 2)


def test_newly_connected_store_prints_a_status_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_eviction_guard(monkeypatch)
    workspace_dir = tmp_path / "repo_2"
    workspace_dir.mkdir()

    monkeypatch.setattr("sase.sdd.store.auto_connect_sdd_store", lambda *_a: True)
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        lambda *_args, **_kwargs: None,
    )

    prepare_launch_workspace_repos(str(workspace_dir), 2)

    assert "Connected existing SDD sidecars for first use on this machine" in (
        capsys.readouterr().out
    )


def test_already_connected_store_does_not_reprint_the_status_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _stub_eviction_guard(monkeypatch)
    workspace_dir = tmp_path / "repo_2"
    workspace_dir.mkdir()
    primary = tmp_path / "repo"

    monkeypatch.setattr(
        "sase.sdd._paths.get_primary_workspace_dir",
        lambda _workspace, _num: str(primary),
    )
    monkeypatch.setattr(
        "sase.sdd._store_records.read_sdd_store_record",
        lambda _primary: object(),
    )
    monkeypatch.setattr(
        "sase.sdd._store_records.is_materialized_record",
        lambda _record: True,
    )
    monkeypatch.setattr("sase.sdd.store.auto_connect_sdd_store", lambda *_a: True)
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        lambda *_args, **_kwargs: None,
    )

    prepare_launch_workspace_repos(str(workspace_dir), 2)

    assert "Connected existing SDD sidecars" not in capsys.readouterr().out
