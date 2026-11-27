"""End-to-end regression for the concurrent epic ID collision chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.bead.config import load_config, save_config
from sase.bead.model import IssueType, PhaseSize
from sase.bead.project import BeadProject
from sase.bead.sync import refresh_bead_store
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN
from tests.test_bead.cli_work_from_plan_publication_helpers import (
    linked_bead_id,
    stable_plan_formatting,
)
from tests.test_bead.cli_work_helpers import FakeLaunchResult
from tests.test_bead.sync_conflict_regression_helpers import (
    _assert_store_matches_fresh_reduction,
    _bead_artifact_bytes,
    _clone,
    _commit,
    _git,
)
from tests.test_bead.sync_test_helpers import init_git_repo


def _seed_three_clones(tmp_path: Path) -> tuple[Path, dict[str, Path], dict[str, Path]]:
    """Create one bead remote and two plan-sidecar clones for the launchers."""
    beads_remote = tmp_path / "beads.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(beads_remote))

    beads_seed = tmp_path / "beads-seed"
    beads_seed.mkdir()
    init_git_repo(beads_seed)
    _git(beads_seed, "branch", "-M", "main")
    (beads_seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(beads_seed, beads_dirname="beads"):
        pass
    config = load_config(beads_seed / "beads")
    config["issue_prefix"] = "p"
    save_config(beads_seed / "beads", config)
    _commit(beads_seed, "Initialize bead store")
    _git(beads_seed, "remote", "add", "origin", str(beads_remote))
    _git(beads_seed, "push", "-u", "origin", "main")

    beads = {name: tmp_path / f"beads-{name}" for name in ("a", "b", "c")}
    for clone in beads.values():
        _clone(beads_remote, clone)

    plans_remote = tmp_path / "plans.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(plans_remote))
    plans_seed = tmp_path / "plans-seed"
    plans_seed.mkdir()
    init_git_repo(plans_seed)
    _git(plans_seed, "branch", "-M", "main")
    (plans_seed / "README.md").write_text("plans\n", encoding="utf-8")
    _commit(plans_seed, "Initialize plans sidecar")
    _git(plans_seed, "remote", "add", "origin", str(plans_remote))
    _git(plans_seed, "push", "-u", "origin", "main")

    plans = {name: tmp_path / f"plans-{name}" for name in ("b", "c")}
    for clone in plans.values():
        _clone(plans_remote, clone)
    return beads_remote, beads, plans


def _split_store(plans: Path, beads: Path) -> tuple[Any, Any]:
    from sase.bead.cli_common import _BeadsLocation

    plans_remote = _git(plans, "remote", "get-url", "origin").stdout.strip()
    beads_remote = _git(beads, "remote", "get-url", "origin").stdout.strip()
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url=plans_remote,
        beads_dir=beads / "beads",
        beads_remote_url=beads_remote,
    )
    location = _BeadsLocation(
        root=beads,
        beads_dirname="beads",
        storage=store.storage,
        store=store,
    )
    return location, store


def _write_plan(project_dir: Path, name: str, title: str) -> Path:
    source = project_dir / f"{name}.md"
    source.write_text(
        EPIC_PLAN.replace("title: Plan-file rollout", f"title: {title}"),
        encoding="utf-8",
    )
    source.with_name(f"{source.stem}.plan-decisions.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "definitions": [{"id": "grouping", "prompt": "Choose grouping"}],
            }
        ),
        encoding="utf-8",
    )
    return source


@pytest.mark.parametrize(
    "force_replay",
    [False, True],
    ids=["published-recreation-relocates", "publication-conflict-replays"],
)
@pytest.mark.usefixtures("fake_cli_work_macros")
def test_three_clone_epic_launch_collision_chain(
    force_replay: bool,
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale plan launch relocates or replays and all clones converge."""
    import sase.bead.sync as sync_module

    from sase.bead.cli_work_from_plan import work_from_plan_file

    stable_plan_formatting(monkeypatch)
    monkeypatch.setattr("sase.sdd.files.get_yyyymm", lambda: "202607")
    _beads_remote, bead_clones, plan_clones = _seed_three_clones(tmp_path)
    beads_a, beads_b, beads_c = (
        bead_clones["a"],
        bead_clones["b"],
        bead_clones["c"],
    )

    # Clone A publishes p-1 after B and C have cloned the empty store.
    with BeadProject(beads_a, beads_dirname="beads") as project:
        published_task = project.create(
            "Published task",
            IssueType.TASK,
            task_type="bug",
            size=PhaseSize.SMALL,
        )
    assert published_task.id == "p-1"
    _commit(beads_a, "Publish p-1 task")
    _git(beads_a, "push")

    # Clone C integrates that task but stays unaware of B's later publications.
    refresh_bead_store(beads_c / "beads")
    assert (
        _git(beads_c, "rev-parse", "HEAD").stdout
        == _git(beads_a, "rev-parse", "HEAD").stdout
    )
    assert load_config(beads_c / "beads")["next_counter"] == 2

    # Reproduce the incident's stale minting window for both launch clones.
    monkeypatch.setattr("sase.bead.sync.refresh_bead_store", lambda *_a, **_k: None)
    launch_calls: list[object] = []

    def fake_launch(*_args: object, **_kwargs: object) -> list[FakeLaunchResult]:
        launch_calls.append(True)
        return [FakeLaunchResult()]

    monkeypatch.setattr(
        "sase.bead.cli_work_handler_publish.launch_bead_work_agents",
        fake_launch,
    )

    publication_outcomes: list[tuple[Path, Any]] = []
    real_push = sync_module.push_bead_work_launch

    def record_publication(beads_dir: Path, **kwargs: Any) -> Any:
        outcome = real_push(beads_dir, **kwargs)
        publication_outcomes.append((beads_dir, outcome))
        return outcome

    monkeypatch.setattr(sync_module, "push_bead_work_launch", record_publication)

    def launch_from_clone(name: str):
        location, store = _split_store(plan_clones[name], bead_clones[name])
        monkeypatch.setattr(
            "sase.bead.cli_work_from_plan._resolve_context",
            lambda *, dry_run: (location, store, project_dir),
        )
        source = _write_plan(project_dir, f"{name}_collision", f"{name.title()} epic")
        return work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    # B's p-1 epic collides with A's task. It moves to p-2, is rolled back,
    # and the corrected counter makes the retry mint p-3.
    result_b = launch_from_clone("b")
    assert result_b.epic_id == "p-3"
    assert result_b.phase_bead_ids == ("p-3.1", "p-3.2", "p-3.3")
    b_relocations = [
        relocation
        for path, outcome in publication_outcomes
        if path == beads_b / "beads"
        for relocation in getattr(outcome, "bead_relocations", ())
    ]
    assert any(
        relocation.old_id == "p-1" and relocation.new_id == "p-2"
        for relocation in b_relocations
    )
    p2_kinds = [
        json.loads(line)["payload"]["kind"]
        for line in (beads_b / "beads/events/streams/p-2.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert p2_kinds.index("issue_created") < p2_kinds.index("issue_removed")

    resolver_calls = 0
    if force_replay:
        import sase.sdd._semantic_conflict_resolver as resolver_module

        real_resolve = resolver_module.resolve_semantic_conflicts

        def fail_first_resolution(cwd: str | Path = ".", **kwargs: Any) -> Any:
            nonlocal resolver_calls
            resolver_calls += 1
            if resolver_calls == 1:
                return resolver_module._SemanticConflictResolution(
                    False, "forced relocation failure for the incident replay test"
                )
            return real_resolve(cwd, **kwargs)

        monkeypatch.setattr(
            resolver_module,
            "resolve_semantic_conflicts",
            fail_first_resolution,
        )

    # C's p-2 creation meets B's published create/remove p-2 history. In the
    # normal path only C moves; when semantic repair is forced to fail, the
    # approved replay path rescues its graph and retries from upstream.
    result_c = launch_from_clone("c")
    assert result_c.launched is True
    if force_replay:
        assert result_c.epic_id == "p-4"
        assert resolver_calls == 1
        replay_outcomes = [
            outcome
            for path, outcome in publication_outcomes
            if path == beads_c / "beads"
        ]
        assert replay_outcomes[0].error is not None
        assert replay_outcomes[0].integration_status == "aborted_unsupported_conflicts"
        refs = _git(beads_c, "for-each-ref", "refs/sase/recovery/").stdout.splitlines()
        assert len(refs) == 1
        assert "p-2" in refs[0]
    else:
        assert result_c.epic_id == "p-5"
        c_relocations = [
            relocation
            for path, outcome in publication_outcomes
            if path == beads_c / "beads"
            for relocation in getattr(outcome, "bead_relocations", ())
        ]
        assert any(
            relocation.old_id == "p-2" and relocation.new_id == "p-4"
            for relocation in c_relocations
        )
    assert len(launch_calls) == 2
    assert linked_bead_id(result_b.archived_plan_path) == result_b.epic_id
    assert linked_bead_id(result_c.archived_plan_path) == result_c.epic_id

    # Refresh every real clone after the last publication and compare both the
    # canonical streams and a fresh reduction of each store.
    for clone in (beads_a, beads_b, beads_c):
        refresh_bead_store(clone / "beads")
        _assert_store_matches_fresh_reduction(clone)
    canonical = _bead_artifact_bytes(beads_a)
    assert _bead_artifact_bytes(beads_b) == canonical
    assert _bead_artifact_bytes(beads_c) == canonical
    with BeadProject(beads_a, beads_dirname="beads") as project:
        current_ids = {issue.id for issue in project.list_issues()}
    assert {"p-1", "p-3", result_c.epic_id} <= current_ids
    assert "p-2" not in current_ids
