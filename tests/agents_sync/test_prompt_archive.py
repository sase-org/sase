from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import sase_core_rs

from sase.agents_sync.models import ProjectTarget, SyncOutcome, TargetSelection
from sase.agents_sync.prompt_archive import publish as archive_publish
from sase.agents_sync.prompt_archive.naming import resolve_prompt_name
from sase.agents_sync.prompt_archive.publish import (
    prepare_prompt_archive,
    publish_prompt_archive,
)
from sase.agents_sync.prompt_archive.render import render_prompt_document
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import git, setup_target


class _HostedLinks:
    def agent_url(self, name: str) -> str:
        return f"https://example.test/agents/{name}"

    def plan_url(self, plan_ref: str) -> str:
        label = plan_ref.removeprefix("plan:").removeprefix("plans:")
        return f"https://example.test/plans/{label}"

    def blob_url_for_repository(
        self,
        _root: Path,
        revision: str,
        path: str,
    ) -> str:
        return f"https://example.test/blob/{revision}/{path}"

    def commit_url_for_repository(self, _root: Path, sha: str) -> str:
        return f"https://example.test/commit/{sha}"

    def bead_url(self, bead_id: str) -> str:
        return f"https://example.test/beads/{bead_id}"


def _record(
    *,
    artifacts_dir: Path,
    raw_ref: str,
    label: str,
    sha256: str | None = None,
    pool_relpath: str | None = None,
    vcs_repo: str | None = None,
    vcs_relpath: str | None = None,
    vcs_revision: str | None = None,
    ref_kind: str = "file",
    locator: str | None = None,
) -> dict[str, object]:
    object_relpath = (
        None if sha256 is None else sase_core_rs.artifact_object_relpath(sha256)
    )
    return {
        "schema_version": sase_core_rs.prompt_artifact_wire_schema_version(),
        "recorded_at": "2026-08-01T14:22:03Z",
        "agent_artifacts_dir": str(artifacts_dir),
        "raw_ref": raw_ref,
        "expanded_ref": raw_ref,
        "ref_kind": ref_kind,
        "label": label,
        "source_path": None,
        "sha256": sha256,
        "size_bytes": None,
        "mime_type": None,
        "pool_relpath": pool_relpath,
        "vcs_repo": vcs_repo,
        "vcs_relpath": vcs_relpath,
        "vcs_revision": vcs_revision,
        "locator": locator,
        "skipped_reason": None,
        "logical_path": None,
        "root_name": None,
        "authored_path": None,
        "origin": None,
        "object_relpath": object_relpath,
        "sidecar_visibility": None,
    }


