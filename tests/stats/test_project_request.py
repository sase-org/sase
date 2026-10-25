"""Project selectors and inventory-to-wire integration contracts."""

import json
from dataclasses import replace
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from sase.sdd.store import SddStore
from sase.stats.project import ProjectStatsQuery, ProjectStatsUsageError
from sase.stats.project import request as module
from sase.stats.ranges import StatsRange


def _record(key="alpha", label="Alpha Project", state="enabled", aliases=None):
    return ProjectRecordWire(
        schema_version=3,
        project_name=key,
        project_dir=f"/projects/{key}",
        project_file=f"/projects/{key}/{key}.sase",
        archive_file=None,
        workspace_dir=f"/work/{key}",
        state=state,
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        display_name=label,
        aliases=aliases or [],
    )


def _repo(name="alpha", kind="primary", **kwargs):
    return RepoRecord(
        name=name,
        kind=kind,
        project="Alpha Project",
        project_key="alpha",
        path=f"/work/{name}",
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        **kwargs,
    )


@pytest.fixture
def inventory(monkeypatch, tmp_path):
    records = [_record(aliases=["a"]), _record("beta", "Beta Project", "disabled")]
    for index, record in enumerate(records):
        spec = tmp_path / f"{record.project_name}.sase"
        spec.touch()
        records[index] = replace(record, project_file=str(spec))
    repos = [
        _repo(),
        _repo("library", "linked", declared_by="project"),
        _repo("dotfiles", "linked", declared_by="user"),
        _repo("plans", "sidecar", slug="alpha--plans"),
        _repo("agents", "sidecar"),
        _repo("foreign", "external"),
    ]
    monkeypatch.setattr(module, "list_project_records", lambda *a, **k: records)
    monkeypatch.setattr(
        module, "collect_repo_inventory", lambda **k: RepoInventory(tuple(repos))
    )
    monkeypatch.setattr(
        module,
        "resolve_sdd_store",
        lambda root, num: SddStore("in_tree", root / "sdd", root / "sdd"),
    )
    monkeypatch.setattr(module, "sase_home", lambda: Path("/sase-home"))
    monkeypatch.setattr(module, "sase_projects_dir", lambda: Path("/projects"))
    monkeypatch.setattr(
        module, "default_agent_artifact_index_path", lambda: Path("/index.sqlite")
    )
    monkeypatch.setattr(
        module, "globalize_owned_agent_name", lambda name: f"owner.apollo.{name}"
    )
    monkeypatch.setattr(module, "get_model_aliases", lambda: {"opus": "anthropic/opus"})
    monkeypatch.setattr(module, "get_timezone", lambda: ZoneInfo("UTC"))
    return records, repos


def _query(*refs, **kwargs):
    return ProjectStatsQuery(
        range=StatsRange(100, 200, "range", "Range"), project_refs=refs, **kwargs
    )


@pytest.mark.parametrize("ref", ["alpha", "Alpha Project", "ALPHA PROJECT", "a", "+a"])
def test_project_reference_forms_resolve_without_cwd(
    inventory, monkeypatch, tmp_path, ref
):
    monkeypatch.chdir(tmp_path)
    request = module.build_project_stats_request(_query(ref), now_ts=200).data
    assert [row["key"] for row in request["projects"]] == ["alpha"]
    assert request["projects"][0]["label"] == "Alpha Project"
    assert request["include_run_only_projects"] is False


def test_default_selection_keeps_disabled_if_runs_and_unregistered(inventory):
    request = module.build_project_stats_request(_query(), now_ts=200).data
    assert [(row["key"], row["selection"]) for row in request["projects"]] == [
        ("alpha", "always"),
        ("beta", "if_runs"),
    ]
    assert request["include_run_only_projects"] is True
    request = module.build_project_stats_request(
        _query(include_disabled=True), now_ts=200
    ).data
    assert all(row["selection"] == "always" for row in request["projects"])


def test_explicit_disabled_project_is_selected_and_aliases_deduplicate(inventory):
    request = module.build_project_stats_request(
        _query("beta", "alpha", "+a"), now_ts=200
    ).data
    assert [row["key"] for row in request["projects"]] == ["alpha", "beta"]
    assert all(row["selection"] == "always" for row in request["projects"])


def test_unknown_suggests_and_ambiguous_lists_candidates(inventory):
    with pytest.raises(ProjectStatsUsageError, match="did you mean.*alpha"):
        module.build_project_stats_request(_query("alph"), now_ts=200)
    records, _ = inventory
    records[1] = replace(records[1], display_name="Alpha Project")
    with pytest.raises(ProjectStatsUsageError, match="Ambiguous.*alpha, beta"):
        module.build_project_stats_request(_query("Alpha Project"), now_ts=200)


