"""Tests for ``sase repo init`` handling."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

import pytest

from sase._linked_repo_config import DEFAULT_AGENTS_DESCRIPTION
from sase.main._repo_init_config import explicit_sidecar_config_update
from sase.main.init_onboarding import run_init_onboarding
from sase.main.init_registry import InitCommandSpec
from sase.main.repo_init_handler import plan_repo_init, run_repo_init
from sase.sdd._sidecar_init import SidecarInitSpec
from sase.sdd.store import SddMaterializationError, SddStore
from tests.main.repo_init_handler_helpers import (
    _args,
    _git_init,
    _mark_managed_project,
)


def test_repo_init_writes_managed_sidecar_config_local_store_and_gitignore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path, "# keep\nis_sase_managed: true\n")
    store_root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", store_root, store_root),
    )

    assert run_repo_init(_args(tmp_path)) == 0

    assert (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8") == (
        "# keep\n"
        "is_sase_managed: true\n"
        "repos:\n"
        "  sidecar:\n"
        "    builtin:\n"
        "      plans:\n"
        "        auto_clone: true\n"
        "        auto_sync: true\n"
        "        ref:\n"
        "          use: builtin@plan\n"
        "      beads:\n"
        "        auto_sync: true\n"
        "      agents:\n"
        f"        description: {DEFAULT_AGENTS_DESCRIPTION}\n"
        "    custom:\n"
        "      research:\n"
        "        description: Durable SASE research reports and generated media.\n"
        "        auto_sync: true\n"
    )
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "/sase/repos/\n"
    assert (store_root / "README.md").is_file()


def test_bare_init_enable_management_also_writes_managed_sidecar_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git_init(tmp_path)
    monkeypatch.chdir(tmp_path)
    store_root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", store_root, store_root),
    )
    args = argparse.Namespace(
        all=False,
        check=False,
        diff=False,
        enable_project_memory=True,
        no_commit=True,
        yes=True,
    )
    spec = InitCommandSpec("repo", "Repos", plan_repo_init, run_repo_init)

    assert run_init_onboarding(args, specs=(spec,)) == 0

    config = (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8")
    assert "is_sase_managed: true" in config
    assert "    builtin:\n" in config
    assert "      plans:\n" in config
    assert "      beads:\n" in config
    assert "      agents:\n" in config
    assert "    custom:\n" in config
    assert "      research:\n" in config
    assert "Durable SASE research reports and generated media." in config


def test_repo_init_appends_plans_without_losing_disabled_research_comments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(
        tmp_path,
        "# keep\n"
        "is_sase_managed: true\n"
        "repos:\n"
        "  sidecar:\n"
        "    custom:\n"
        "      research: # shared\n"
        "        disabled: true\n",
    )
    root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", root, root),
    )

    assert run_repo_init(_args(tmp_path)) == 0

    text = (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8")
    assert "# keep" in text
    assert "research: # shared" in text
    assert text.count("plans:") == 1
    assert text.count("beads:") == 1
    assert text.count("research:") == 1
    assert text.count("agents:") == 1
    assert "Durable SASE research reports" not in text


def test_repo_init_preserves_existing_managed_sidecar_entries_verbatim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = (
        "# keep\n"
        "is_sase_managed: true\n"
        "repos:\n"
        "  sidecar:\n"
        "    builtin:\n"
        "      plans: # custom\n"
        "        disabled: true\n"
        "      beads: # migration opt-out\n"
        "        disabled: true\n"
        "      agents: # privacy opt-out\n"
        "        disabled: true\n"
        "    custom:\n"
        "      research: # opted out\n"
        "        disabled: true\n"
    )
    expected = (
        "# keep\n"
        "is_sase_managed: true\n"
        "repos:\n"
        "  sidecar:\n"
        "    builtin:\n"
        "      plans: # custom\n"
        "        disabled: true\n"
        "        ref:\n"
        "          use: builtin@plan\n"
        "      beads: # migration opt-out\n"
        "        disabled: true\n"
        "      agents: # privacy opt-out\n"
        "        disabled: true\n"
        "    custom:\n"
        "      research: # opted out\n"
        "        disabled: true\n"
    )
    _mark_managed_project(tmp_path, config)
    root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", root, root),
    )

    assert run_repo_init(_args(tmp_path)) == 0

    assert (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8") == expected


def test_repo_init_sidecar_config_update_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mark_managed_project(tmp_path)
    root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", root, root),
    )

    assert run_repo_init(_args(tmp_path)) == 0
    first = (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8")
    capsys.readouterr()

    assert run_repo_init(_args(tmp_path)) == 0
    second_output = capsys.readouterr().out
    assert (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8") == first
    assert "updated" not in second_output
    assert first.count("beads:") == 1
    assert first.count("agents:") == 1
    assert first.count("use: builtin@plan") == 1


def test_repo_init_does_not_overwrite_existing_plans_ref(tmp_path: Path) -> None:
    config_path = tmp_path / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "is_sase_managed: true\n"
        "repos:\n"
        "  sidecar:\n"
        "    builtin:\n"
        "      plans:\n"
        "        auto_clone: true\n"
        "        ref:\n"
        "          kind: custom_plan\n",
        encoding="utf-8",
    )

    update = explicit_sidecar_config_update(config_path)

    assert update.changed is True
    assert "kind: custom_plan" in update.updated_text
    assert "use: builtin@plan" not in update.updated_text


def test_legacy_list_sidecar_config_is_refused_with_a_migration_error(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "sase" / "sase.yml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "is_sase_managed: true\n"
        "repos:\n"
        "  sidecar:\n"
        "    - name: research\n"
        "      description: Durable SASE research reports and generated media.\n",
        encoding="utf-8",
    )

    update = explicit_sidecar_config_update(config_path)

    assert update.error is not None
    assert "removed list form" in update.error
    assert "builtin/custom" in update.error
    assert update.changed is False


def test_repo_init_commits_only_owned_project_wiring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test User"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "sase/sase.yml"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-qm", "initial"],
        check=True,
    )
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("leave me alone\n", encoding="utf-8")
    store_root = tmp_path / ".sase" / "sdd"
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: SddStore("local", store_root, store_root),
    )
    monkeypatch.setattr(
        "sase.main.init_workspace_handler.run_before_commit_hook",
        lambda _root: True,
    )

    assert run_repo_init(_args(tmp_path, no_commit=False)) == 0

    subject = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    names = subprocess.run(
        ["git", "-C", str(tmp_path), "show", "--format=", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert subject == "chore: initialize SASE repositories"
    assert names == [".gitignore", "sase/sase.yml"]
    assert unrelated.exists()


def test_materialized_store_refreshes_present_sidecars_and_preserves_lazy_ones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path)
    specs = (SidecarInitSpec(role="plans"), SidecarInitSpec(role="research"))
    plans_root = tmp_path / "sase" / "repos" / "plans"
    (plans_root / ".git").mkdir(parents=True)
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "local",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._has_materialized_sidecar_store",
        lambda _root: True,
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._materialized_compatibility_roles",
        lambda _root: frozenset({"plans", "research"}),
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_materialized_sidecars",
        lambda _root, selected, **_kwargs: (
            seen.append(tuple(spec.role for spec in selected)) or {"plans": plans_root}
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.store.materialize_sdd_store",
        lambda *_args, **_kwargs: pytest.fail("must preserve the sidecar store"),
    )

    assert run_repo_init(_args(tmp_path)) == 0
    assert seen == [("plans",)]


def test_preflight_unavailable_fails_before_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _mark_managed_project(tmp_path)
    specs = (SidecarInitSpec(role="plans"),)
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: specs,
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: (_ for _ in ()).throw(
            SddMaterializationError("Update the provider plugin")
        ),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.initialize_sidecars",
        lambda *_args, **_kwargs: pytest.fail("must fail before materialization"),
    )

    assert run_repo_init(_args(tmp_path)) == 1
    assert "Update the provider plugin" in capsys.readouterr().err


def test_repo_init_check_is_read_only_and_does_not_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mark_managed_project(tmp_path)
    monkeypatch.setattr(
        "sase.main.repo_init_handler._project_provider_sdd_policy",
        lambda _root: "separate_repo",
    )
    monkeypatch.setattr(
        "sase.main.repo_init_handler._configured_sidecar_specs",
        lambda _root: (SidecarInitSpec(role="plans"),),
    )
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.preflight_sidecars",
        lambda *_args: pytest.fail("check must not probe the network"),
    )

    before = (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8")
    assert run_repo_init(_args(tmp_path, check=True)) == 1
    assert (tmp_path / "sase" / "sase.yml").read_text(encoding="utf-8") == before
    assert not (tmp_path / ".gitignore").exists()