def _write_manifest(workspace: Path, rows: list[dict[str, object]]) -> None:
    path = workspace / ".sase/artifacts/prompt-artifacts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            f"{sase_core_rs.prompt_artifact_manifest_render_record(row)}\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def test_prepare_prompt_archive_links_and_copies_all_reference_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifacts_dir = tmp_path / "runs/20260801120000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "workspace_dir": str(workspace),
                "sdd_plan_path": "plans:202608/example_plan.md",
            }
        )
    )
    (artifacts_dir / "raw_xprompt.md").write_text(
        "Use @~/diagram.png, @src/demo.py, @src/#plan.py, #plan, and @bug:proj#7.\n"
    )
    (artifacts_dir / "claude_prompt.md").write_text(
        "# Rendered\n\n```python\nprint('sent to model')\n```\n",
        encoding="utf-8",
    )

    content = b"diagram bytes"
    digest = hashlib.sha256(content).hexdigest()
    pool_name = sase_core_rs.prompt_artifact_pool_filename(digest, "diagram.png")
    pool = workspace / ".sase/artifacts/pool" / pool_name
    pool.parent.mkdir(parents=True)
    pool.write_bytes(content)
    rows = [
        _record(
            artifacts_dir=artifacts_dir,
            raw_ref="@~/diagram.png",
            label="diagram.png",
            sha256=digest,
            pool_relpath=f"pool/{pool_name}",
        ),
        _record(
            artifacts_dir=artifacts_dir,
            raw_ref="@src/demo.py",
            label="src/demo.py",
            sha256="b" * 64,
            vcs_repo="primary",
            vcs_relpath="src/demo.py",
            vcs_revision="b" * 40,
        ),
        _record(
            artifacts_dir=artifacts_dir,
            raw_ref="@src/#plan.py",
            label="src/#plan.py",
            sha256="c" * 64,
            vcs_repo="primary",
            vcs_relpath="src/#plan.py",
        ),
        _record(
            artifacts_dir=artifacts_dir,
            raw_ref="@bug:proj#7",
            label="proj#7",
            ref_kind="bug",
            locator="https://example.test/issues/7",
        ),
    ]
    _write_manifest(workspace, rows)

    repo = tmp_path / "agents"
    repo.mkdir()
    target = ProjectTarget(
        "proj",
        "Project",
        workspace,
        (workspace,),
        repo,
        "git@example.test:project/agents.git",
    )
    hosted = _HostedLinks()
    monkeypatch.setattr(archive_publish, "_hosted_resolver", lambda *_a: hosted)
    monkeypatch.setattr(
        archive_publish,
        "_repository_roots",
        lambda: {"primary": workspace.resolve()},
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)

    first = prepare_prompt_archive(
        target=target,
        repo=repo,
        agent_name="worker",
        global_agent="alice.athena.worker",
        primary_revision="a" * 40,
        commit_cwd=workspace,
        agent_artifacts_dir=artifacts_dir,
    )
    first_bytes = first.prompt_path.read_bytes()
    second = prepare_prompt_archive(
        target=target,
        repo=repo,
        agent_name="worker",
        global_agent="alice.athena.worker",
        primary_revision="a" * 40,
        commit_cwd=workspace,
        agent_artifacts_dir=artifacts_dir,
    )

    assert first.prompt_path == repo / "prompts/202608/example_plan.md"
    assert second.prompt_path == first.prompt_path
    assert second.prompt_path.read_bytes() == first_bytes
    document = first.prompt_path.read_text()
    artifact_link = sase_core_rs.artifact_object_prompt_link(
        sase_core_rs.artifact_object_relpath(digest)
    )
    assert "[@~/diagram.png][1]" in document and f"[1]: {artifact_link}" in document
    assert (
        "[@src/demo.py][2]" in document
        and f"[2]: https://example.test/blob/{'b' * 40}/src/demo.py" in document
    )
    assert (
        "[@src/#plan.py][3]" in document
        and f"[3]: https://example.test/blob/{'a' * 40}/src/#plan.py" in document
    )
    assert ", #plan, and " in document
    assert "sase/xprompts/plan.md" not in document
    assert "[@bug:proj#7][4]" in document
    assert "[4]: https://example.test/issues/7" in document
    assert "<!-- sase:section:" not in document
    assert "<details>" not in document
    assert "sent to model" not in document
    object_path = repo / sase_core_rs.artifact_object_relpath(digest)
    assert object_path.read_bytes() == content
    index = (repo / "prompts/202608/README.md").read_text()
    assert "[example_plan.md](example_plan.md)" in index
    assert "| 4 |" in index


def test_render_prompt_document_keeps_body_xprompt_reference_verbatim() -> None:
    document = render_prompt_document(
        "Archive body references #plan.\n",
        (),
        artifact_target=lambda _record: None,
        agent_label="alice.athena.worker",
        agent_target="https://example.test/agents/worker",
    ).document

    assert "Archive body references #plan." in document
    assert "[#plan]" not in document
    assert "<!-- sase:section:" not in document


def test_artifact_target_resolver_handles_pinned_and_builtin_destinations(
    tmp_path: Path,
) -> None:
    from sase.agents_sync.prompt_archive.preparation import _ArtifactTargetResolver

    primary = tmp_path / "primary"
    sidecar = tmp_path / "sidecar"
    primary.mkdir()
    sidecar.mkdir()

    def git_runner(*_args: object, **_kwargs: object):
        raise AssertionError("pinned VCS records must not inspect HEAD")

    resolver = _ArtifactTargetResolver(
        yyyymm="202608",
        repo=tmp_path / "agents",
        project="Project",
        workspace_root=primary,
        primary_root=primary,
        primary_revision="a" * 40,
        hosted=_HostedLinks(),
        git_runner=git_runner,  # type: ignore[arg-type]
        repository_roots={"primary": primary, "sidecar": sidecar},
    )

    artifacts_dir = tmp_path / "run"
    assert (
        resolver(
            _record(
                artifacts_dir=artifacts_dir,
                raw_ref="@doc",
                label="doc",
                sha256="b" * 64,
                vcs_repo="sidecar",
                vcs_relpath="docs/x.md",
                vcs_revision="c" * 40,
            )
        )
        == f"https://example.test/blob/{'c' * 40}/docs/x.md"
    )
    assert (
        resolver(
            _record(
                artifacts_dir=artifacts_dir,
                raw_ref="@commit",
                label="commit",
                ref_kind="commit",
                locator="primary@abc123",
            )
        )
        == "https://example.test/commit/abc123"
    )
    assert (
        resolver(
            _record(
                artifacts_dir=artifacts_dir,
                raw_ref="@stitch",
                label="stitch",
                ref_kind="stitch",
                locator="primary@def456",
            )
        )
        == "https://example.test/commit/def456"
    )
    assert (
        resolver(
            _record(
                artifacts_dir=artifacts_dir,
                raw_ref="@bead",
                label="bead",
                ref_kind="bead",
                locator="Project/sase-js.6",
            )
        )
        == "https://example.test/beads/sase-js.6"
    )


