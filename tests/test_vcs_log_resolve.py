"""Tests for ``sase vcs log`` repo resolution across project layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import sase.main.utils as main_utils
import sase.workspace_provider.utils as ws_utils
from sase.vcs_log.resolve import resolve_log_repos


@dataclass(frozen=True)
class _FakeLinked:
    name: str
    primary_dir: str
    workspace_dir: str = ""


@dataclass(frozen=True)
class _FakeLinkedResolution:
    repos: tuple[_FakeLinked, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FakeSddStore:
    storage: str
    sdd_dir: Path


@dataclass(frozen=True)
class _FakeRecord:
    repo: str | None


@pytest.fixture()
def project(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A resolvable project with a fixed primary workspace dir."""
    monkeypatch.setattr(
        main_utils,
        "ensure_project_file_and_get_workspace_num",
        lambda *, create_missing=False: ("/proj/sase.sase", 0, "sase"),
    )
    monkeypatch.setattr(
        ws_utils, "parse_workspace_dir", lambda project_file: "/ws/sase"
    )


def _set_linked(
    monkeypatch: pytest.MonkeyPatch, resolution: _FakeLinkedResolution
) -> None:
    import sase.linked_repos as linked_mod

    monkeypatch.setattr(
        linked_mod,
        "resolve_linked_repos_for_project",
        lambda **kwargs: resolution,
    )


def _set_sdd(
    monkeypatch: pytest.MonkeyPatch,
    store: _FakeSddStore,
    record: _FakeRecord | None = None,
) -> None:
    import sase.sdd as sdd_mod

    monkeypatch.setattr(sdd_mod, "resolve_sdd_store", lambda *a, **k: store)
    monkeypatch.setattr(sdd_mod, "read_sdd_store_record", lambda *a, **k: record)


def test_primary_only(monkeypatch: pytest.MonkeyPatch, project: None) -> None:
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(
        monkeypatch,
        _FakeSddStore(storage="in_tree", sdd_dir=Path("/ws/sase/.sase/sdd")),
    )

    resolved = resolve_log_repos(cwd="/ws/sase")

    assert [(r.name, r.path, r.kind) for r in resolved.repos] == [
        ("sase", "/ws/sase", "primary")
    ]
    assert resolved.warnings == []


def test_primary_plus_linked_sorted_by_name(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(
        monkeypatch,
        _FakeLinkedResolution(
            repos=(
                _FakeLinked("sase-telegram", "/ws/telegram"),
                _FakeLinked("sase-core", "/ws/core"),
            )
        ),
    )
    _set_sdd(
        monkeypatch, _FakeSddStore(storage="local", sdd_dir=Path("/ws/sase/.sase/sdd"))
    )

    resolved = resolve_log_repos(cwd="/ws/sase")

    # primary first, then linked sorted by name.
    assert [r.name for r in resolved.repos] == [
        "sase",
        "sase-core",
        "sase-telegram",
    ]
    assert [r.kind for r in resolved.repos] == ["primary", "linked", "linked"]


def test_separate_repo_sdd_included_with_git(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    (sdd_dir / ".git").mkdir(parents=True)
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(
        monkeypatch,
        _FakeSddStore(storage="separate_repo", sdd_dir=sdd_dir),
        record=_FakeRecord(repo="sase-sdd"),
    )

    resolved = resolve_log_repos(cwd="/ws/sase")

    sdd = [r for r in resolved.repos if r.kind == "sdd"]
    assert len(sdd) == 1
    assert sdd[0].name == "sase-sdd"
    assert sdd[0].path == str(sdd_dir)


def test_separate_repo_sdd_skipped_without_git(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    sdd_dir.mkdir()
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(
        monkeypatch,
        _FakeSddStore(storage="separate_repo", sdd_dir=sdd_dir),
    )

    resolved = resolve_log_repos(cwd="/ws/sase")

    assert [r.kind for r in resolved.repos] == ["primary"]


def test_in_tree_sdd_skipped(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    (sdd_dir / ".git").mkdir(parents=True)  # even with a .git, in_tree is skipped
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, _FakeSddStore(storage="in_tree", sdd_dir=sdd_dir))

    resolved = resolve_log_repos(cwd="/ws/sase")

    assert [r.kind for r in resolved.repos] == ["primary"]


def test_current_only_drops_linked_and_sdd(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(
        monkeypatch,
        _FakeLinkedResolution(repos=(_FakeLinked("sase-core", "/ws/core"),)),
    )
    _set_sdd(monkeypatch, _FakeSddStore(storage="separate_repo", sdd_dir=Path("/nope")))

    resolved = resolve_log_repos(cwd="/ws/sase", current_only=True)

    assert [r.name for r in resolved.repos] == ["sase"]


def test_repo_filter_selects_named_repos(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(
        monkeypatch,
        _FakeLinkedResolution(
            repos=(
                _FakeLinked("sase-core", "/ws/core"),
                _FakeLinked("sase-telegram", "/ws/telegram"),
            )
        ),
    )
    _set_sdd(
        monkeypatch, _FakeSddStore(storage="local", sdd_dir=Path("/ws/sase/.sase/sdd"))
    )

    resolved = resolve_log_repos(cwd="/ws/sase", repo_filters=["sase-core"])

    assert [r.name for r in resolved.repos] == ["sase-core"]


def test_repo_filter_unknown_name_warns(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, _FakeSddStore(storage="local", sdd_dir=Path("/x")))

    resolved = resolve_log_repos(cwd="/ws/sase", repo_filters=["nope"])

    assert resolved.repos == []
    assert any("nope" in w for w in resolved.warnings)


def test_sdd_matched_by_literal_sdd_filter(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    (sdd_dir / ".git").mkdir(parents=True)
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(
        monkeypatch,
        _FakeSddStore(storage="separate_repo", sdd_dir=sdd_dir),
        record=_FakeRecord(repo="sase-sdd"),
    )

    resolved = resolve_log_repos(cwd="/ws/sase", repo_filters=["sdd"])

    assert [r.kind for r in resolved.repos] == ["sdd"]


def test_not_in_project_falls_back_to_current_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_utils,
        "ensure_project_file_and_get_workspace_num",
        lambda *, create_missing=False: (None, None, None),
    )
    import sase.vcs_provider as vcs_mod

    monkeypatch.setattr(vcs_mod, "get_vcs_provider", lambda cwd: object())

    resolved = resolve_log_repos(cwd="/some/repo")

    assert [(r.name, r.kind) for r in resolved.repos] == [("repo", "primary")]


def test_not_in_project_and_not_a_repo_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_utils,
        "ensure_project_file_and_get_workspace_num",
        lambda *, create_missing=False: (None, None, None),
    )
    import sase.vcs_provider as vcs_mod

    def _raise(cwd: str) -> object:
        raise RuntimeError("no vcs")

    monkeypatch.setattr(vcs_mod, "get_vcs_provider", _raise)

    resolved = resolve_log_repos(cwd="/tmp/plain")

    assert resolved.repos == []
    assert any(
        "not a recognized" in w.lower() or "vcs" in w.lower() for w in resolved.warnings
    )
