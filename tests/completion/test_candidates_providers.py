"""Tests for kind -> provider dispatch of pre-argparse completion candidates."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase.core.project_lifecycle_facade as project_lifecycle_facade
from sase.bead.model import IssueType, PhaseSize
from sase.bead.project import BeadProject
from sase.completion.candidates.protocol import Candidate
from sase.completion.candidates.providers import candidates_for
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


@pytest.fixture(autouse=True)
def _isolated_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setenv("SASE_COMPLETION_NO_CACHE", "1")
    monkeypatch.delenv("SASE_SDD_BEADS_DIR", raising=False)
    monkeypatch.delenv("SASE_SDD_PLANS_DIR", raising=False)


def test_artifact_relation_candidates_include_cli_slugs() -> None:
    values = {
        candidate.value
        for candidate in candidates_for(
            "artifact_relation", "", project=None, limit=200
        )
    }
    assert {"related", "implements", "supersedes", "derives-from"} <= values


def test_directive_candidates_use_shared_contract_and_hide_final() -> None:
    result = candidates_for("directive", "", project=None, limit=200)

    values = {candidate.value for candidate in result}
    assert {"model", "effort", "id", "wait", "auto"} <= values
    assert "final" not in values
    model = next(candidate for candidate in result if candidate.value == "model")
    assert "Override the LLM model" in model.description
    assert "alias %m" in model.description


def test_candidates_for_unknown_kind_returns_empty_list() -> None:
    assert candidates_for("bogus", "", project=None, limit=200) == []


def test_candidates_for_kind_without_shipped_provider_returns_empty_list() -> None:
    # path/dir are declared ValueKinds but stay shell-native, with no provider.
    assert candidates_for("path", "", project=None, limit=200) == []
    assert candidates_for("dir", "", project=None, limit=200) == []


def test_project_candidates_render_display_name_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="acme_widgets",
        project_dir="/tmp/acme_widgets",
        project_file="/tmp/acme_widgets/acme_widgets.sase",
        archive_file=None,
        workspace_dir="/tmp/acme_widgets/ws",
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name="Acme Widgets",
    )
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: [record],
    )

    result = candidates_for("project", "", project=None, limit=200)

    assert result == [Candidate("Acme Widgets", "enabled")]


def test_project_candidates_falls_back_to_key_without_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="acme_widgets",
        project_dir="/tmp/acme_widgets",
        project_file="/tmp/acme_widgets/acme_widgets.sase",
        archive_file=None,
        workspace_dir="/tmp/acme_widgets/ws",
        state="disabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=False,
    )
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: [record],
    )

    result = candidates_for("project", "", project=None, limit=200)

    assert result == [Candidate("acme_widgets", "disabled")]


def test_project_candidates_respects_prefix_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        ProjectRecordWire(
            schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
            project_name=name,
            project_dir=f"/tmp/{name}",
            project_file=f"/tmp/{name}/{name}.sase",
            archive_file=None,
            workspace_dir=None,
            state="enabled",
            state_explicit=True,
            system_managed=False,
            active_claim_count=0,
            launchable=False,
        )
        for name in ("alpha", "alt", "beta")
    ]
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: records,
    )

    result = candidates_for("project", "al", project=None, limit=1)

    assert result == [Candidate("alpha", "enabled")]


def test_bead_candidates_lists_ids_and_titles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)

    with BeadProject(tmp_path) as project:
        created = project.create(
            "Fix the thing", IssueType.TASK, task_type="bug", size=PhaseSize.SMALL
        )

    result = candidates_for("bead", "", project=None, limit=200)

    assert result == [Candidate(created.id, "Fix the thing")]


def test_bead_candidates_without_a_store_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert candidates_for("bead", "", project=None, limit=200) == []


def test_candidates_for_caches_between_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SASE_COMPLETION_NO_CACHE", raising=False)
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="acme",
        project_dir="/tmp/acme",
        project_file="/tmp/acme/acme.sase",
        archive_file=None,
        workspace_dir=None,
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=False,
    )
    calls: list[int] = []

    def fake_list_project_records(
        *args: object, **kwargs: object
    ) -> list[ProjectRecordWire]:
        calls.append(1)
        return [record]

    monkeypatch.setattr(
        project_lifecycle_facade, "list_project_records", fake_list_project_records
    )

    first = candidates_for("project", "", project=None, limit=200)
    second = candidates_for("project", "", project=None, limit=200)

    assert first == second == [Candidate("acme", "enabled")]
    assert len(calls) == 1


def test_flag_candidates_come_from_the_in_process_registry() -> None:
    result = candidates_for("flag", "", project=None, limit=200)

    keys = {candidate.value for candidate in result}
    assert "ref_sync_gesture" in keys
    assert "coder_inherits_planner_chat" not in keys
    assert "completion_refresh_on_update" not in keys
    ref_sync = next(
        candidate for candidate in result if candidate.value == "ref_sync_gesture"
    )
    assert ref_sync.description.startswith("sunset:")


def test_model_candidates_are_the_builtin_size_aliases() -> None:
    result = candidates_for("model", "", project=None, limit=200)

    assert [candidate.value for candidate in result] == [
        "xsmall",
        "small",
        "medium",
        "large",
        "xlarge",
    ]


def test_snippet_candidates_use_rust_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.rust as rust

    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase").mkdir()
    calls: list[tuple[str | None, str]] = []

    def fake_loader(project: str | None, root_dir: str) -> dict[str, object]:
        calls.append((project, root_dir))
        return {
            "entries": [
                {
                    "trigger": "todo",
                    "source": "user_config",
                    "source_path_display": "ace.snippets",
                },
                {
                    "trigger": "Todo",
                    "source": "user_config",
                    "source_path_display": "ace.snippets",
                },
                {"trigger": "fixit", "source": "xprompt", "xprompt_name": "fix"},
                {"trigger": "", "source": "ignored"},
            ]
        }

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            fake_loader
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    result = candidates_for("snippet", "", project="demo", limit=200)

    assert result == [
        Candidate("todo", "user_config · ace.snippets"),
        Candidate("Todo", "user_config · ace.snippets"),
        Candidate("fixit", "xprompt · fix"),
    ]
    assert calls == [("demo", str(tmp_path))]


@pytest.mark.parametrize("payload", [{"entries": "bad"}, ["bad"]])
def test_snippet_candidates_degrade_on_malformed_payload(
    payload: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.rust as rust

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            (lambda _project, _root_dir: payload)
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    assert candidates_for("snippet", "", project=None, limit=200) == []


def test_snippet_candidates_degrade_on_native_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.rust as rust

    def raise_native_error(_project: str | None, _root_dir: str) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            raise_native_error
            if name == "load_editor_snippet_catalog"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    assert candidates_for("snippet", "", project=None, limit=200) == []


def test_tag_candidates_come_from_the_xprompt_tag_enum() -> None:
    result = candidates_for("tag", "", project=None, limit=200)

    values = {candidate.value for candidate in result}
    assert {"vcs", "commit", "land_epic"} <= values


def test_xprompt_and_skill_candidates_include_packaged_names() -> None:
    xprompts = candidates_for("xprompt", "", project=None, limit=200)
    skills = candidates_for("skill", "", project=None, limit=200)

    assert any(candidate.value == "coder" for candidate in xprompts)
    assert any(candidate.value == "sase_repo" for candidate in skills)


def test_repo_candidates_use_display_name_and_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase._repo_inventory_models import RepoInventory, RepoRecord
    import sase.repo_inventory as repo_inventory

    records = [
        RepoRecord(
            name="sase",
            slug="sase",
            kind="primary",
            project="sase",
            project_key="gh_sase-org__sase",
            path="/tmp/sase",
            exists=True,
            auto_clone=False,
            description=None,
            source="project",
            env_name=None,
        ),
        RepoRecord(
            name="sase-core",
            slug="sase-core",
            kind="linked",
            project="sase",
            project_key="gh_sase-org__sase",
            path="/tmp/sase-core",
            exists=True,
            auto_clone=True,
            description=None,
            source="config",
            env_name=None,
        ),
        RepoRecord(
            name="sase",
            slug="sase",
            kind="sidecar",
            project="sase",
            project_key="gh_sase-org__sase",
            path="/tmp/sase-sidecar",
            exists=True,
            auto_clone=False,
            description=None,
            source="sdd",
            env_name=None,
        ),
        RepoRecord(
            name="other-core",
            slug="other-core",
            kind="linked",
            project="Other",
            project_key="other",
            path="/tmp/other-core",
            exists=True,
            auto_clone=True,
            description=None,
            source="config",
            env_name=None,
        ),
    ]

    def fake_collect_repo_inventory(**kwargs: object) -> RepoInventory:
        project = kwargs.get("project")
        if project is None:
            return RepoInventory(tuple(records))
        return RepoInventory(
            tuple(
                record
                for record in records
                if project in {record.project, record.project_key}
            )
        )

    monkeypatch.setattr(
        repo_inventory,
        "collect_repo_inventory",
        fake_collect_repo_inventory,
    )

    result = candidates_for("repo", "", project=None, limit=200)
    scoped = candidates_for("repo", "", project="sase", limit=200)

    assert result == [
        Candidate("sase", "primary · sase"),
        Candidate("sase-core", "linked · sase"),
        Candidate("other-core", "linked · Other"),
    ]
    assert scoped == [
        Candidate("sase", "primary · sase"),
        Candidate("sase-core", "linked · sase"),
    ]


def test_workspace_candidates_use_display_project_and_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="demo",
        project_dir=str(tmp_path / "demo"),
        project_file=str(tmp_path / "demo" / "demo.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / "demo" / "checkout"),
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name="Demo",
    )
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: [record],
    )
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    registry = tmp_path / "workspaces" / "demo" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        '{"workspaces": {"12": {"role": "claim"}}}',
        encoding="utf-8",
    )

    result = candidates_for("workspace", "", project=None, limit=200)

    assert result == [
        Candidate("0", "Demo primary"),
        Candidate("12", "Demo claim"),
    ]


def test_plugin_candidates_skip_the_sase_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.plugins.inventory import (
        PluginInventory,
        _PluginDistributionRecord,
        _PluginEntryPointRecord,
    )
    import sase.plugins.inventory as plugin_inventory

    inventory = PluginInventory(
        entry_points=(
            _PluginEntryPointRecord(
                group="sase_vcs",
                name="github",
                value="sase_github:plugin",
                package="sase-github",
                version="1.2.3",
                load_status="not_loaded",
            ),
            _PluginEntryPointRecord(
                group="sase_config",
                name="core",
                value="sase.config:plugin",
                package="sase",
                version="0.0.0",
                load_status="not_loaded",
            ),
        ),
        distributions=(
            _PluginDistributionRecord("sase-github", "1.2.3", ("sase_vcs:github",)),
            _PluginDistributionRecord("sase", "0.0.0", ("sase_config:core",)),
        ),
        disabled_env=(),
    )
    monkeypatch.setattr(
        plugin_inventory,
        "collect_plugin_inventory",
        lambda **kwargs: inventory,
    )

    result = candidates_for("plugin", "", project=None, limit=200)

    assert Candidate("sase-github", "1.2.3") in result
    assert Candidate("github", "sase-github") in result
    assert all(candidate.value not in {"sase", "core"} for candidate in result)


def test_proc_candidates_list_ids_and_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.core.rust as rust

    store = tmp_path / "sase-home" / "procs" / "procs.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda _path: (
                {
                    "schema_version": 3,
                    "procs": [
                        {
                            "proc_id": "abc123def456",
                            "label": "just check",
                            "status": "running",
                        }
                    ],
                }
                if name == "read_procs_snapshot"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("proc", "", project=None, limit=200)

    assert result == [Candidate("abc123def456", "running just check")]


def test_artifact_candidates_use_indexed_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.rust as rust

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda _path, _filters: (
                [
                    {
                        "id": "explicit:0123456789abcdef01234567",
                        "label": "screenshot.png",
                    }
                ]
                if name == "artifact_files_query"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("artifact", "", project=None, limit=200)

    assert result == [Candidate("explicit:0123456789abcdef01234567", "screenshot.png")]


def test_artifact_ref_candidates_emit_canonical_file_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.core.rust as rust

    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda _path, _filters: (
                [
                    {
                        "id": "explicit:0123456789abcdef01234567",
                        "label": "screenshot.png",
                    }
                ]
                if name == "artifact_files_query"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("artifact_ref", "", project=None, limit=200)

    assert result == [
        Candidate("file:explicit:0123456789abcdef01234567", "screenshot.png")
    ]


def test_patch_candidates_use_rust_parse_and_display_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.core.project_lifecycle_wire import (
        PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        ProjectRecordWire,
    )
    import sase.core.project_lifecycle_facade as project_lifecycle_facade
    import sase.core.rust as rust

    spec = tmp_path / "demo.sase"
    spec.write_bytes(b"NAME: alpha\n")
    record = ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name="demo_key",
        project_dir=str(tmp_path),
        project_file=str(spec),
        archive_file=None,
        workspace_dir=None,
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name="Demo",
    )
    monkeypatch.setattr(
        project_lifecycle_facade,
        "list_project_records",
        lambda *args, **kwargs: [record],
    )
    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda _path, _data: (
                [
                    {
                        "name": "alpha",
                        "status": "InReview",
                        "project_display_name": "Demo",
                    }
                ]
                if name == "parse_patch_project_bytes"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("patch", "", project=None, limit=200)

    assert result == [Candidate("alpha", "InReview · Demo")]


def test_plan_candidates_emit_canonical_references(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.core.paths as core_paths
    import sase.core.rust as rust

    plans = tmp_path / "plans"
    month = plans / "202608"
    month.mkdir(parents=True)
    (month / "cli_completion.md").write_text("# Plan\n", encoding="utf-8")
    monkeypatch.setattr(core_paths, "sase_subdir", lambda name: plans)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        rust,
        "require_rust_binding",
        lambda name: (
            lambda path, _roots: (
                f"plan:{Path(path).parent.name}/{Path(path).name}"
                if name == "plan_reference_canonicalize"
                else (_ for _ in ()).throw(AssertionError(name))
            )
        ),
    )

    result = candidates_for("plan", "", project=None, limit=200)

    assert result == [Candidate("plan:202608/cli_completion.md", "cli_completion")]


def _write_glossary_project(root: Path) -> None:
    config = root / "sase" / "sase.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "memory:\n"
        "  glossary:\n"
        "    Agent Hood:\n"
        "      definition: >-\n"
        "        An agent hood is a group of agents. It has a second sentence.\n"
        "      aliases:\n"
        "        - hood\n"
        "        - agent neighborhood\n"
        "    Stitch:\n"
        "      definition: A stitch is one recorded VCS change\n",
        encoding="utf-8",
    )


def test_glossary_candidates_use_slug_references_and_first_sentences(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_glossary_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = candidates_for("glossary", "", project=None, limit=200)

    # Slug form: `sase glossary` resolves references case- and
    # separator-insensitively, so a hyphenated value never needs quoting.
    assert result == [
        Candidate("agent-hood", "An agent hood is a group of agents"),
        Candidate("hood", "alias of Agent Hood"),
        Candidate("agent-neighborhood", "alias of Agent Hood"),
        Candidate("stitch", "A stitch is one recorded VCS change"),
    ]


def test_glossary_candidates_filter_by_prefix_and_survive_missing_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    _write_glossary_project(project)
    monkeypatch.chdir(project)
    assert [
        candidate.value
        for candidate in candidates_for("glossary", "agent-", project=None, limit=200)
    ] == ["agent-hood", "agent-neighborhood"]

    empty = tmp_path / "elsewhere"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert candidates_for("glossary", "", project=None, limit=200) == []


def test_provider_errors_return_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.feature_flags.registry as flag_registry

    monkeypatch.setattr(
        flag_registry,
        "feature_flag_definitions",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert candidates_for("flag", "", project=None, limit=200) == []
