"""Regression tests for stale-revision outbox repair.

The fixture outbox is written at schema 6 the way production rows look
today (no ``requested_revision``, revision scope), backed by real git
repositories: a primary checkout with a linear ``A -> M -> S -> T`` history
and a linked clone carrying an unrelated commit ``L``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync.git import run_git
from sase.agents_sync.inventory_models import InventoryRun
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.agents_sync.prompt_archive.deferred import prompt_runs_by_request
from sase.agents_sync.publication_completion import stale_requested_revision_rows
from sase.agents_sync.publication_outbox import (
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    AgentPublicationOutboxItem,
)
from sase.agents_sync.publication_outbox_models import PUBLICATION_SCOPE_LINKED
import sase.agents_sync._publication_revision_repair_apply as repair_application
import sase.agents_sync._publication_revision_repair_classification as repair_classification
from sase.agents_sync.publication_revision_repair import (
    REPAIR_REVISIONS_AUDIT_FILENAME,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.main.parser import create_parser
from sase.sase_agent import sase_agent_ref_for_turn
from tests.agents_sync.git_sync_fixtures import git, plant_fulfilled_publication

_OWNER = AgentOwnerIdentity("alice", "athena")


def _commit(repo: Path, name: str) -> str:
    (repo / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", name)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Tests")
    git(path, "config", "user.email", "tests@example.test")
    return path


@pytest.fixture
def histories(tmp_path: Path) -> dict[str, str]:
    """Build the primary and linked histories, returning labeled SHAs."""

    primary = _git_repo(tmp_path / "primary")
    shas = {"primary": str(primary)}
    for name in ("A", "M", "S", "T"):
        shas[name] = _commit(primary, f"commit-{name}")
    linked = _git_repo(tmp_path / "linked")
    shas["L"] = _commit(linked, "linked-commit")
    shas["linked"] = str(linked)
    return shas


def _target(histories: dict[str, str], tmp_path: Path) -> ProjectTarget:
    primary = Path(histories["primary"])
    return ProjectTarget(
        "proj",
        "Project",
        primary,
        (primary.resolve(),),
        tmp_path / "sidecar",
        "unused",
        "primary",
    )


def _item(
    local: str,
    revision: str,
    *,
    attempts: int = 0,
    last_error: str | None = None,
    quarantined: bool = False,
) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=local,
        global_agent=f"alice.athena.{local}",
        primary_revision=revision,
        local_hood=local,
        attempts=attempts,
        last_error=last_error,
        quarantined=quarantined,
    )


def _write_outbox(tmp_path: Path, rows: list[AgentPublicationOutboxItem]) -> Path:
    path = tmp_path / "projects" / "proj" / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    payload = []
    for row in rows:
        record = row.to_json_dict()
        record.pop("requested_revision")
        payload.append(record)
    path.write_text(
        json.dumps({"schema_version": 6, "items": payload}), encoding="utf-8"
    )
    return path


def _commits(
    runs: list[tuple[str, list[str]]],
) -> dict[tuple[str, str], list[str]]:
    return {(local, f"alice.athena.{local}"): list(shas) for local, shas in runs}


def test_classify_row_covers_every_repair_outcome(
    histories: dict[str, str], tmp_path: Path
) -> None:
    """Each stale shape classifies through real git ancestry facts."""

    target = _target(histories, tmp_path)
    facts = repair_classification._GitFacts(
        target, git_runner=run_git, linked_dirs=(Path(histories["linked"]),)
    )
    commits = _commits(
        [
            ("w-unch", [histories["T"]]),
            ("w-par", [histories["S"]]),
            ("w-reb", [histories["T"]]),
            ("w-link", [histories["T"]]),
            ("w-un", [histories["T"]]),
        ]
    )
    rows = {
        name: repair_classification._classify_row(_item(name, revision), commits, facts)
        for name, revision in (
            ("w-unch", histories["T"]),
            ("w-par", histories["M"]),
            ("w-reb", histories["A"]),
            ("w-link", histories["L"]),
            ("w-un", "d" * 40),
        )
    }
    assert rows["w-unch"].action == "unchanged"
    assert rows["w-unch"].fulfilling_revision is None

    parent = rows["w-par"]
    assert parent.action == "repaired"
    assert parent.fulfilling_revision == histories["S"]
    assert parent.evidence_commit == histories["S"]

    rebased = rows["w-reb"]
    assert rebased.action == "repaired"
    assert rebased.fulfilling_revision == histories["T"]

    linked = rows["w-link"]
    assert linked.action == "linked"
    assert linked.new_scope == PUBLICATION_SCOPE_LINKED

    unresolved = rows["w-un"]
    assert unresolved.action == "unresolved"
    assert unresolved.fulfilling_revision is None


def test_run_commits_index_earliest_first() -> None:
    """Agent commit lists preserve inventory order across runs."""

    identity = AgentIdentitySnapshot(_OWNER)
    assert sase_agent_ref_for_turn("w-par", identity).local_name == "w-par"
    run_one = InventoryRun(
        "run-1",
        "w-par",
        "alice.athena.w-par",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (),
        (CommitRecord("b" * 40, "second", 2),),
        None,
        None,
        None,
        None,
        (),
        "20260723120001",
    )
    run_two = InventoryRun(
        "run-2",
        "w-par",
        "alice.athena.w-par",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:02:00+00:00",
        None,
        (),
        (CommitRecord("c" * 40, "third", 3),),
        None,
        None,
        None,
        None,
        (),
        "20260723120002",
    )
    indexed = repair_classification._run_commits_by_agent((run_one, run_two), identity)
    item = _item("w-par", "a" * 40)
    assert repair_classification._row_commit_shas(item, indexed) == ["b" * 40, "c" * 40]


def _inventory_run(local: str, shas: list[str]) -> InventoryRun:
    return InventoryRun(
        f"run-{local}",
        local,
        f"alice.athena.{local}",
        "completed",
        "2026-07-23T12:00:00+00:00",
        "2026-07-23T12:01:00+00:00",
        None,
        (),
        tuple(
            CommitRecord(sha, f"subject {sha[:8]}", index)
            for index, sha in enumerate(shas)
        ),
        None,
        None,
        None,
        None,
        (),
        "20260723120001",
    )


@pytest.fixture
def staged_repair(
    histories: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ProjectTarget, Path, dict[str, str]]:
    """Stage the schema-6 fixture outbox with stubbed inventory discovery."""

    from sase.agents_sync.inventory import ProjectHoodInventory

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    target = _target(histories, tmp_path)
    rows = [
        _item("w-unch", histories["T"]),
        _item("w-par", histories["M"]),
        _item("w-reb", histories["A"]),
        _item("w-link", histories["L"]),
        _item(
            "w-un",
            "d" * 40,
            attempts=2,
            last_error="push rejected",
            quarantined=True,
        ),
        _item("w-col", histories["T"]),
        _item("w-col", histories["M"]),
    ]
    outbox = _write_outbox(tmp_path, rows)
    runs = [
        _inventory_run("w-unch", [histories["T"]]),
        _inventory_run("w-par", [histories["S"]]),
        _inventory_run("w-reb", [histories["T"]]),
        _inventory_run("w-link", [histories["T"]]),
        _inventory_run("w-un", [histories["T"]]),
        _inventory_run("w-col", [histories["T"]]),
    ]
    inventory = ProjectHoodInventory(_OWNER, "proj", tuple(runs))
    monkeypatch.setattr(
        repair_classification,
        "build_project_hood_inventory",
        lambda _target, _identity, *, git_runner=None, requested_hoods=None: inventory,
    )
    linked_record = SimpleNamespace(
        kind="linked",
        project_key="proj",
        path=histories["linked"],
        clones=(),
    )
    monkeypatch.setattr(
        repair_classification,
        "collect_repo_inventory",
        lambda *args, **kwargs: SimpleNamespace(records=(linked_record,)),
    )
    return target, outbox, histories


def test_report_mode_writes_nothing(
    staged_repair: tuple[ProjectTarget, Path, dict[str, str]],
) -> None:
    """Report mode classifies every row without touching disk state."""

    from sase.agents_sync.publication_outbox import list_agent_publications as list_pubs

    target, outbox, _histories = staged_repair
    before = outbox.read_bytes()
    rows_before = len(list_pubs("proj"))
    report = repair_classification.classify_project_revisions(
        target, _OWNER, git_runner=run_git
    )

    assert sorted((row.global_agent, row.action) for row in report.rows) == [
        ("alice.athena.w-col", "repaired"),
        ("alice.athena.w-col", "unchanged"),
        ("alice.athena.w-link", "linked"),
        ("alice.athena.w-par", "repaired"),
        ("alice.athena.w-reb", "repaired"),
        ("alice.athena.w-un", "unresolved"),
        ("alice.athena.w-unch", "unchanged"),
    ]
    assert report.changed == 4
    assert len(list_pubs("proj")) == rows_before == 7
    assert outbox.read_bytes() == before
    assert not (outbox.parent / REPAIR_REVISIONS_AUDIT_FILENAME).exists()


def test_apply_rekeys_relinks_and_merges_with_audit(
    staged_repair: tuple[ProjectTarget, Path, dict[str, str]],
) -> None:
    """Apply rewrites the outbox, preserves the unresolved row, and audits."""

    from sase.agents_sync.publication_outbox import list_agent_publications as list_pubs

    target, outbox, histories = staged_repair
    report = repair_classification.classify_project_revisions(
        target, _OWNER, git_runner=run_git
    )
    applied = repair_application.apply_project_revisions(target, report)

    assert applied.applied
    assert applied.audit_path is not None
    upgraded = json.loads(outbox.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == PUBLICATION_OUTBOX_SCHEMA_VERSION
    by_global = [row["global_agent"] for row in upgraded["items"]]
    assert by_global.count("alice.athena.w-col") == 1

    remaining = list_pubs("proj")
    assert len(remaining) == 6
    items = {item.global_agent: item for item in remaining}

    repaired_par = items["alice.athena.w-par"]
    assert repaired_par.primary_revision == histories["S"]
    assert repaired_par.original_revision == histories["M"]
    assert repaired_par.attempts == 0
    repaired_reb = items["alice.athena.w-reb"]
    assert repaired_reb.primary_revision == histories["T"]
    assert repaired_reb.original_revision == histories["A"]
    assert items["alice.athena.w-link"].scope == PUBLICATION_SCOPE_LINKED
    assert items["alice.athena.w-link"].primary_revision == histories["L"]

    unresolved = items["alice.athena.w-un"]
    assert unresolved.primary_revision == "d" * 40
    assert unresolved.original_revision == "d" * 40
    assert unresolved.quarantined
    assert unresolved.attempts == 2
    assert unresolved.last_error == "push rejected"

    audit = [
        json.loads(line)
        for line in Path(applied.audit_path).read_text(encoding="utf-8").splitlines()
    ]
    actions = {(entry["global_agent"], entry["action"]) for entry in audit}
    assert ("alice.athena.w-par", "repaired") in actions
    assert ("alice.athena.w-reb", "repaired") in actions
    assert ("alice.athena.w-link", "linked") in actions
    assert ("alice.athena.w-col", "merged") in actions
    assert not any(entry["global_agent"] == "alice.athena.w-un" for entry in audit)
    assert not any(entry["global_agent"] == "alice.athena.w-unch" for entry in audit)
    par_entry = next(
        entry
        for entry in audit
        if (entry["global_agent"], entry["action"])
        == ("alice.athena.w-par", "repaired")
    )
    assert par_entry["original_revision"] == histories["M"]
    assert par_entry["fulfilling_revision"] == histories["S"]
    assert par_entry["evidence_commit"] == histories["S"]


def test_apply_is_idempotent_on_a_second_run(
    staged_repair: tuple[ProjectTarget, Path, dict[str, str]],
) -> None:
    """A second apply changes no bytes and appends no audit entries."""

    from sase.agents_sync.publication_outbox import list_agent_publications as list_pubs

    target, outbox, _histories = staged_repair
    report = repair_classification.classify_project_revisions(
        target, _OWNER, git_runner=run_git
    )
    first = repair_application.apply_project_revisions(target, report)
    assert first.audit_path is not None
    outbox_bytes = outbox.read_bytes()
    audit_bytes = Path(first.audit_path).read_bytes()

    second_report = repair_classification.classify_project_revisions(
        target, _OWNER, git_runner=run_git
    )
    assert second_report.changed == 0
    second = repair_application.apply_project_revisions(target, second_report)

    assert second.applied
    assert second.audit_path is None
    assert outbox.read_bytes() == outbox_bytes
    assert Path(first.audit_path).read_bytes() == audit_bytes
    assert len(list_pubs("proj")) == 6


def test_repaired_row_fulfills_completion_and_prompt_restore(
    staged_repair: tuple[ProjectTarget, Path, dict[str, str]],
) -> None:
    """After apply, the gates accept the repaired revision and its source."""

    from sase.agents_sync.publication_completion import (
        _publication_request_completion,
    )
    from sase.agents_sync.publication_outbox import list_agent_publications as list_pubs

    target, _outbox, histories = staged_repair
    report = repair_classification.classify_project_revisions(
        target, _OWNER, git_runner=run_git
    )
    repair_application.apply_project_revisions(target, report)

    repaired = next(
        item for item in list_pubs("proj") if item.global_agent == "alice.athena.w-par"
    )
    assert repaired.primary_revision == histories["S"]
    target.sidecar_path.mkdir(parents=True, exist_ok=True)
    plant_fulfilled_publication(
        target.sidecar_path,
        owner=_OWNER,
        local_agent="w-par",
        global_agent="alice.athena.w-par",
        revision=histories["S"],
        local_hood="w-par",
    )
    decision = _publication_request_completion(target, repaired, _OWNER)
    assert decision.fulfilled

    plant_fulfilled_publication(
        target.sidecar_path,
        owner=_OWNER,
        local_agent="w-un",
        global_agent="alice.athena.w-un",
        revision=histories["S"],
        local_hood="w-un",
    )
    stale = stale_requested_revision_rows(
        target,
        tuple(
            item
            for item in list_pubs("proj")
            if item.global_agent == "alice.athena.w-un"
        ),
        _OWNER,
    )
    assert [item.global_agent for item in stale] == ["alice.athena.w-un"]

    inventory = SimpleNamespace(
        runs=(
            SimpleNamespace(
                local_name="w-par",
                global_name="alice.athena.w-par",
                commits=(SimpleNamespace(sha=histories["S"]),),
                source_label=str(target.primary_checkout),
            ),
        )
    )
    identity = AgentIdentitySnapshot(_OWNER)
    prompt_runs = prompt_runs_by_request(inventory, identity)
    projected = sase_agent_ref_for_turn("w-par", identity).local_name
    assert (projected, histories["S"]) in prompt_runs


def test_parser_accepts_repair_revisions_with_apply() -> None:
    """The repair flags parse, including short aliases and JSON output."""

    args = create_parser().parse_args(
        [
            "agent",
            "sync",
            "--repair-revisions",
            "--project",
            "one",
            "--apply",
            "--json",
        ]
    )
    assert args.repair_revisions
    assert args.apply
    assert args.project == ["one"]
    assert args.json

    short = create_parser().parse_args(["agent", "sync", "-R", "-p", "one", "-a"])
    assert short.repair_revisions
    assert short.apply
    assert short.project == ["one"]


@pytest.mark.parametrize(
    "extra",
    (
        [],
        ["--project", "one", "--project", "two"],
        ["--project", "one", "--check"],
        ["--project", "one", "--repair-manifest"],
        ["--project", "one", "--retry-quarantined"],
        ["--project", "one", "--apply", "--check"],
    ),
)
def test_parser_rejects_repair_revisions_misuse(extra: list[str]) -> None:
    """The repair runs report-first for exactly one project."""

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--repair-revisions", *extra])
    assert exc_info.value.code == 2


def test_parser_rejects_apply_without_repair_revisions() -> None:
    """The apply flag belongs to the revision repair only."""

    with pytest.raises(SystemExit) as exc_info:
        create_parser().parse_args(["agent", "sync", "--apply", "--project", "one"])
    assert exc_info.value.code == 2
