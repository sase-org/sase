"""A multi-batch scheduler drain builds the project hood inventory once."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from sase.agents_sync import (
    _commit_publication_drain as publication_drain,
    _commit_publication_locked as publication_locked,
    _publication_job_drain as job_drain,
    inventory_reuse,
)
from sase.agents_sync.git import run_git
from sase.agents_sync.inventory_models import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
    list_agent_publications,
)
from sase.agents_sync.v2_io import owner_manifest_path, v2_json_bytes
from sase.agents_sync.v2_models import (
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync._commit_publication_bounded_drain_helpers import (
    configure_target,
)
from tests.agents_sync.commit_publication_fixtures import fulfilled_completion, git

_OWNER = AgentOwnerIdentity("alice", "athena")
_HOOD = "foo"
# One more than the job's 25-row hood batch, plus a few, forces two batches.
_ROWS = 30


def _commit_primary(primary: Path, message: str) -> None:
    git(primary, "commit", "--allow-empty", "-m", message)


def _init_primary(target: ProjectTarget) -> None:
    primary = target.primary_checkout
    git(primary, "init")
    git(primary, "config", "user.name", "Tests")
    git(primary, "config", "user.email", "tests@example.test")
    _commit_primary(primary, "seed")


def _publish_hood(on_publish: list[int], *, move_head_after_first: Path | None):
    """Publish the shared hood; optionally move primary HEAD after batch one."""

    def publish(_target, repo: Path, _agent: str, **_kwargs: object):
        on_publish.append(1)
        (repo / "README.md").write_text("# Published hood\n")
        (repo / "schema.json").write_text("{}\n")
        for directory in ("families", "sessions"):
            (repo / directory).mkdir(exist_ok=True)
            (repo / directory / ".gitkeep").write_text("")
        manifest = V2OwnerManifest(
            _OWNER,
            V2ProjectIdentity("proj", "Project"),
            ((_HOOD, V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(_OWNER)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        if move_head_after_first is not None and len(on_publish) == 1:
            _commit_primary(move_head_after_first, "primary moved between batches")
        return V2PublicationCounts(hoods_published=1)

    return publish


def _configure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    move_head: bool,
) -> tuple[ProjectTarget, list[frozenset[str]], list[int], list[object]]:
    target, _remote = configure_target(monkeypatch, tmp_path, _OWNER)
    _init_primary(target)
    builds: list[frozenset[str]] = []

    def counting_build(_target, _identity, **kwargs: object) -> ProjectHoodInventory:
        requested = kwargs["requested_hoods"]
        assert isinstance(requested, frozenset)
        builds.append(requested)
        return ProjectHoodInventory(_OWNER, "proj", ())

    monkeypatch.setattr(inventory_reuse, "build_project_hood_inventory", counting_build)
    publishes: list[int] = []
    monkeypatch.setattr(
        publication_locked,
        "publish_agent_hood",
        _publish_hood(
            publishes,
            move_head_after_first=target.primary_checkout if move_head else None,
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.publication_completion.publication_request_completion",
        fulfilled_completion,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.deferred.restore_deferred_prompt_archives",
        lambda *_args, **_kwargs: {},
    )
    timings: list[object] = []
    monkeypatch.setattr(publication_drain, "emit_drain_timing", timings.append)
    for index in range(_ROWS):
        enqueue_agent_publication(
            AgentPublicationOutboxItem(
                project_key="proj",
                project="Project",
                local_agent=_HOOD,
                global_agent=f"alice.athena.{_HOOD}",
                primary_revision=f"{index:040x}",
                local_hood=_HOOD,
            )
        )
    return target, builds, publishes, timings


def test_multi_batch_drain_builds_the_inventory_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, builds, publishes, timings = _configure(
        tmp_path, monkeypatch, move_head=False
    )

    result = job_drain.drain_project(
        target,
        deadline=time.monotonic() + 120,
        git_runner=run_git,
    )

    assert result.error is None
    assert result.hood_drained == _ROWS
    assert list_agent_publications("proj") == ()
    # Two 25-row-capped batches each ran a full drain transaction ...
    assert len(timings) == 2
    assert len(publishes) == 2
    # ... but shared one inventory, scoped to the pass's queued hoods.
    assert builds == [frozenset({_HOOD})]


def test_multi_batch_drain_rebuilds_when_primary_head_moves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, builds, publishes, timings = _configure(
        tmp_path, monkeypatch, move_head=True
    )

    result = job_drain.drain_project(
        target,
        deadline=time.monotonic() + 120,
        git_runner=run_git,
    )

    assert result.error is None
    assert result.hood_drained == _ROWS
    assert len(timings) == 2
    assert len(publishes) == 2
    # The second batch saw a new primary HEAD, so it could not reuse batch one.
    assert builds == [frozenset({_HOOD}), frozenset({_HOOD})]
