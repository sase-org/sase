from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase import artifact_ref_context, artifact_refs
from sase.artifact_ref_models import (
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
)
from sase.artifact_ref_prompt_context import PromptRefContext
from sase.artifact_ref_prompt_materialize import materialize_missing_document_roots
from sase.artifact_refs import process_artifact_references, validate_artifact_references
from sase.sdd.store import SddMaterializationError, write_sdd_store_record
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo

from .preprocessing_helpers import (
    disable_consumption_ledger_writes,  # noqa: F401 (registers autouse fixture)
)


def test_missing_document_sidecar_materializes_and_expands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, root, ref_context, _remote = _sidecar_context_with_store(
        tmp_path,
        role="research",
        kind="research",
        remote_relpath="202608/report.md",
    )
    assert not root.exists()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.artifact_ref_prompt_context._safe_artifact_ref_context",
        lambda workspace_dir, workspace_num, *, project: _artifact_context(
            Path(workspace_dir), "research", root
        ),
    )

    expanded = process_artifact_references(
        "Read @research:202608/report.md.",
        ref_contexts=(ref_context,),
        materialize_missing_roots=True,
    )

    assert expanded == f"Read @{root / '202608' / 'report.md'}."
    assert (root / ".git").is_dir()
    assert root.is_relative_to(workspace)
    assert (
        "Materializing 'research' sidecar for @research references"
        in capsys.readouterr().err
    )


def test_materialization_is_noop_when_root_is_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _workspace, root, ref_context, _remote = _sidecar_context_with_store(
        tmp_path,
        role="research",
        kind="research",
        root_present=True,
    )
    doc = root / "202608" / "report.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# Report\n", encoding="utf-8")
    ensure = Mock()
    monkeypatch.setattr("sase.sdd.store.ensure_sdd_kind_clone", ensure)
    monkeypatch.chdir(tmp_path)

    expanded = process_artifact_references(
        "Read @research:202608/report.md.",
        ref_contexts=(ref_context,),
        materialize_missing_roots=True,
    )

    assert expanded == f"Read @{doc}."
    ensure.assert_not_called()


def test_materialization_default_is_off(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _workspace, _root, ref_context, _remote = _sidecar_context_with_store(
        tmp_path,
        role="research",
        kind="research",
    )
    ensure = Mock()
    monkeypatch.setattr("sase.sdd.store.ensure_sdd_kind_clone", ensure)

    with pytest.raises(SystemExit, match="1"):
        process_artifact_references(
            "@research:202608/report.md",
            ref_contexts=(ref_context,),
        )

    ensure.assert_not_called()


def test_validation_never_materializes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _workspace, _root, ref_context, _remote = _sidecar_context_with_store(
        tmp_path,
        role="research",
        kind="research",
    )
    ensure = Mock()
    monkeypatch.setattr("sase.sdd.store.ensure_sdd_kind_clone", ensure)

    with pytest.raises(SystemExit, match="1"):
        validate_artifact_references(
            "@research:202608/report.md",
            ref_contexts=(ref_context,),
        )

    ensure.assert_not_called()


def test_clone_failure_is_reported_as_actionable_hint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, _root, ref_context, remote = _sidecar_context_with_store(
        tmp_path,
        role="research",
        kind="research",
    )
    monkeypatch.chdir(tmp_path)

    def fail(*_args: object, **_kwargs: object) -> None:
        raise SddMaterializationError("network unavailable")

    monkeypatch.setattr("sase.sdd.store.ensure_sdd_kind_clone", fail)

    with pytest.raises(SystemExit, match="1"):
        process_artifact_references(
            "@research:202608/report.md",
            ref_contexts=(ref_context,),
            materialize_missing_roots=True,
        )

    captured = capsys.readouterr()
    assert "Materializing 'research' sidecar" in captured.err
    assert "could not materialize 'research' sidecar" in captured.out
    assert str(remote) in captured.out
    assert "sase repo path research --ensure" in captured.out


def test_present_sidecar_missing_file_names_searched_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, root, ref_context, _remote = _sidecar_context_with_store(
        tmp_path,
        role="research",
        kind="research",
        root_present=True,
    )
    monkeypatch.chdir(tmp_path)
    ensure = Mock()
    monkeypatch.setattr("sase.sdd.store.ensure_sdd_kind_clone", ensure)

    with pytest.raises(SystemExit, match="1"):
        process_artifact_references(
            "@research:202608/missing.md",
            ref_contexts=(ref_context,),
            materialize_missing_roots=True,
        )

    output = capsys.readouterr().out
    assert f"searched document root: {root}" in output
    assert "sase repo path research --ensure" not in output
    ensure.assert_not_called()


def test_kind_to_role_mapping_includes_builtin_and_custom_ref_kinds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    roots = {
        "plans": workspace / "sase" / "repos" / "plans",
        "research": workspace / "sase" / "repos" / "research",
        "designs": workspace / "sase" / "repos" / "designs",
    }
    remote_urls = {role: f"git@example.test:sase/{role}.git" for role in roots}

    class Store:
        def split_sidecar_roles(self) -> tuple[str, ...]:
            return ("plans", "research", "designs")

        def kind_root(self, role: str) -> Path:
            return roots[role]

        def remote_url_for_kind(self, role: str) -> str:
            return remote_urls[role]

    calls: list[str] = []

    def ensure(
        _workspace_dir: Path,
        _workspace_num: int,
        role: str,
        *,
        strict: bool,
    ) -> Path:
        assert strict is True
        calls.append(role)
        roots[role].mkdir(parents=True)
        return roots[role]

    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: Store())
    monkeypatch.setattr("sase.sdd.store.ensure_sdd_kind_clone", ensure)
    monkeypatch.setattr(
        "sase._linked_repo_config.resolution_config",
        lambda *_args: {
            "repos": {
                "sidecar": {
                    "custom": {
                        "designs": {"ref": {"kind": "idea"}},
                    }
                }
            }
        },
    )
    monkeypatch.setattr(
        "sase.artifact_ref_prompt_materialize.refresh_prompt_ref_context",
        lambda context: context,
    )
    context = PromptRefContext(
        artifact_context=_artifact_context(workspace, "research", roots["research"]),
        project=None,
        primary_repo=None,
        workspace_dir=workspace,
        workspace_num=2,
        origin="vcs_workflow",
        project_ref="sase",
    )

    refreshed, failures = materialize_missing_document_roots(
        ("research", "plan", "idea"),
        context,
    )

    assert refreshed is context
    assert failures == ()
    assert calls == ["research", "plans", "designs"]


