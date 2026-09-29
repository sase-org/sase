"""Coverage for the ``repos.linked[].revision_pin`` pin-follow behavior."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from sase._linked_repo_config import (
    normalize_revision_pin,
    revision_pin_for_entry,
)
from sase._linked_repo_env import ResolvedLinkedRepo
from sase._repo_inventory_models import RepoRecord
from sase.doctor import checks_config_repos as repos_checks
from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_revision_pin import (
    maybe_write_revision_pin,
    order_pinned_siblings_first,
    without_pin_protected,
)
from sase.finalizers.commit_types import StitchCommandResult
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult


def _repo(name: str, path: Path, kind: str) -> DirtyRepo:
    return DirtyRepo(
        name=name,
        path=str(path),
        changed_files=("dirty.txt",),
        kind=kind,  # type: ignore[arg-type]
    )


def _decisions(*repos: DirtyRepo) -> dict[str, dict[str, Any]]:
    return {
        repository_decision_id(repo): {"action": "commit", "message": "feat: x"}
        for repo in repos
    }


# Config parsing and validation.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sase-core-revision.txt", "sase-core-revision.txt"),
        ("./sase-core-revision.txt", "sase-core-revision.txt"),
        ("sub/dir/pin.txt", "sub/dir/pin.txt"),
        ("a/b/../c.txt", "a/c.txt"),
    ],
)
def test_normalize_revision_pin_accepts_relative_paths(raw: str, expected: str) -> None:
    assert normalize_revision_pin(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["/abs/pin.txt", "~/pin.txt", "../escape.txt", "a/../../escape.txt", "", "   "],
)
def test_normalize_revision_pin_rejects_absolute_and_escaping_paths(
    raw: str,
) -> None:
    with pytest.raises(ValueError):
        normalize_revision_pin(raw)


def test_normalize_revision_pin_rejects_non_strings() -> None:
    with pytest.raises(ValueError):
        normalize_revision_pin(42)


def test_revision_pin_for_entry_returns_none_when_unset() -> None:
    assert revision_pin_for_entry({"name": "core"}) is None


def test_revision_pin_models_carry_the_field() -> None:
    resolved = ResolvedLinkedRepo(
        name="sase-core",
        env_name="SASE_CORE",
        primary_dir="/primary",
        workspace_dir="/ws",
        workspace_num=1,
        revision_pin="sase-core-revision.txt",
    )
    assert resolved.to_json_dict()["revision_pin"] == "sase-core-revision.txt"

    record = RepoRecord(
        name="sase-core",
        kind="linked",
        project="sase",
        project_key="sase",
        path="/primary/../sase-core",
        exists=True,
        auto_clone=True,
        description="core",
        source="repos.linked config",
        env_name="SASE_CORE",
        revision_pin="sase-core-revision.txt",
    )
    assert record.to_json_dict()["revision_pin"] == "sase-core-revision.txt"


# Project-local pin resolution.


def test_revision_pins_read_from_project_local_config(tmp_path: Path) -> None:
    from sase.finalizers.commit_revision_pin import revision_pins_for_project

    primary = tmp_path / "proj"
    (primary / "sase").mkdir(parents=True)
    (primary / "sase" / "sase.yml").write_text(
        "repos:\n"
        "  linked:\n"
        "    - name: sase-core\n"
        "      path: ../sase-core\n"
        "      description: core\n"
        "      revision_pin: sase-core-revision.txt\n",
        encoding="utf-8",
    )

    assert revision_pins_for_project(str(primary)) == {
        "sase-core": "sase-core-revision.txt"
    }


def test_revision_pins_ignore_cwd_project_config(tmp_path: Path) -> None:
    """A tmp primary without its own config gets no pins.

    Regression: the sase checkout's own ``sase/sase.yml`` (the process cwd)
    must not leak its pin into unrelated finalizer runs.
    """

    from sase.finalizers.commit_revision_pin import revision_pins_for_project

    primary = tmp_path / "proj"
    primary.mkdir()

    assert revision_pins_for_project(str(primary)) == {}


# Ordering.


def test_pinned_sibling_ordered_first(tmp_path: Path) -> None:
    main = _repo("main", tmp_path / "sase", "main")
    sibling = _repo("sase-core", tmp_path / "core", "sibling")
    ordered = order_pinned_siblings_first(
        [main, sibling],
        _decisions(main, sibling),
        pins={"sase-core": "sase-core-revision.txt"},
    )
    assert [repo.name for repo in ordered] == ["sase-core", "main"]


def test_order_unchanged_without_pin(tmp_path: Path) -> None:
    main = _repo("main", tmp_path / "sase", "main")
    sibling = _repo("sase-core", tmp_path / "core", "sibling")
    ordered = order_pinned_siblings_first(
        [main, sibling], _decisions(main, sibling), pins={}
    )
    assert [repo.name for repo in ordered] == ["main", "sase-core"]


def test_order_unchanged_when_sibling_deferred(tmp_path: Path) -> None:
    main = _repo("main", tmp_path / "sase", "main")
    sibling = _repo("sase-core", tmp_path / "core", "sibling")
    decisions = _decisions(main, sibling)
    ordered = order_pinned_siblings_first(
        [main, sibling],
        decisions,
        pins={"sase-core": "sase-core-revision.txt"},
        accepted_deferrals={repository_decision_id(sibling): object()},
    )
    assert [repo.name for repo in ordered] == ["main", "sase-core"]


def test_order_unchanged_without_main_commit(tmp_path: Path) -> None:
    main = _repo("main", tmp_path / "sase", "main")
    sibling = _repo("sase-core", tmp_path / "core", "sibling")
    decisions = {
        repository_decision_id(main): {"action": "defer", "message": ""},
        repository_decision_id(sibling): {"action": "commit", "message": "x"},
    }
    ordered = order_pinned_siblings_first(
        [main, sibling],
        decisions,
        pins={"sase-core": "sase-core-revision.txt"},
    )
    assert [repo.name for repo in ordered] == ["main", "sase-core"]


def test_without_pin_protected_drops_host_pin() -> None:
    assert without_pin_protected(
        ("sase-core-revision.txt", "src/app.py"), "sase-core-revision.txt"
    ) == ("src/app.py",)
    assert without_pin_protected(("src/app.py",), "sase-core-revision.txt") == (
        "src/app.py",
    )


# Pin write conditions.


def _patch_git_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    import sase.finalizers.commit_revision_pin as pin_mod

    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: True
    )
    monkeypatch.setattr(pin_mod, "_pin_is_ancestor", lambda *a, **k: True)


def test_pin_written_and_included_in_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    new_sha = "a" * 40
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha=new_sha,
        main_is_commit=True,
    )

    assert diagnostic is None
    assert evidence == f"sase-core:sase-core-revision.txt:{'b' * 12}->{'a' * 12}"
    assert (primary / "sase-core-revision.txt").read_text(encoding="utf-8") == (
        new_sha + "\n"
    )


def test_pin_write_recovery_resume_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    new_sha = "a" * 40
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    first, _ = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha=new_sha,
        main_is_commit=True,
    )
    second, _ = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha=new_sha,
        main_is_commit=True,
    )

    assert "->" in first
    assert "already-equal" in second
    assert (primary / "sase-core-revision.txt").read_text(encoding="utf-8") == (
        new_sha + "\n"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"main_is_commit": False, "commit_sha": "a" * 40},
        {"main_is_commit": True, "commit_sha": "short"},
    ],
)
def test_pin_write_skip_conditions_never_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any]
) -> None:
    _patch_git_ok(monkeypatch)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        **kwargs,  # type: ignore[arg-type]
    )

    assert "skipped" in evidence
    assert diagnostic is not None
    assert (primary / "sase-core-revision.txt").read_text(encoding="utf-8") == (
        "b" * 40 + "\n"
    )


def test_pin_write_skips_when_sha_not_on_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_revision_pin as pin_mod

    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: False
    )
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha="a" * 40,
        main_is_commit=True,
    )

    assert "sha-not-on-default-branch" in evidence
    assert diagnostic is not None


def test_pin_write_skips_when_pin_not_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_revision_pin as pin_mod

    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: True
    )
    monkeypatch.setattr(pin_mod, "_pin_is_ancestor", lambda *a, **k: False)
    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    evidence, diagnostic = maybe_write_revision_pin(
        project_dir=str(primary),
        sibling_name="sase-core",
        sibling_dir=str(sibling_dir),
        pin_rel="sase-core-revision.txt",
        commit_sha="a" * 40,
        main_is_commit=True,
    )

    assert "pin-not-ancestor" in evidence
    assert diagnostic is not None


# End-to-end dispatch with a fake primary and a fake pinned sibling.


def test_dispatch_commits_pinned_sibling_first_and_follows_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_dispatch as dispatch_mod
    import sase.finalizers.commit_revision_pin as pin_mod

    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    monkeypatch.setattr(
        dispatch_mod,
        "_revision_pins_for_project",
        lambda _project_dir: {"sase-core": "sase-core-revision.txt"},
    )
    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: True
    )
    monkeypatch.setattr(pin_mod, "_pin_is_ancestor", lambda *a, **k: True)

    main = DirtyRepo(
        name="main", path=str(primary), changed_files=("app.py",), kind="main"
    )
    sibling = DirtyRepo(
        name="sase-core",
        path=str(sibling_dir),
        changed_files=("lib.rs",),
        kind="sibling",  # type: ignore[arg-type]
    )
    decisions = {
        repository_decision_id(main): {
            "action": "commit",
            "message": "feat: x",
            "bead_action": "close",
        },
        repository_decision_id(sibling): {
            "action": "commit",
            "message": "feat: core",
            "bead_action": "close",
        },
    }
    order: list[str] = []
    bead_actions: dict[str, Any] = {}

    def stitch_runner(
        repo: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context: object,
        **kwargs: Any,
    ) -> StitchCommandResult:
        order.append(repo.name)
        bead_actions[repo.name] = kwargs.get("bead_action")
        markers = []
        try:
            markers = json.loads(
                (artifacts / "commit_results.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            markers = []
        sha = "a" * 40 if repo.name == "sase-core" else "c" * 40
        markers.append(
            {
                "cwd": repo.path,
                "result": "ok",
                "commit_sha": sha,
                "commit_tree": "d" * 40,
            }
        )
        (artifacts / "commit_results.json").write_text(
            json.dumps(markers), encoding="utf-8"
        )
        return StitchCommandResult(
            returncode=0, stdout="ok", stderr="", argv=(), message_file=None
        )

    def _state(_project_dir: str, _artifacts: Any) -> PreparedCommitDirtyState:
        return PreparedCommitDirtyState(
            dirty_state=DirtyState(project_dir=str(primary), repos=(), details="clean")
        )

    result = dispatch_commit_decisions(
        (main, sibling),
        decisions,
        state=_state(str(primary), artifacts),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts), plan_digest="sha256:test"
        ),
        instance_id="commit",
        artifacts=artifacts,
        project_dir=str(primary),
        provider=None,
        invoke_result=InvokeResult(content=""),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
        stitch_runner=stitch_runner,  # type: ignore[arg-type]
        resume_runner=stitch_runner,  # type: ignore[arg-type]
        ledger=InstanceLedger(instance_id="commit", max_attempts=4),
        prepare_dirty_state=_state,  # type: ignore[arg-type]
        protected_path_resolver=lambda _artifacts, _path: (),
        unexpected_path_resolver=lambda _path, _protected: [],
        baseline_record_resolver=lambda _artifacts, _path: None,
    )

    assert order[0] == "sase-core"
    assert order[-1] == "main"
    # Only the main stitch applies bead_action; the sibling lands first.
    assert bead_actions["sase-core"] is None
    assert bead_actions["main"] == "close"
    kinds = [item.kind for item in result.evidence]
    assert "revision_pin" in kinds
    pin_evidence = next(
        item.value for item in result.evidence if item.kind == "revision_pin"
    )
    assert pin_evidence.startswith("sase-core:sase-core-revision.txt:")
    assert (primary / "sase-core-revision.txt").read_text(encoding="utf-8") == (
        "a" * 40 + "\n"
    )


def test_dispatch_keeps_today_order_without_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_dispatch as dispatch_mod

    primary = tmp_path / "sase"
    primary.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(
        dispatch_mod, "_revision_pins_for_project", lambda _project_dir: {}
    )

    main = DirtyRepo(
        name="main", path=str(primary), changed_files=("app.py",), kind="main"
    )
    sibling = DirtyRepo(
        name="sase-core",
        path=str(tmp_path / "core"),
        changed_files=("lib.rs",),
        kind="sibling",  # type: ignore[arg-type]
    )
    decisions = _decisions(main, sibling)
    order: list[str] = []

    def stitch_runner(
        repo: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context: object,
        **kwargs: Any,
    ) -> StitchCommandResult:
        order.append(repo.name)
        markers = []
        try:
            markers = json.loads(
                (artifacts / "commit_results.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            markers = []
        markers.append(
            {
                "cwd": repo.path,
                "result": "ok",
                "commit_sha": "e" * 40,
                "commit_tree": "d" * 40,
            }
        )
        (artifacts / "commit_results.json").write_text(
            json.dumps(markers), encoding="utf-8"
        )
        return StitchCommandResult(
            returncode=0, stdout="ok", stderr="", argv=(), message_file=None
        )

    def _state(_project_dir: str, _artifacts: Any) -> PreparedCommitDirtyState:
        return PreparedCommitDirtyState(
            dirty_state=DirtyState(project_dir=str(primary), repos=(), details="clean")
        )

    dispatch_commit_decisions(
        (main, sibling),
        decisions,
        state=_state(str(primary), artifacts),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts), plan_digest="sha256:test"
        ),
        instance_id="commit",
        artifacts=artifacts,
        project_dir=str(primary),
        provider=None,
        invoke_result=InvokeResult(content=""),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
        stitch_runner=stitch_runner,  # type: ignore[arg-type]
        resume_runner=stitch_runner,  # type: ignore[arg-type]
        ledger=InstanceLedger(instance_id="commit", max_attempts=4),
        prepare_dirty_state=_state,  # type: ignore[arg-type]
        protected_path_resolver=lambda _artifacts, _path: (),
        unexpected_path_resolver=lambda _path, _protected: [],
        baseline_record_resolver=lambda _artifacts, _path: None,
    )

    assert order == ["main", "sase-core"]


# Doctor check.


def test_doctor_flags_missing_pin_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "sase-core-revision.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "WARN"
    assert any("missing" in row["message"] for row in check.data["problems"])


def test_doctor_flags_non_sha_pin_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase-core-revision.txt").write_text("not-a-sha\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "sase-core-revision.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "WARN"
    assert any("40-character hex" in row["message"] for row in check.data["problems"])


def test_doctor_flags_absolute_pin_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "/abs/pin.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "WARN"


def test_doctor_accepts_valid_pin_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase-core-revision.txt").write_text("a" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {
            "repos": {
                "linked": [
                    {
                        "name": "sase-core",
                        "path": "../sase-core",
                        "description": "core",
                        "revision_pin": "sase-core-revision.txt",
                    }
                ]
            }
        },
    )
    monkeypatch.setattr(
        "sase.doctor.checks_config_repos._artifact_provider_registry_problems",
        lambda: [],
    )

    check = repos_checks.check_config_repos()

    assert check.status == "OK"
