"""Shared helpers for artifact-link event acceptance tests."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any

import pytest

from sase.bead.project import BeadProject
from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_store_support import sidecar_index_path
from sase.sdd.artifact_link_event_publisher import (
    edge_put_event_from_row,
    edge_remove_event,
    observation_or_put_event_from_row,
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


def _baseline_event(
    operation_id: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    event = {
        "schema_version": int(
            require_rust_binding("artifact_link_event_schema_version")()
        ),
        "project_key": PROJECT_KEY,
        "operation_id": operation_id,
        "created_by": "agent:importer.athena.worker",
        "origin": "migrated",
        "created_at": "2026-09-10T00:00:00Z",
        "kind": {
            "type": "baseline-import",
            "import_id": f"baseline-{operation_id}",
            "source_head": "sha256:" + "b" * 64,
            "rows": [dict(row) for row in rows],
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
