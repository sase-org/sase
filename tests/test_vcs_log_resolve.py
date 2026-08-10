"""Tests for ``sase stitch log`` repo resolution across project layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import sase.main.utils as main_utils
import sase.vcs_log.resolve as resolve_module
import sase.workspace_provider.utils as ws_utils
from sase.vcs_log.resolve import resolve_log_repos


@dataclass(frozen=True)
class _FakeLinked:
    name: str
    primary_dir: str
    workspace_dir: str = ""
    kind: str = "linked"


@dataclass(frozen=True)
class _FakeLinkedResolution:
    repos: tuple[_FakeLinked, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FakeRecord:
    repo: str | None


@pytest.fixture()
def project(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """A resolvable project with a fixed primary workspace dir."""
    monkeypatch.setattr(
        main_utils,
        "ensure_project_file_and_get_workspace_num",
        lambda *, create_missing=False: ("/proj/sase.sase", 0, "gh_sase-org__sase"),
    )
    monkeypatch.setattr(
        ws_utils, "parse_workspace_dir", lambda project_file: "/ws/sase"
    )
    monkeypatch.setattr(
        resolve_module,
        "project_display_name_for",
        lambda key: "sase" if key == "gh_sase-org__sase" else key,
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
    clone: Path | None,
    record: _FakeRecord | None = None,
) -> None:
    import sase.sdd as sdd_mod

    monkeypatch.setattr(sdd_mod, "materialized_sdd_clone", lambda *a, **k: clone)
    monkeypatch.setattr(sdd_mod, "read_sdd_store_record", lambda *a, **k: record)


def test_primary_only(monkeypatch: pytest.MonkeyPatch, project: None) -> None:
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, None)

    resolved = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    assert [(r.name, r.path, r.kind) for r in resolved.repos] == [
        ("sase", "/ws/sase", "primary")
    ]
    assert resolved.repos[0].plan_workspaces[0].workspace_dir == "/ws/sase"
    assert resolved.warnings == []


def test_primary_name_falls_back_to_project_key(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    monkeypatch.setattr(resolve_module, "project_display_name_for", lambda key: key)
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, None)

    resolved = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    assert [(r.name, r.path, r.kind) for r in resolved.repos] == [
        ("gh_sase-org__sase", "/ws/sase", "primary")
    ]


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
    _set_sdd(monkeypatch, None)

    resolved = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    # primary first, then linked sorted by name.
    assert [r.name for r in resolved.repos] == [
        "sase",
        "sase-core",
        "sase-telegram",
    ]
    assert [r.kind for r in resolved.repos] == ["primary", "linked", "linked"]


def test_modern_sidecars_keep_identity_and_require_opt_in(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(
        monkeypatch,
        _FakeLinkedResolution(
            repos=(
                _FakeLinked("sase-core", "/ws/core"),
                _FakeLinked("plans", "/ws/plans", kind="sidecar"),
                _FakeLinked("research", "/ws/research", kind="sidecar"),
            )
        ),
    )
    _set_sdd(monkeypatch, None)

    default = resolve_log_repos(cwd="/ws/sase")
    included = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    assert [(repo.name, repo.kind) for repo in default.repos] == [
        ("sase", "primary"),
        ("sase-core", "linked"),
    ]
    assert [(repo.name, repo.kind) for repo in included.repos] == [
        ("sase", "primary"),
        ("sase-core", "linked"),
        ("plans", "sidecar"),
        ("research", "sidecar"),
    ]


def test_repo_filter_cannot_select_hidden_modern_sidecar(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(
        monkeypatch,
        _FakeLinkedResolution(
            repos=(_FakeLinked("plans", "/ws/plans", kind="sidecar"),)
        ),
    )
    _set_sdd(monkeypatch, None)

    default = resolve_log_repos(cwd="/ws/sase", repo_filters=["plans"])
    included = resolve_log_repos(
        cwd="/ws/sase",
        repo_filters=["plans"],
        include_sidecars=True,
    )

    assert default.repos == []
    assert default.warnings == ["--repo 'plans' did not match any repository"]
    assert [(repo.name, repo.kind) for repo in included.repos] == [("plans", "sidecar")]


def test_materialized_sdd_clone_is_included_with_record_label(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    (sdd_dir / ".git").mkdir(parents=True)
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(
        monkeypatch,
        sdd_dir,
        record=_FakeRecord(repo="sase-sdd"),
    )

    default = resolve_log_repos(cwd="/ws/sase")
    resolved = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    assert [r.kind for r in default.repos] == ["primary"]
    sdd = [r for r in resolved.repos if r.kind == "sidecar"]
    assert len(sdd) == 1
    assert sdd[0].name == "sase-sdd"
    assert sdd[0].path == str(sdd_dir)


def test_materialized_sdd_clone_uses_fallback_label_without_repo_name(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    sdd_dir.mkdir()
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, sdd_dir)

    resolved = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    assert [r.kind for r in resolved.repos] == ["primary", "sidecar"]


def test_materialized_sdd_record_with_unusable_clone_is_skipped(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, None, record=_FakeRecord(repo="sase-sdd"))

    resolved = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    assert [r.kind for r in resolved.repos] == ["primary"]


def test_stale_non_materialized_sdd_clone_is_skipped_without_warning(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    (sdd_dir / ".git").mkdir(parents=True)
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, None)

    resolved = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    assert [r.kind for r in resolved.repos] == ["primary"]
    assert resolved.warnings == []


def test_current_only_drops_linked_and_sdd(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    _set_linked(
        monkeypatch,
        _FakeLinkedResolution(repos=(_FakeLinked("sase-core", "/ws/core"),)),
    )
    sdd_dir = tmp_path / "sdd"
    sdd_dir.mkdir()
    _set_sdd(monkeypatch, sdd_dir)

    resolved = resolve_log_repos(
        cwd="/ws/sase", current_only=True, include_sidecars=True
    )

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
    _set_sdd(monkeypatch, None)

    resolved = resolve_log_repos(cwd="/ws/sase", repo_filters=["sase-core"])

    assert [r.name for r in resolved.repos] == ["sase-core"]


def test_repo_filter_unknown_name_warns(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, None)

    resolved = resolve_log_repos(cwd="/ws/sase", repo_filters=["nope"])

    assert resolved.repos == []
    assert any("nope" in w for w in resolved.warnings)


def test_repo_exclusions_are_case_insensitive_and_win_over_inclusions(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(
        monkeypatch,
        _FakeLinkedResolution(repos=(_FakeLinked("sase-core", "/ws/core"),)),
    )
    _set_sdd(monkeypatch, None)

    resolved = resolve_log_repos(
        cwd="/ws/sase",
        repo_filters=["SASE-CORE"],
        exclude_repo_filters=["sase-core"],
    )

    assert resolved.repos == []
    assert resolved.warnings == []


def test_unmatched_repo_exclusion_warns_without_hiding_other_repos(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, None)

    resolved = resolve_log_repos(
        cwd="/ws/sase",
        exclude_repo_filters=["missing"],
    )

    assert [repo.name for repo in resolved.repos] == ["sase"]
    assert resolved.warnings == ["-repo 'missing' did not match any repository"]


def test_sdd_filter_requires_sdd_scope(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    (sdd_dir / ".git").mkdir(parents=True)
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(
        monkeypatch,
        sdd_dir,
        record=_FakeRecord(repo="sase-sdd"),
    )

    default = resolve_log_repos(cwd="/ws/sase", repo_filters=["sdd"])
    resolved = resolve_log_repos(
        cwd="/ws/sase", repo_filters=["sdd"], include_sidecars=True
    )

    assert default.repos == []
    assert default.warnings == ["--repo 'sdd' did not match any repository"]
    assert [r.kind for r in resolved.repos] == ["sidecar"]


def test_sdd_exclusion_applies_only_to_the_enabled_sdd_scope(
    monkeypatch: pytest.MonkeyPatch, project: None, tmp_path: Path
) -> None:
    sdd_dir = tmp_path / "sdd"
    sdd_dir.mkdir()
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    _set_sdd(monkeypatch, sdd_dir, record=_FakeRecord(repo="sase-sdd"))

    without_scope = resolve_log_repos(cwd="/ws/sase", exclude_repo_filters=["sdd"])
    with_scope = resolve_log_repos(
        cwd="/ws/sase",
        include_sidecars=True,
        exclude_repo_filters=["sdd"],
    )

    assert [repo.kind for repo in without_scope.repos] == ["primary"]
    assert without_scope.warnings == ["-repo 'sdd' did not match any repository"]
    assert [repo.kind for repo in with_scope.repos] == ["primary"]
    assert with_scope.warnings == []


def test_excluded_sdd_store_is_not_probed_or_warned(
    monkeypatch: pytest.MonkeyPatch, project: None
) -> None:
    _set_linked(monkeypatch, _FakeLinkedResolution(repos=()))
    import sase.sdd as sdd_mod

    calls: list[tuple[str, int]] = []

    def fail_sdd(primary_dir: str) -> object:
        calls.append((primary_dir, 0))
        raise RuntimeError("broken SDD metadata")

    monkeypatch.setattr(sdd_mod, "materialized_sdd_clone", fail_sdd)

    default = resolve_log_repos(cwd="/ws/sase")
    included = resolve_log_repos(cwd="/ws/sase", include_sidecars=True)

    assert calls == [("/ws/sase", 0)]
    assert default.warnings == []
    assert included.warnings == ["sdd store could not be resolved: broken SDD metadata"]


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
    assert resolved.repos[0].plan_workspaces[0].workspace_dir == "/some/repo"


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