def test_lsp_catalog_never_materializes_document_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    ensure = Mock()
    record = SimpleNamespace(
        project_name="gh_sase-org__sase",
        display_name="sase",
        aliases=[],
        workspace_dir=str(workspace),
        system_managed=False,
    )
    monkeypatch.setattr("sase.sdd.store.ensure_sdd_kind_clone", ensure)
    monkeypatch.setattr(
        artifact_ref_context,
        "list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "effective_project_name",
        lambda project_record: project_record.display_name,
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "workspace_context_for_plan_resolution",
        lambda path: (Path(path), 1),
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "artifact_ref_context",
        lambda workspace_dir, _workspace_num, project=None: _artifact_context(
            Path(workspace_dir),
            "research",
            Path(workspace_dir) / "sase" / "repos" / "research",
        ),
    )
    monkeypatch.setattr(
        artifact_ref_context,
        "_workspace_project_ref",
        lambda _workspace: "sase",
    )

    artifact_refs.artifact_ref_lsp_catalog_payload(workspace)

    ensure.assert_not_called()


def _sidecar_context_with_store(
    tmp_path: Path,
    *,
    role: str,
    kind: str,
    root_present: bool = False,
    remote_relpath: str | None = None,
) -> tuple[Path, Path, PromptRefContext, Path]:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    primary.mkdir()
    workspace.mkdir()
    plans_remote = tmp_path / "plans.git"
    role_remote = tmp_path / f"{role}.git"
    init_bare_repo(plans_remote)
    if remote_relpath is None:
        init_bare_repo(role_remote)
    else:
        _seed_remote(role_remote, tmp_path / f"{role}-seed", remote_relpath)
    sidecars = {
        "plans": {
            "repo": "owner/repo--plans",
            "remote_url": str(plans_remote),
        },
        role: {
            "repo": f"owner/repo--{role}",
            "remote_url": str(role_remote),
        },
    }
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": sidecars,
        },
    )
    root = workspace / "sase" / "repos" / role
    if root_present:
        root.mkdir(parents=True)
        git(["init", "-q"], root)
        git(["remote", "add", "origin", str(role_remote)], root)
    return (
        workspace,
        root,
        PromptRefContext(
            artifact_context=_artifact_context(workspace, kind, root),
            project=None,
            primary_repo=None,
            workspace_dir=workspace,
            workspace_num=2,
            origin="vcs_workflow",
            project_ref="gh_sase-org__sase",
        ),
        role_remote,
    )


def _seed_remote(remote: Path, seed: Path, relpath: str) -> None:
    init_bare_repo(remote)
    clone(remote, seed)
    doc = seed / relpath
    doc.parent.mkdir(parents=True)
    doc.write_text("# Report\n", encoding="utf-8")
    commit_all(seed, "Add report")
    git(["push", "-u", "origin", "main"], seed)


def _artifact_context(
    workspace: Path,
    kind: str,
    root: Path,
) -> ArtifactRefContext:
    return ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot(kind, root),),
        chats_root=workspace / "chats",
        artifact_index_path=workspace / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(),
    )