def test_request_golden(inventory):
    result = module.build_project_stats_request(_query("alpha"), now_ts=200)
    golden = Path(__file__).parent / "golden" / "project_request.json"
    assert result.data == json.loads(golden.read_text())
    assert result.issues == ()


def test_clone_choice_is_canonical_then_sorted_registered_then_unavailable(inventory):
    _, repos = inventory
    repos[1] = replace(
        repos[1],
        clones=(
            RepoCloneRecord(8, "/clone/8", True),
            RepoCloneRecord(2, "/clone/2", True),
        ),
    )
    request = module.build_project_stats_request(_query("alpha"), now_ts=200)
    assert request.data["projects"][0]["code_repos"][0]["path"] == "/work/library"
    repos[1] = replace(repos[1], exists=False)
    request = module.build_project_stats_request(_query("alpha"), now_ts=200)
    assert request.data["projects"][0]["code_repos"][0]["path"] == "/clone/2"
    repos[1] = replace(repos[1], clones=())
    request = module.build_project_stats_request(_query("alpha"), now_ts=200)
    assert request.data["projects"][0]["code_repos"][0]["path"] == "/work/library"
    assert any(issue["code"] == "not_cloned" for issue in request.issues)


@pytest.mark.parametrize(
    "storage", ["in_tree", "local", "sidecar_repos", "separate_repo"]
)
def test_plan_store_descriptor(inventory, monkeypatch, storage):
    root = Path("/work/alpha") if storage == "in_tree" else Path("/work/plans")
    plan_dir = root / "sdd" if storage == "in_tree" else root
    monkeypatch.setattr(
        module, "resolve_sdd_store", lambda *args: SddStore(storage, plan_dir, plan_dir)
    )
    result = module.build_project_stats_request(_query("alpha"), now_ts=200)
    assert result.data["projects"][0]["plan_store"] == {
        "storage": storage,
        "repo_path": None if storage == "local" else str(root),
        "plans_dir": "sdd" if storage == "in_tree" else ".",
        "project_filter": "alpha" if storage == "separate_repo" else None,
    }


def test_plan_resolution_failure_preserves_other_sources(inventory, monkeypatch):
    def fail(*args):
        raise ValueError("unresolved store")

    monkeypatch.setattr(module, "resolve_sdd_store", fail)
    result = module.build_project_stats_request(_query("alpha"), now_ts=200)
    assert len(result.data["projects"][0]["code_repos"]) == 2
    assert result.data["projects"][0]["plan_store"]["repo_path"] is None
    assert result.issues[0]["code"] == "plan_store_unresolved"


def test_in_tree_plans_use_the_selected_primary_clone(inventory):
    _, repos = inventory
    repos[0] = replace(
        repos[0], exists=False, clones=(RepoCloneRecord(3, "/clone/3", True),)
    )
    result = module.build_project_stats_request(_query("alpha"), now_ts=200)
    assert result.data["projects"][0]["plan_store"]["repo_path"] == "/clone/3"


def test_sidecars_include_unselected_projects_for_attribution(inventory):
    _, repos = inventory
    repos.append(
        replace(_repo("agents", "sidecar"), project_key="beta", path="/beta/agents")
    )
    result = module.build_project_stats_request(_query("alpha"), now_ts=200)
    assert {row["project_key"] for row in result.data["agents_sidecars"]} == {
        "alpha",
        "beta",
    }


def test_query_render_options_do_not_change_data_request(inventory):
    a = module.build_project_stats_request(_query("alpha"), now_ts=200).data
    b = module.build_project_stats_request(
        _query("alpha", group_by="model", fetch=True), now_ts=200
    ).data
    assert a == b


def test_language_grouping_is_accepted(inventory):
    request = module.build_project_stats_request(
        _query("alpha", group_by="language"), now_ts=200
    )
    assert request.data["projects"][0]["key"] == "alpha"
    with __import__("pytest").raises(ProjectStatsUsageError):
        module.build_project_stats_request(_query("alpha", group_by="nope"), now_ts=200)


def test_remote_identity_uses_core_canonicalization(inventory):
    _, repos = inventory
    repos[1] = replace(repos[1], remote_url="git@github.com:org/library.git")
    result = module.build_project_stats_request(_query("alpha"), now_ts=200)
    assert result.data["projects"][0]["code_repos"][0]["identity"] == "gh:org/library"
