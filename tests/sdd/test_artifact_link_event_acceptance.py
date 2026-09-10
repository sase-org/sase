"""Acceptance coverage for immutable artifact-link event publication."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from typing import Any

import pytest

from sase.bead._sync_publication import PushOutcome
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_cutover_state import read_artifact_link_cutover_marker
from sase.sdd._artifact_link_event_canonical import (
    canonical_artifact_link_event_object,
)
from sase.sdd._artifact_link_outbox_io import (
    inspect_artifact_link_outbox,
    read_artifact_link_outbox_entries,
)
from sase.sdd._artifact_link_publication_retry import (
    sweep_artifact_link_publication_retries,
)
from sase.sdd._artifact_link_publication_retry_state import (
    artifact_link_publication_state_path,
)
from sase.sdd._artifact_link_store_support import sidecar_index_path
from sase.sdd.artifact_link_event_publisher import (
    edge_put_event_from_row,
    edge_remove_event,
    observation_or_put_event_from_row,
    publish_artifact_link_events,
    rows_from_events,
)
from sase.sdd.artifact_link_import_indexes import import_artifact_link_indexes
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_release_evidence import (
    record_artifact_link_release_evidence,
)
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)
from sase.sdd.store import SddStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo


PROJECT_KEY = "gh_sase-org__sase"


@dataclass(frozen=True)
class _Machine:
    name: str
    plans: Path
    research: Path
    store: ArtifactLinkStore


@dataclass(frozen=True)
class _AcceptanceCluster:
    plans_remote: Path
    research_remote: Path
    machine_a: _Machine
    machine_b: _Machine
    bead_project: BeadProject


def test_two_machine_event_publication_has_no_link_index_conflicts_or_bad_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two stale machine clones converge through immutable event files."""

    cluster = _cluster(tmp_path, monkeypatch)
    machine_a = cluster.machine_a
    machine_b = cluster.machine_b
    tracked_bead = cluster.bead_project.create("Tracked rollout", IssueType.PLAN)
    base_race = _edge_put(
        "11111111111111111111111111111111",
        source="plan:202609/race.md",
        relation="related",
        target="plan:202609/target.md",
        description="base race description",
    )
    machine_a_events = (
        *_hot_read_events("a", range(4)),
        _read_event(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaa0000",
            source="agent:repeat.athena.worker",
            target="plan:202609/hot.md",
        ),
        _edge_put(
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbb0000",
            source="plan:202609/described.md",
            relation="related",
            target="research:202609/source.md",
            description="machine A description",
        ),
        _edge_put(
            "cccccccccccccccccccccccccccc0000",
            source="plan:202609/report-new.md",
            relation="related",
            target="research:202609/source.md",
            description="machine A saw the brand-new report",
        ),
        base_race,
        _alias_event(
            "dddddddddddddddddddddddddddd0000",
            old_ref="plan:202609/renamed_old.md",
            new_ref="plan:202609/renamed_new.md",
        ),
        _edge_put(
            "eeeeeeeeeeeeeeeeeeeeeeeeeeee0000",
            source="plan:202609/mixed.md",
            relation="implements",
            target=f"bead:{tracked_bead.id}",
            description="document event projects to the bead store",
            origin="derived",
        ),
    )
    report_a = publish_artifact_link_events(
        machine_a.store,
        machine_a_events,
        push_after_commit=True,
        mutation_origin="machine",
    )

    assert report_a.publication_error is None
    assert report_a.published == len(machine_a_events)
    assert _git_status(machine_a.plans) == ""
    assert _git_status(machine_a.research) == ""
    assert _unmerged_files(machine_a.plans) == ()
    assert _unmerged_files(machine_a.research) == ()

    machine_b_events = (
        *_hot_read_events("b", range(4, 9)),
        machine_a_events[4],
        _read_event(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaa0001",
            source="agent:repeat.athena.worker",
            target="plan:202609/hot.md",
        ),
        _edge_put(
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbb0001",
            source="plan:202609/described.md",
            relation="related",
            target="research:202609/source.md",
            description="machine B description",
        ),
        _edge_put(
            "cccccccccccccccccccccccccccc0001",
            source="plan:202609/report-new.md",
            relation="related",
            target="research:202609/source.md",
            description="machine B saw the brand-new report",
        ),
        _edge_remove(
            "22222222222222222222222222222222",
            source="plan:202609/race.md",
            relation="related",
            target="plan:202609/target.md",
            observed=("11111111111111111111111111111111",),
        ),
        _edge_put(
            "33333333333333333333333333333333",
            source="plan:202609/race.md",
            relation="related",
            target="plan:202609/target.md",
            description="late add survived a stale remover",
        ),
        _edge_put(
            "44444444444444444444444444444444",
            source="plan:202609/race.md",
            relation="related",
            target="plan:202609/target.md",
            description="concurrent update survived a stale remover",
            observed=("11111111111111111111111111111111",),
        ),
        _read_event(
            "dddddddddddddddddddddddddddd0001",
            source="agent:late.athena.worker",
            target="plan:202609/renamed_old.md",
        ),
    )
    report_b = publish_artifact_link_events(
        machine_b.store,
        machine_b_events,
        push_after_commit=True,
        mutation_origin="machine",
    )

    assert report_b.publication_error is None
    assert report_b.published == len(machine_b_events)
    assert _git_status(machine_b.plans) == ""
    assert _git_status(machine_b.research) == ""
    assert _unmerged_files(machine_b.plans) == ()
    assert _unmerged_files(machine_b.research) == ()
    assert _link_index_paths(machine_a.plans) == ()
    assert _link_index_paths(machine_a.research) == ()
    assert _link_index_paths(machine_b.plans) == ()
    assert _link_index_paths(machine_b.research) == ()

    observed_events = {
        str(event["operation_id"]) for event in (*machine_a_events, *machine_b_events)
    }
    assert _remote_event_operation_ids(cluster.plans_remote) == observed_events
    assert _remote_event_operation_ids(cluster.research_remote) == {
        str(event["operation_id"])
        for event in (*machine_a_events, *machine_b_events)
        if _touches_research(event)
    }

    fresh_plans = tmp_path / "fresh" / "plans"
    fresh_research = tmp_path / "fresh" / "research"
    clone(cluster.plans_remote, fresh_plans)
    clone(cluster.research_remote, fresh_research)
    fresh_store = _store(
        plans=fresh_plans,
        research=fresh_research,
        plans_remote=cluster.plans_remote,
        research_remote=cluster.research_remote,
        beads_dir=cluster.bead_project.beads_dir,
    )
    rows = fresh_store.load_durable_rows()

    assert _uses(rows, "agent:reader-a-0.athena.worker", "read", "plan:202609/hot.md")
    assert _uses(rows, "agent:reader-b-8.athena.worker", "read", "plan:202609/hot.md")
    assert _uses(rows, "agent:repeat.athena.worker", "read", "plan:202609/hot.md") == 2
    assert _row_count(rows, "plan:202609/described.md", "related") == 1
    assert _row_count(rows, "plan:202609/report-new.md", "related") == 1
    assert _description(rows, "plan:202609/race.md", "related") == (
        "concurrent update survived a stale remover"
    )
    assert (
        _uses(
            rows,
            "agent:late.athena.worker",
            "read",
            "plan:202609/renamed_new.md",
        )
        == 1
    )
    assert not any(
        row.get("target_ref") == "plan:202609/renamed_old.md" for row in rows
    )
    assert _row_count(rows, "plan:202609/mixed.md", "implements") == 1
    assert cluster.bead_project.show(tracked_bead.id).links

    all_events = (*machine_a_events, *machine_b_events)
    assert rows_from_events(all_events) == rows_from_events(reversed(all_events))
    assert rows_from_events((*all_events, *all_events)) == rows_from_events(all_events)
    for root in (fresh_plans, fresh_research):
        for path in root.glob("link-events/v1/**/*.json"):
            relative = path.relative_to(root).as_posix()
            validated = require_rust_binding("artifact_link_event_validate_bytes")(
                path.read_bytes(),
                relative,
            )
            assert validated["path"] == relative

    assert _link_only_commit_count(fresh_plans) == 2
    assert _link_only_commit_count(fresh_research) == 2