def test_patch_locator_resolves_only_current_project_pr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agents_sync.prompt_archive.preparation import _patch_pr_url
    from sase.core.project_lifecycle_wire import ProjectRecordWire

    project_file = tmp_path / "proj.sase"
    project_file.write_text(
        "NAME: example\n"
        "DESCRIPTION:\n"
        "Patch under test\n"
        "PR: https://example.test/pull/1\n"
        "STATUS: WIP\n",
        encoding="utf-8",
    )
    record = ProjectRecordWire(
        schema_version=3,
        project_name="proj",
        project_dir=str(tmp_path),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(tmp_path),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=["alias"],
        display_name="Project",
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr("sase.core.paths.sase_projects_dir", lambda: tmp_path)

    assert _patch_pr_url("Project/example", "Project") == "https://example.test/pull/1"
    assert _patch_pr_url("Other/example", "Project") is None


def test_prepare_prompt_archive_accepts_expanded_planner_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifacts_dir = tmp_path / "runs/20260801120000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(workspace)}),
        encoding="utf-8",
    )
    (artifacts_dir / "raw_xprompt.md").write_text("Raw prompt.\n", encoding="utf-8")
    repo = tmp_path / "agents"
    repo.mkdir()
    target = ProjectTarget(
        "proj",
        "Project",
        workspace,
        (workspace,),
        repo,
        "git@example.test:project/agents.git",
    )
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: _HostedLinks(),
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)

    prepared = prepare_prompt_archive(
        target=target,
        repo=repo,
        agent_name="planner",
        global_agent="alice.athena.planner",
        primary_revision="a" * 40,
        commit_cwd=workspace,
        agent_artifacts_dir=artifacts_dir,
        prompt_content="Expanded planner prompt.\n",
        plan_ref="plans:202608/approved.md",
        prompt_name="approved",
        yyyymm="202608",
    )

    assert prepared.prompt_path == repo / "prompts/202608/approved.md"
    document = prepared.prompt_path.read_text(encoding="utf-8")
    assert "Expanded planner prompt." in document
    assert "Raw prompt." not in document
    assert "https://example.test/plans/202608/approved.md" in document
    assert "<!-- sase:section:rendered -->" not in document


def test_prompt_name_reuses_same_run_and_suffixes_another_run() -> None:
    listing = ("plan.md", "plan_1.md")
    assert resolve_prompt_name("plan", "agent", listing) == "plan_2"
    assert (
        resolve_prompt_name(
            "plan",
            "agent",
            listing,
            reusable_names=("plan",),
        )
        == "plan"
    )
    assert resolve_prompt_name(None, "alice.athena.agent", ()) == ("alice.athena.agent")


def test_publish_prompt_archive_missing_agents_target_is_nonfatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_publication_project_key",
        lambda *_args, **_kwargs: "proj",
    )
    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection(
            (),
            (SyncOutcome("proj", "Project", skip_reason="agents sidecar disabled"),),
        ),
    )

    outcome = publish_prompt_archive(
        "worker",
        "a" * 40,
        commit_cwd=tmp_path,
    )

    assert not outcome.published
    assert outcome.skip_reason == "agents sidecar disabled"
    assert outcome.error is None


def test_publish_prompt_archive_without_artifacts_is_git_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    artifacts_dir = tmp_path / "runs/20260801130000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)})
    )
    (artifacts_dir / "raw_xprompt.md").write_text("Archive this prompt.\n")
    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        archive_publish,
        "require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        archive_publish,
        "_hosted_resolver",
        lambda *_args: _HostedLinks(),
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)

    first = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )
    second = publish_prompt_archive(
        "worker",
        "a" * 40,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert first.published and first.error is None
    assert not second.published and second.error is None
    verify = tmp_path / "verify-prompt"
    git(tmp_path, "clone", str(remote), str(verify))
    prompt = verify / "prompts/202608/alice.athena.worker.md"
    assert prompt.is_file()
    assert "Archive this prompt." in prompt.read_text()
    assert not (verify / "artifacts/202608").exists()
