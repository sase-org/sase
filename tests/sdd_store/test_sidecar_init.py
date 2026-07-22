"""Split-sidecar initialization coverage."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.sdd._sidecar_init import (
    SidecarInitSpec,
    initialize_materialized_sidecars,
    initialize_sidecars,
    preflight_sidecars,
    sidecar_clone_root,
)
from sase.sdd._init_files import (
    ensure_sdd_sidecar_initialized,
    expected_sdd_sidecar_files,
    plan_sdd_sidecar_init_actions,
)
from sase.sdd._store_records import read_sdd_store_record
from sase.sdd._store_records import write_sdd_store_record
from sase.workspace_provider import SddSidecarPreflight


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _bare_remote(tmp_path: Path, name: str) -> Path:
    remote = tmp_path / f"{name}.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    return remote


def _git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.get_primary_workspace_dir",
        lambda workspace, _workspace_num: workspace,
    )
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


def test_agents_sidecar_generated_files_are_privacy_forward_and_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "agents"

    actions = plan_sdd_sidecar_init_actions("agents", root)

    assert {action.path.relative_to(root).as_posix() for action in actions} == {
        "README.md",
        "manifest.json",
        "agents/.gitkeep",
    }
    written = ensure_sdd_sidecar_initialized("agents", root)
    assert set(written) == {action.path for action in actions}
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "full agent chat transcripts" in readme
    assert "prompts and responses" in readme
    assert "agent metadata and commit associations" in readme
    assert "`private`" in readme
    assert "`disabled: true`" in readme
    assert "`sase agent sync`" in readme
    assert json.loads((root / "manifest.json").read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "agents": {},
    }
    assert (root / "agents" / ".gitkeep").read_text(encoding="utf-8") == ""
    assert plan_sdd_sidecar_init_actions("agents", root) == ()

    (root / "manifest.json").write_text("{}\n", encoding="utf-8")
    assert plan_sdd_sidecar_init_actions("agents", root) == ()

    (root / "agents" / ".gitkeep").unlink()
    populated = root / "agents" / "athena.worker"
    populated.mkdir()
    (populated / "meta.json").write_text("{}\n", encoding="utf-8")
    assert plan_sdd_sidecar_init_actions("agents", root) == ()


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


def test_sidecar_clone_root_keeps_agents_machine_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "widget"
    project.mkdir()
    state_root = tmp_path / "state"
    monkeypatch.setenv("SASE_HOME", str(state_root))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda root: "gh_acme__widget" if root == str(project) else None,
    )

    assert sidecar_clone_root(project, "plans") == (
        project / "sase" / "repos" / "plans"
    )
    assert sidecar_clone_root(project, "agents") == (
        state_root / "projects" / "gh_acme__widget" / "repos" / "agents"
    )
    assert not state_root.exists()


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


def test_agents_init_uses_hidden_root_and_leaves_compatibility_store_two_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git_env(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    remotes = {
        role: _bare_remote(tmp_path, role) for role in ("plans", "research", "agents")
    }
    visible_clones = {
        role: tmp_path / f"widget--{role}" for role in ("plans", "research")
    }
    state_root = tmp_path / "state"
    captured: list[tuple[str, str, bool]] = []
    monkeypatch.setenv("SASE_HOME", str(state_root))
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd",
        lambda _root: "gh_acme__widget",
    )

    def create_remote(
        _primary: str,
        _workspace: str,
        options: dict[str, object],
    ) -> dict[str, object]:
        role = str(options["sdd_sidecar_suffix"])
        captured.append(
            (
                role,
                str(options["sdd_visibility"]),
                options["sdd_creation_authorized"] is True,
            )
        )
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": f"acme/widget--{role}",
            "remote_url": str(remotes[role]),
            "discovery": "found",
            "created": True,
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, role: str(visible_clones[role]),
    )
    specs = (
        SidecarInitSpec(role="plans"),
        SidecarInitSpec(role="research"),
        SidecarInitSpec(
            role="agents",
            visibility="private",
            description="Private commit-associated agents.",
        ),
    )

    outcome = initialize_sidecars(
        project,
        1,
        specs,
        creation_authorized={"plans": True, "research": True, "agents": True},
    )

    agents_root = state_root / "projects" / "gh_acme__widget" / "repos" / "agents"
    assert captured == [
        ("plans", "public", True),
        ("research", "public", True),
        ("agents", "private", True),
    ]
    assert outcome.roots == {**visible_clones, "agents": agents_root}
    assert outcome.created == frozenset({"plans", "research", "agents"})
    assert (agents_root / "README.md").is_file()
    assert json.loads((agents_root / "manifest.json").read_text()) == {
        "schema_version": 1,
        "agents": {},
    }
    assert (agents_root / "agents" / ".gitkeep").is_file()
    assert not (project / "sase" / "repos" / "agents").exists()

    record = read_sdd_store_record(project)
    assert record is not None and record.is_sidecar_storage
    assert record.plans is not None and record.research is not None
    persisted = json.loads((project / ".sase" / "sdd-store.json").read_text())
    assert set(persisted["sidecars"]) == {"plans", "research"}

    roots = initialize_materialized_sidecars(project, (specs[-1],))
    assert roots == {"agents": agents_root}


def test_split_init_normalizes_legacy_https_clone_and_record_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git_env(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    clone = tmp_path / "research-clone"
    clone.mkdir()
    _git(clone, "init")
    _git(
        clone,
        "remote",
        "add",
        "origin",
        "https://github.com/acme/widget--research.git",
    )
    local = clone / "local.md"
    local.write_text("preserve this checkout\n", encoding="utf-8")
    _git(clone, "add", "local.md")
    _git(clone, "commit", "-m", "Local research commit")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    record_path = project / ".sase" / "sdd-store.json"
    record_path.parent.mkdir()
    record_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "storage": "sidecar_repos",
                "provider": "github",
                "host": "github.com",
                "sidecars": {
                    "plans": {
                        "repo": "acme/widget--plans",
                        "remote_url": "git@github.com:acme/widget--plans.git",
                    },
                    "research": {
                        "repo": "acme/widget--research",
                        "remote_url": "https://github.com/acme/widget--research.git",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    captured: list[dict[str, object]] = []

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
            "repo": "acme/widget--research",
            "remote_url": "git@github.com:acme/widget--research.git",
            "discovery": "found",
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, _kind: str(clone),
    )
    monkeypatch.setattr(
        "sase.sdd._store_link._pull_sdd_clone",
        lambda _root, **_kwargs: True,
    )
    monkeypatch.setattr("sase.sdd._sidecar_init._seed_sidecars", lambda *_a, **_k: None)

    outcome = initialize_sidecars(
        project,
        0,
        (
            SidecarInitSpec(
                role="research",
                repo="acme/widget--research",
                remote_url="git@github.com:acme/widget--research.git",
            ),
        ),
    )

    assert captured[0]["sdd_remote_url"] == ("git@github.com:acme/widget--research.git")
    assert local.read_text(encoding="utf-8") == "preserve this checkout\n"
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == head
    )
    assert (
        subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == "git@github.com:acme/widget--research.git"
    )
    assert outcome.record is not None and outcome.record.research is not None
    assert outcome.record.research.remote_url == (
        "git@github.com:acme/widget--research.git"
    )
    persisted = json.loads(record_path.read_text(encoding="utf-8"))
    assert persisted["sidecars"]["research"]["remote_url"] == (
        "git@github.com:acme/widget--research.git"
    )


def test_split_init_cuts_over_changed_pinned_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_env(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    old_remote = _bare_remote(tmp_path, "widget--research")
    shared_remote = _bare_remote(tmp_path, "shared-research")
    clone = tmp_path / "research-clone"
    _git(tmp_path, "clone", str(old_remote), str(clone))
    captured: list[dict[str, object]] = []
    write_sdd_store_record(
        project,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "host": "github.com",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "acme/widget--research",
                    "remote_url": str(old_remote),
                },
            },
        },
    )

    def create_remote(
        _primary: str, _workspace: str, options: dict[str, object]
    ) -> dict[str, object]:
        captured.append(options)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "sase-org/shared-research",
            "remote_url": str(shared_remote),
            "discovery": "found",
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, _kind: str(clone),
    )

    outcome = initialize_sidecars(
        project,
        0,
        (
            SidecarInitSpec(
                role="research",
                repo="sase-org/shared-research",
                remote_url=str(shared_remote),
            ),
        ),
    )

    assert captured[0]["sdd_repo"] == "sase-org/shared-research"
    assert captured[0]["sdd_remote_url"] == str(shared_remote)
    assert outcome.record is not None and outcome.record.research is not None
    assert outcome.record.research.repo == "sase-org/shared-research"
    assert outcome.record.research.remote_url == str(shared_remote)
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert origin == str(shared_remote)
    assert (clone / "README.md").is_file()


def test_split_init_re_records_stale_research_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git_env(monkeypatch)
    project = tmp_path / "widget"
    project.mkdir()
    (project / ".git").mkdir()
    research_remote = _bare_remote(tmp_path, "widget--research")
    clone = tmp_path / "research-clone"
    write_sdd_store_record(
        project,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "host": "github.com",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "sase-org/sase--research",
                    "remote_url": "git@github.com:sase-org/sase--research.git",
                },
            },
        },
    )

    def create_remote(
        _primary: str, _workspace: str, options: dict[str, object]
    ) -> dict[str, object]:
        assert options["sdd_repo"] == "acme/widget--research"
        assert options["sdd_remote_url"] == str(research_remote)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "github",
            "host": "github.com",
            "repo": "acme/widget--research",
            "remote_url": str(research_remote),
            "discovery": "found",
        }

    monkeypatch.setattr("sase.workspace_provider.create_sdd_remote", create_remote)
    monkeypatch.setattr(
        "sase.linked_repos.sidecar_repo_clone_dir",
        lambda _workspace, _kind: str(clone),
    )

    outcome = initialize_sidecars(
        project,
        0,
        (
            SidecarInitSpec(
                role="research",
                repo="acme/widget--research",
                remote_url=str(research_remote),
            ),
        ),
    )

    assert outcome.record is not None
    assert outcome.record.plans is not None
    assert outcome.record.plans.repo == "acme/widget--plans"
    assert outcome.record.research is not None
    assert outcome.record.research.repo == "acme/widget--research"
    assert outcome.record.research.remote_url == str(research_remote)