def test_outbox_crash_recovery_retirement_and_retry_ledger_sweep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover after event-write, commit, and publish-boundary interruptions."""

    cluster = _cluster(tmp_path, monkeypatch)
    machine = cluster.machine_a
    event_after_write = _read_event(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaa1111",
        source="agent:crash-write.athena.worker",
        target="plan:202609/hot.md",
    )
    event_object = canonical_artifact_link_event_object(event_after_write)
    partial_path = machine.plans / event_object.relative_path
    partial_path.parent.mkdir(parents=True)
    partial_path.write_bytes(event_object.payload)

    recovered_write = publish_artifact_link_events(
        machine.store,
        (event_after_write,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert recovered_write.published_operation_ids == (
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaa1111",
    )
    assert recovered_write.committed is True
    assert _head_payload(machine.plans, event_object.relative_path) == (
        event_object.payload
    )

    event_after_commit = _read_event(
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbb1111",
        source="agent:crash-commit.athena.worker",
        target="plan:202609/hot.md",
    )
    append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="machine",
        run_id="boundary",
        event=event_after_commit,
        now=10.0,
    )
    committed_once = publish_artifact_link_events(
        machine.store,
        (event_after_commit,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    assert committed_once.published == 1
    assert len(read_artifact_link_outbox_entries(PROJECT_KEY)) == 1
    record_artifact_link_release_evidence(
        project_key=PROJECT_KEY,
        run_id="boundary",
        agent_id="machine",
        qualifying_repo_ids=(str(machine.plans),),
    )

    drained = drain_artifact_link_outbox(
        store=machine.store,
        agent_name="machine",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert drained.drained == 1
    assert drained.committed is False
    assert read_artifact_link_outbox_entries(PROJECT_KEY) == ()
    assert (
        _uses(
            machine.store.load_aggregate()["rows"],
            "agent:crash-commit.athena.worker",
            "read",
            "plan:202609/hot.md",
        )
        == 1
    )

    queued = _read_event(
        "cccccccccccccccccccccccccccc1111",
        source="agent:queue-age.athena.worker",
        target="plan:202609/hot.md",
    )
    append_artifact_link_outbox_event(
        project_key=PROJECT_KEY,
        agent_name="machine",
        run_id="age",
        event=queued,
        now=100.0,
    )
    stats = inspect_artifact_link_outbox(PROJECT_KEY, now=250.0)
    assert stats.event_queued == 1
    assert stats.p95_age_seconds == 150.0

    pushed_before = _remote_event_operation_ids(cluster.plans_remote)
    transient_failure = _read_event(
        "dddddddddddddddddddddddddddd1111",
        source="agent:ledger.athena.worker",
        target="plan:202609/hot.md",
    )

    def _reject_push(
        _repo_root: Path,
        *,
        worker_lock_wait: float = 0.0,
        deadline: float | None = None,
    ) -> PushOutcome:
        return PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="simulated publication crash after commit",
        )

    with monkeypatch.context() as patch:
        patch.setattr("sase.bead.sync.push_bead_work_launch", _reject_push)
        failed_publish = publish_artifact_link_events(
            machine.store,
            (transient_failure,),
            push_after_commit=True,
            mutation_origin="machine",
        )

    assert failed_publish.published_operation_ids == (
        "dddddddddddddddddddddddddddd1111",
    )
    assert failed_publish.publication_error is not None
    assert "Scheduled artifact_link_backfill will retry" in (
        failed_publish.publication_error
    )
    assert _remote_event_operation_ids(cluster.plans_remote) == pushed_before
    assert artifact_link_publication_state_path(PROJECT_KEY).is_file()

    retry_roots = (
        _machine_root(
            role="plans",
            repo_root=machine.plans,
            remote_url=cluster.plans_remote,
        ),
    )
    sweep = sweep_artifact_link_publication_retries(
        retry_roots,
        now=time.time() + 3_700.0,
        deadline=time.monotonic() + 60.0,
        worker_lock_wait=1.0,
    )

    assert sweep.attempted == 1
    assert sweep.published == 1
    assert sweep.failed == 0
    assert "dddddddddddddddddddddddddddd1111" in _remote_event_operation_ids(
        cluster.plans_remote
    )
    assert _git_status(machine.plans) == ""
    assert _unmerged_files(machine.plans) == ()


def test_import_replay_and_managed_markdown_projection_remain_event_consistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy import plus managed markdown projection reduce to one truth."""

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "machine" / "plans"
    _init_local_repo(plans, {"202609/imported.md": "# Imported\n"})
    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": plans},
    )
    legacy = _write_legacy_index(
        plans,
        "plan:202609/imported.md",
        rows=[
            _row(
                source="plan:202609/imported.md",
                relation="related",
                target="plan:202609/target.md",
                description="legacy relationship",
            )
        ],
    )
    commit_all(plans, "legacy link index")

    first = import_artifact_link_indexes(store).plan
    second = import_artifact_link_indexes(store).plan

    assert first.import_id == second.import_id
    assert first.operation_id == second.operation_id
    assert json.dumps(first.baseline_event, sort_keys=True) == json.dumps(
        second.baseline_event,
        sort_keys=True,
    )

    applied = import_artifact_link_indexes(store, apply=True, push_after_commit=False)

    assert applied.applied is True
    assert read_artifact_link_cutover_marker(plans) is not None
    assert any(path.exists() for path in applied.event_paths)
    [row] = store.load_durable_rows()
    assert row["description"] == "legacy relationship"
    assert row["target_ref"] == "plan:202609/target.md"
    assert legacy.exists()

    new_event = _edge_put(
        "eeeeeeeeeeeeeeeeeeeeeeeeeeee1111",
        source="plan:202609/imported.md",
        relation="related",
        target="plan:202609/after-import.md",
        description="event after import",
    )
    publish_artifact_link_events(
        store,
        (new_event,),
        push_after_commit=False,
        mutation_origin="machine",
    )
    reduced_rows = store.load_artifact_rows("plan:202609/imported.md")

    assert {
        (
            row["relation"],
            frozenset((row["source_ref"], row["target_ref"])),
            row["description"],
        )
        for row in reduced_rows
    } == {
        (
            "related",
            frozenset(("plan:202609/imported.md", "plan:202609/target.md")),
            "legacy relationship",
        ),
        (
            "related",
            frozenset(("plan:202609/imported.md", "plan:202609/after-import.md")),
            "event after import",
        ),
    }


