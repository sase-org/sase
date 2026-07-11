"""Tests for provider-owned ``sase sdd init`` handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.sdd_handler import handle_sdd_command
from sase.sdd.store import SddMaterializationError, SddStore
from tests.main.sdd_handler_helpers import make_args, mark_tmp_path_as_project

__all__ = ["mark_tmp_path_as_project"]

pytestmark = pytest.mark.usefixtures("mark_tmp_path_as_project")


def _local_store(project: Path) -> SddStore:
    sdd_dir = project / ".sase" / "sdd"
    return SddStore(storage="local", sdd_dir=sdd_dir, repo_root=sdd_dir)


def test_init_materializes_provider_store_without_changing_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[Path, int]] = []

    def materialize(path: Path, workspace_num: int) -> SddStore:
        calls.append((path, workspace_num))
        return _local_store(path)

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", materialize)
    config = tmp_path / "sase.yml"
    original = "is_sase_managed: true\n"
    config.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert calls == [(tmp_path, 1)]
    assert config.read_text(encoding="utf-8") == original
    readme = tmp_path / ".sase" / "sdd" / "README.md"
    assert readme.is_file()
    assert str(readme) in capsys.readouterr().out


def test_init_preserves_existing_retired_config_verbatim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "sase.yml"
    original = (
        "is_sase_managed: true\nsdd:\n  storage: local\n  version_controlled: true\n"
    )
    config.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda path, workspace_num: _local_store(path),
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 0
    assert config.read_text(encoding="utf-8") == original


def test_init_fails_before_generating_files_when_materialization_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(_path: Path, _workspace_num: int) -> SddStore:
        raise SddMaterializationError("provider unavailable")

    monkeypatch.setattr("sase.sdd.store.materialize_sdd_store", fail)
    (tmp_path / "sase.yml").write_text("is_sase_managed: true\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        handle_sdd_command(make_args(sdd_subcommand="init", path=str(tmp_path)))

    assert excinfo.value.code == 1
    assert "provider unavailable" in capsys.readouterr().err
    assert not (tmp_path / ".sase" / "sdd").exists()
