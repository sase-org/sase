"""Split-sidecar initialization and legacy migration coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.sdd._sidecar_init import (
    SidecarInitSpec,
    initialize_sidecars,
    preflight_sidecars,
)
from sase.sdd._init_files import (
    ensure_sdd_sidecar_initialized,
    expected_sdd_sidecar_files,
    plan_sdd_sidecar_init_actions,
)
from sase.sdd._store_records import read_sdd_store_record, write_sdd_store_record
from sase.sdd._store_types import SddSidecar, SddStoreRecord
from sase.sdd.migrate import (
    apply_split_sdd_migration,
    plan_split_sdd_migration,
    render_split_sdd_migration_diff,
)
from sase.workspace_provider import SddSidecarPreflight


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _bare_remote(tmp_path: Path, name: str) -> Path:
    remote = tmp_path / f"{name}.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    return remote


def _git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GIT_AUTHOR_EMAIL": "sase@example.test",
        "GIT_AUTHOR_NAME": "SASE Tests",
        "GIT_COMMITTER_EMAIL": "sase@example.test",
        "GIT_COMMITTER_NAME": "SASE Tests",
    }.items():
        monkeypatch.setenv(key, value)


def test_sidecar_generated_files_are_deterministic_and_drift_tracked(
    tmp_path: Path,
) -> None:
    for kind in ("plans", "research"):
        root = tmp_path / kind
        actions = plan_sdd_sidecar_init_actions(kind, root)
        assert {action.path.name for action in actions} == {
            "README.md",
            f"{kind}-directory-map.png",
        }

        written = ensure_sdd_sidecar_initialized(kind, root)
        assert len(written) == 2
        expected_readme = expected_sdd_sidecar_files(kind, root)[0]
        assert (root / "README.md").read_text() == expected_readme.content
        assert (
            (root / "assets" / f"{kind}-directory-map.png")
            .read_bytes()
            .startswith(b"\x89PNG\r\n\x1a\n")
        )
        assert plan_sdd_sidecar_init_actions(kind, root) == ()


def test_custom_sidecar_generates_deterministic_generic_readme(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"

    actions = plan_sdd_sidecar_init_actions(
        "artifacts",
        root,
        description="Durable generated build artifacts.",
    )

    assert [action.path.name for action in actions] == ["README.md"]
    written = ensure_sdd_sidecar_initialized(
        "artifacts",
        root,
        description="Durable generated build artifacts.",
    )
    assert written == (root / "README.md",)
    assert (root / "README.md").read_text(encoding="utf-8") == (
        "# SASE Artifacts\n\n"
        "Durable generated build artifacts.\n\n"
        "This repository is managed as a SASE sidecar and is cloned below "
        "`sase/repos/artifacts` in project workspaces.\n"
    )


def test_custom_sidecar_preflight_passes_pin_visibility_and_description(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "widget"
    project.mkdir()
    captured: list[dict[str, object]] = []
    spec = SidecarInitSpec(
        role="artifacts",
        repo="acme/shared-artifacts",
        remote_url="https://github.com/acme/shared-artifacts.git",
        visibility="private",
        description="Durable build artifacts.",
    )

    def preflight(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> SddSidecarPreflight:
        captured.append(options)
        return SddSidecarPreflight(
            status="not_found",
            provider="GitHub",
            host="github.com",
            repo="acme/shared-artifacts",
            visibility="private",
        )

    monkeypatch.setattr("sase.workspace_provider.preflight_sdd_sidecar", preflight)

    result = preflight_sidecars(project, 1, (spec,))

    assert result["artifacts"].visibility == "private"
    assert captured == [
        {
            "create": False,
            "provider_policy": "separate_repo",
            "sdd_sidecar_suffix": "artifacts",
            "sdd_visibility": "private",
            "workspace_num": 1,
            "sdd_repo": "acme/shared-artifacts",
            "sdd_remote_url": "https://github.com/acme/shared-artifacts.git",
            "sdd_description": "Durable build artifacts.",
        }
    ]


def test_custom_sidecar_preflight_rejects_provider_visibility_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "widget"
    project.mkdir()
    spec = SidecarInitSpec(role="artifacts", visibility="private")
    monkeypatch.setattr(
        "sase.workspace_provider.preflight_sdd_sidecar",
        lambda *_args: SddSidecarPreflight(
            status="not_found",
            provider="GitHub",
            host="github.com",
            repo="acme/widget--artifacts",
            visibility="public",
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="config requires private",
    ):
        preflight_sidecars(project, 1, (spec,))


def test_custom_sidecar_init_uses_pinned_private_provider_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git_env(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    remote = _bare_remote(tmp_path, "shared-artifacts")
    clone = tmp_path / "artifacts-clone"
    captured: list[dict[str, object]] = []
    spec = SidecarInitSpec(
        role="artifacts",
        repo="acme/shared-artifacts",
        remote_url=str(remote),
        visibility="private",
        description="Durable build artifacts.",
    )

    def create_remote(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        captured.append(options)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/shared-artifacts",
            "remote_url": str(remote),
            "discovery": "found",
            "created": True,
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, _role: str(clone),
    )

    outcome = initialize_sidecars(
        project,
        1,
        (spec,),
        creation_authorized={"artifacts": True},
    )

    assert outcome.created == frozenset({"artifacts"})
    assert outcome.record is None
    assert (clone / "README.md").is_file()
    assert captured[0]["sdd_repo"] == "acme/shared-artifacts"
    assert captured[0]["sdd_visibility"] == "private"
    assert captured[0]["sdd_creation_authorized"] is True


def test_split_init_creates_both_repos_before_writing_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_env(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "sase.yml").write_text("is_sase_managed: true\n")
    remotes = {kind: _bare_remote(tmp_path, kind) for kind in ("plans", "research")}
    clones = {kind: tmp_path / f"widget--{kind}" for kind in remotes}
    calls: list[tuple[str, bool]] = []

    def create_remote(
        _primary: str, _workspace: str, options: dict[str, object]
    ) -> dict[str, object]:
        kind = str(options["sdd_sidecar_suffix"])
        calls.append((kind, options["sdd_creation_authorized"] is True))
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": f"acme/widget--{kind}",
            "remote_url": str(remotes[kind]),
            "discovery": "found",
            "created": True,
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, kind: str(clones[kind]),
    )

    outcome = initialize_sidecars(
        project,
        1,
        (SidecarInitSpec(role="plans"), SidecarInitSpec(role="research")),
        creation_authorized={"plans": True, "research": True},
    )

    assert calls == [("plans", True), ("research", True)]
    assert outcome.created == frozenset({"plans", "research"})
    record = read_sdd_store_record(project)
    assert record is not None and record.is_sidecar_storage
    assert record.plans is not None and record.plans.repo == "acme/widget--plans"
    assert record.research is not None
    assert (clones["plans"] / "README.md").is_file()
    assert (clones["plans"] / ".gitignore").read_text().splitlines() == [
        "beads/beads.db",
        "beads/beads.db-shm",
        "beads/beads.db-wal",
    ]
    assert (clones["research"] / "README.md").is_file()


def test_migration_dry_run_rewrites_links_and_apply_is_rerunnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_env(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "sase.yml").write_text("is_sase_managed: true\n")
    legacy = project / ".sase" / "sdd"
    plan_file = legacy / "plans" / "202607" / "example.md"
    prompt_file = legacy / "plans" / "202607" / "prompts" / "example.md"
    research_file = legacy / "research" / "202607" / "finding.md"
    bead_file = legacy / "beads" / "events" / "event.json"
    for path, content in {
        plan_file: "---\nprompt: .sase/sdd/plans/202607/prompts/example.md\n---\n",
        prompt_file: "---\nplan: sdd/plans/202607/example.md\n---\n",
        research_file: "# Finding\n",
        bead_file: "{}\n",
        legacy / "beads" / "beads.db": "local db\n",
        legacy / "legends" / "keep.md": "left in archived remote\n",
    }.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    roots: dict[str, Path] = {}
    remotes: dict[str, Path] = {}
    for kind in ("plans", "research"):
        remote = _bare_remote(tmp_path, f"migration-{kind}")
        root = tmp_path / f"clone-{kind}"
        _git(tmp_path, "clone", str(remote), str(root))
        (root / "README.md").write_text(f"# {kind}\n")
        _git(root, "add", "README.md")
        _git(root, "commit", "-m", f"Initialize {kind}")
        _git(root, "push", "origin", "HEAD")
        roots[kind] = root
        remotes[kind] = remote

    record = SddStoreRecord(
        schema_version=2,
        storage="sidecar_repos",
        provider="github",
        discovery="found",
        plans=SddSidecar("acme/widget--plans", str(remotes["plans"])),
        research=SddSidecar("acme/widget--research", str(remotes["research"])),
    )
    write_sdd_store_record(project, record)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, kind: str(roots[kind]),
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_sdd_kind_clone",
        lambda *_args, **_kwargs: None,
    )

    preview = plan_split_sdd_migration(project)
    assert preview.has_changes
    assert len(preview.actions) == 4
    rendered = render_split_sdd_migration_diff(preview)
    assert "prompt: 202607/prompts/example.md" in rendered
    assert plan_file.is_file()

    applied = apply_split_sdd_migration(project)
    assert len(applied.actions) == 4
    assert not legacy.exists()
    assert (
        "prompt: 202607/prompts/example.md"
        in (roots["plans"] / "202607" / "example.md").read_text()
    )
    assert (
        "plan: 202607/example.md"
        in (roots["plans"] / "202607" / "prompts" / "example.md").read_text()
    )
    assert not (roots["plans"] / "beads" / "beads.db").exists()
    assert (roots["plans"] / "beads" / "events" / "event.json").is_file()
    assert not plan_split_sdd_migration(project).has_changes