def _cluster(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _AcceptanceCluster:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans_remote = _seed_role_remote(
        tmp_path,
        "plans",
        {
            "202609/hot.md": "# Hot report\n",
            "202609/renamed_new.md": "# Renamed report\n",
            "202609/source.md": "# Plan source\n",
        },
    )
    research_remote = _seed_role_remote(
        tmp_path,
        "research",
        {
            "202609/source.md": "# Research source\n",
        },
    )
    bead_project = BeadProject.init(tmp_path / "beads")
    machine_a = _machine(
        tmp_path,
        "machine-a",
        plans_remote=plans_remote,
        research_remote=research_remote,
        beads_dir=bead_project.beads_dir,
    )
    machine_b = _machine(
        tmp_path,
        "machine-b",
        plans_remote=plans_remote,
        research_remote=research_remote,
        beads_dir=bead_project.beads_dir,
    )
    return _AcceptanceCluster(
        plans_remote=plans_remote,
        research_remote=research_remote,
        machine_a=machine_a,
        machine_b=machine_b,
        bead_project=bead_project,
    )


def _machine(
    tmp_path: Path,
    name: str,
    *,
    plans_remote: Path,
    research_remote: Path,
    beads_dir: Path,
) -> _Machine:
    root = tmp_path / name
    plans = root / "plans"
    research = root / "research"
    clone(plans_remote, plans)
    clone(research_remote, research)
    return _Machine(
        name=name,
        plans=plans,
        research=research,
        store=_store(
            plans=plans,
            research=research,
            plans_remote=plans_remote,
            research_remote=research_remote,
            beads_dir=beads_dir,
        ),
    )


def _store(
    *,
    plans: Path,
    research: Path,
    plans_remote: Path,
    research_remote: Path,
    beads_dir: Path | None,
) -> ArtifactLinkStore:
    sdd_store = SddStore(
        "sidecar_repos",
        plans,
        plans,
        provider="github",
        remote_url=str(plans_remote),
        sidecar_dirs={"research": research},
        sidecar_remote_urls={"research": str(research_remote)},
        beads_dir=beads_dir,
    )
    return ArtifactLinkStore.from_sdd_store(sdd_store, PROJECT_KEY)


def _seed_role_remote(
    tmp_path: Path,
    role: str,
    documents: Mapping[str, str],
) -> Path:
    remote = tmp_path / "remotes" / f"{role}.git"
    seed = tmp_path / "seeds" / role
    init_bare_repo(remote)
    clone(remote, seed)
    for relpath, content in documents.items():
        path = seed / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    commit_all(seed, f"seed {role}")
    git(["push", "-u", "origin", "main"], seed)
    return remote


def _init_local_repo(repo: Path, documents: Mapping[str, str]) -> None:
    repo.mkdir(parents=True)
    git(["init", "-q", "-b", "main"], repo)
    git(["config", "user.email", "sase-test@example.invalid"], repo)
    git(["config", "user.name", "SASE Test"], repo)
    for relpath, content in documents.items():
        path = repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    commit_all(repo, "seed local plans")


def _hot_read_events(prefix: str, indexes: Iterable[int]) -> tuple[dict[str, Any], ...]:
    return tuple(
        _read_event(
            f"{prefix * 24}{index:08x}",
            source=f"agent:reader-{prefix}-{index}.athena.worker",
            target="plan:202609/hot.md",
        )
        for index in indexes
    )


def _read_event(operation_id: str, *, source: str, target: str) -> dict[str, Any]:
    return observation_or_put_event_from_row(
        _row(
            source=source,
            relation="read",
            target=target,
            origin="read",
            description=f"{source} read {target}",
            created_by=source,
            created_at="2026-09-10T00:00:00Z",
        ),
        project_key=PROJECT_KEY,
        operation_id=operation_id,
    )


def _edge_put(
    operation_id: str,
    *,
    source: str,
    relation: str,
    target: str,
    description: str,
    origin: str = "manual",
    observed: Sequence[str] = (),
) -> dict[str, Any]:
    return edge_put_event_from_row(
        _row(
            source=source,
            relation=relation,
            target=target,
            origin=origin,
            description=description,
            created_by="agent:publisher.athena.worker",
            created_at="2026-09-10T00:00:00Z",
        ),
        project_key=PROJECT_KEY,
        operation_id=operation_id,
        observed_operation_ids=observed,
    )


def _edge_remove(
    operation_id: str,
    *,
    source: str,
    relation: str,
    target: str,
    observed: Sequence[str],
) -> dict[str, Any]:
    return edge_remove_event(
        project_key=PROJECT_KEY,
        operation_id=operation_id,
        source_ref=source,
        relation=relation,
        target_ref=target,
        created_by="agent:remover.athena.worker",
        origin="manual",
        created_at="2026-09-10T00:00:01Z",
        observed_operation_ids=observed,
    )


def _alias_event(operation_id: str, *, old_ref: str, new_ref: str) -> dict[str, Any]:
    event = {
        "schema_version": int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        "project_key": PROJECT_KEY,
        "operation_id": operation_id,
        "created_by": "agent:renamer.athena.worker",
        "origin": "migrated",
        "created_at": "2026-09-10T00:00:00Z",
        "kind": {
            "type": "alias",
            "old_ref": old_ref,
            "new_ref": new_ref,
        },
    }
    return dict(require_rust_binding("artifact_link_event_canonicalize")(event))


def _machine_root(*, role: str, repo_root: Path, remote_url: Path) -> Any:
    from sase.sdd._artifact_link_machine_store import MachineArtifactLinkRoot

    return MachineArtifactLinkRoot(
        project_key=PROJECT_KEY,
        role=role,
        repo_root=repo_root,
        remote_url=str(remote_url),
    )


def _touches_research(event: Mapping[str, Any]) -> bool:
    kind = event.get("kind")
    if not isinstance(kind, dict):
        return False
    if str(kind.get("type") or "") == "baseline-import":
        rows = kind.get("rows")
        return isinstance(rows, list) and any(
            isinstance(row, dict)
            and (
                str(row.get("source_ref") or "").startswith("research:")
                or str(row.get("target_ref") or "").startswith("research:")
            )
            for row in rows
        )
    if str(kind.get("type") or "") == "alias":
        return str(kind.get("old_ref") or "").startswith("research:") or str(
            kind.get("new_ref") or ""
        ).startswith("research:")
    edge = kind.get("edge")
    if not isinstance(edge, dict):
        return False
    return any(str(value).startswith("research:") for value in edge.values())


def _remote_event_operation_ids(remote: Path) -> set[str]:
    checkout = remote.parent.parent / "inspect" / remote.stem
    if checkout.exists():
        shutil.rmtree(checkout)
    clone(remote, checkout)
    events: set[str] = set()
    for path in checkout.glob("link-events/v1/**/*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        events.add(str(payload["operation_id"]))
    return events


def _link_index_paths(root: Path) -> tuple[Path, ...]:
    links = root / "links"
    if not links.exists():
        return ()
    return tuple(path for path in links.rglob("*") if path.is_file())


def _unmerged_files(repo: Path) -> tuple[str, ...]:
    output = git(["diff", "--name-only", "--diff-filter=U"], repo).stdout
    return tuple(line for line in output.splitlines() if line.strip())


def _git_status(repo: Path) -> str:
    return git(["status", "--porcelain=v1", "--untracked-files=all"], repo).stdout


def _uses(
    rows: Sequence[Mapping[str, Any]],
    source: str,
    relation: str,
    target: str,
) -> int:
    for row in rows:
        if (
            row.get("source_ref") == source
            and row.get("relation") == relation
            and row.get("target_ref") == target
        ):
            return int(row.get("uses") or 0)
    return 0


def _row_count(
    rows: Sequence[Mapping[str, Any]],
    source: str,
    relation: str,
) -> int:
    return sum(
        1
        for row in rows
        if row.get("source_ref") == source and row.get("relation") == relation
    )


def _description(
    rows: Sequence[Mapping[str, Any]],
    source: str,
    relation: str,
) -> str | None:
    for row in rows:
        if row.get("source_ref") == source and row.get("relation") == relation:
            return str(row.get("description") or "")
    return None


def _head_payload(repo: Path, relative_path: Path) -> bytes:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative_path.as_posix()}"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return result.stdout


def _link_only_commit_count(repo: Path) -> int:
    output = git(["log", "--format=%H", "--", "link-events"], repo).stdout
    return len([line for line in output.splitlines() if line.strip()])


def _write_legacy_index(
    repo: Path,
    artifact_ref: str,
    *,
    rows: list[dict[str, object]],
) -> Path:
    path = sidecar_index_path(repo, artifact_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "artifact_ref": artifact_ref,
                "rows": rows,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path
