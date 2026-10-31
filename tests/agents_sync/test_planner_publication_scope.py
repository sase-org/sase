"""Planner prompt-archive rows enqueue linked scope and drain on the page gate."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from sase.agents_sync import (
    _commit_publication_locked as publication_locked,
    _commit_publication_support as publication_support,
)
from sase.agents_sync.git import run_git
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.agents_sync.prompt_archive import publish as archive_publish
from sase.agents_sync.prompt_archive.publish import (
    PromptArchivePublicationOutcome,
    publish_prompt_archive,
)
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_LINKED,
    PUBLICATION_SCOPE_REVISION,
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
from sase.axe.run_agent_exec_plan_accept_sdd import publish_planner_prompt_archive
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.sdd.plan_header_block import (
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    render_plan_header_block,
)
from tests.agents_sync._prompt_archive_helpers import HostedLinks
from tests.agents_sync.commit_publication_fixtures import setup_target
from tests.agents_sync.git_sync_fixtures import plant_fulfilled_publication

_OWNER = AgentOwnerIdentity("alice", "athena")
_PLANNER_LOCAL = "foo.bar"
_PLANNER_GLOBAL = "alice.athena.foo.bar"
_PLANNER_HOOD = "foo"
_PLANNER_HEAD = "a" * 40
_CODER_SHA = "b" * 40


def _artifacts_dir(tmp_path: Path, target: ProjectTarget) -> Path:
    artifacts_dir = tmp_path / "runs/20261001120000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)})
    )
    (artifacts_dir / "raw_prompt.md").write_text("Archive this planner prompt.\n")
    return artifacts_dir


def _stub_prompt_publish(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: ProjectTarget
) -> Path:
    artifacts_dir = _artifacts_dir(tmp_path, target)
    monkeypatch.setattr(
        archive_publish,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(archive_publish, "require_agent_owner_identity", lambda: _OWNER)
    monkeypatch.setattr(
        archive_publish, "_hosted_resolver", lambda *_args: HostedLinks()
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)
    return artifacts_dir


def _plant_planner_archive(sidecar: Path, global_agent: str) -> None:
    month = sidecar / "prompts" / "202610"
    month.mkdir(parents=True, exist_ok=True)
    header = render_plan_header_block(
        (
            PlanHeaderSection(
                kind=PlanHeaderSectionKind.AGENTS,
                entries=(PlanHeaderEntry(label=global_agent),),
            ),
        )
    )
    (month / f"{global_agent}.md").write_text(
        f"{header}\n\n# Prompt\narchived planner prompt\n",
        encoding="utf-8",
    )


def _enqueue_planner(
    *,
    scope: str,
    revision: str = _PLANNER_HEAD,
    artifacts_dir: Path | str | None = None,
) -> AgentPublicationOutboxItem:
    return enqueue_agent_publication(
        AgentPublicationOutboxItem(
            project_key="proj",
            project="Project",
            local_agent=_PLANNER_LOCAL,
            global_agent=_PLANNER_GLOBAL,
            primary_revision=revision,
            local_hood=_PLANNER_HOOD,
            scope=scope,
            artifacts_dir=None if artifacts_dir is None else str(artifacts_dir),
        )
    )


def _drain_with_planted_hood(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    commit_shas: tuple[str, ...],
    plant_archive: bool = True,
    has_prompt_file: bool = True,
    plant_page: bool = True,
) -> ProjectTarget:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    monkeypatch.setattr(
        publication_support,
        "resolve_sync_targets",
        lambda _projects: TargetSelection((target,), ()),
    )
    monkeypatch.setattr(
        publication_support, "require_agent_owner_identity", lambda: _OWNER
    )

    def publish(_target, repo, _agent, **_kwargs):
        if plant_page:
            plant_fulfilled_publication(
                repo,
                owner=_OWNER,
                local_agent=_PLANNER_LOCAL,
                global_agent=_PLANNER_GLOBAL,
                revision=_PLANNER_HEAD,
                commit_shas=commit_shas,
                local_hood=_PLANNER_HOOD,
                kind="session",
                has_prompt_file=has_prompt_file,
            )
        if plant_archive:
            _plant_planner_archive(repo, _PLANNER_GLOBAL)
        manifest = V2OwnerManifest(
            _OWNER,
            V2ProjectIdentity("proj", "Project"),
            ((_PLANNER_HOOD, V2OwnerHoodEntry("d" * 64, ("README.md",), 1, 1)),),
        )
        path = repo / owner_manifest_path(_OWNER)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(v2_json_bytes(manifest.to_json_dict()))
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(publication_locked, "publish_agent_hood", publish)
    return target


def test_publish_planner_prompt_archive_passes_linked_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_publish(
        *_args: object, **kwargs: object
    ) -> PromptArchivePublicationOutcome:
        captured.update(kwargs)
        return PromptArchivePublicationOutcome(
            queued=True, published=True, prompt_path=tmp_path / "prompt.md"
        )

    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive",
        fake_publish,
    )
    monkeypatch.setattr(
        "sase.agents_sync.git.run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["rev-parse", "HEAD"], 0, f"{_PLANNER_HEAD}\n", ""
        ),
    )

    path = publish_planner_prompt_archive(
        SimpleNamespace(workspace_dir=str(tmp_path), project_name="Project"),
        SimpleNamespace(current_artifacts_dir=str(tmp_path / "artifacts")),
        agent_name="foo.bar--plan",
        prompt_content="# Plan\n",
        plan_name="example",
        yyyymm="202610",
    )

    assert path == tmp_path / "prompt.md"
    assert captured["fulfillment_scope"] == PUBLICATION_SCOPE_LINKED
    assert captured["plan_ref"] == "plan:202610/example.md"
    assert captured["prompt_name"] == "example"


def test_publish_prompt_archive_planner_scope_enqueues_linked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    artifacts_dir = _stub_prompt_publish(monkeypatch, tmp_path, target)

    outcome = publish_prompt_archive(
        "foo.bar--plan",
        _PLANNER_HEAD,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
        fulfillment_scope=PUBLICATION_SCOPE_LINKED,
    )

    assert outcome.queued
    [request] = list_agent_publications("proj")
    assert request.scope == PUBLICATION_SCOPE_LINKED
    assert request.primary_revision == _PLANNER_HEAD


def test_publish_prompt_archive_commit_path_enqueues_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, _remote = setup_target(tmp_path)
    artifacts_dir = _stub_prompt_publish(monkeypatch, tmp_path, target)

    outcome = publish_prompt_archive(
        "worker",
        _PLANNER_HEAD,
        project="Project",
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
    )

    assert outcome.queued
    [request] = list_agent_publications("proj")
    assert request.scope == PUBLICATION_SCOPE_REVISION


def test_publish_prompt_archive_rejects_unknown_fulfillment_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    outcome = publish_prompt_archive(
        "worker",
        _PLANNER_HEAD,
        commit_cwd=tmp_path,
        fulfillment_scope="prompt",
    )
    assert not outcome.queued
    assert outcome.error is not None
    assert "linked" in outcome.error
    assert "revision" in outcome.error


def test_epic_planner_drain_acknowledges_on_first_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _drain_with_planted_hood(monkeypatch, tmp_path, commit_shas=())
    request = _enqueue_planner(scope=PUBLICATION_SCOPE_LINKED)
    result = publication_locked.publish_queued_locked(target, _OWNER, run_git)

    assert result.drained == 1
    assert request.logical_key not in {
        item.logical_key for item in list_agent_publications("proj")
    }
    assert list_agent_publications("proj") == ()


def test_tale_planner_drain_acknowledges_after_descendant_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _drain_with_planted_hood(monkeypatch, tmp_path, commit_shas=(_CODER_SHA,))
    _enqueue_planner(scope=PUBLICATION_SCOPE_LINKED)
    result = publication_locked.publish_queued_locked(target, _OWNER, run_git)

    assert result.drained == 1
    assert list_agent_publications("proj") == ()


def test_revision_commit_row_with_wrong_sha_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _drain_with_planted_hood(monkeypatch, tmp_path, commit_shas=(_CODER_SHA,))
    request = _enqueue_planner(scope=PUBLICATION_SCOPE_REVISION)
    result = publication_locked.publish_queued_locked(target, _OWNER, run_git)

    remaining = list_agent_publications("proj")
    assert result.drained == 0
    assert len(remaining) == 1
    assert remaining[0].logical_key == request.logical_key
    assert remaining[0].attempts == 1
    assert remaining[0].last_error is not None
    assert "did not materialize" not in remaining[0].last_error
    assert "not acknowledged:" in remaining[0].last_error
    assert "without the requested primary revision" in remaining[0].last_error


def test_repeated_deterministic_refusal_retires_after_confirming_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _drain_with_planted_hood(monkeypatch, tmp_path, commit_shas=(_CODER_SHA,))
    request = _enqueue_planner(scope=PUBLICATION_SCOPE_REVISION)

    first = publication_locked.publish_queued_locked(target, _OWNER, run_git)
    assert first.drained == 0
    [after_first] = list_agent_publications("proj")
    assert after_first.attempts == 1
    assert not after_first.terminal
    first_error = after_first.last_error
    assert first_error is not None
    assert "not acknowledged:" in first_error

    second = publication_locked.publish_queued_locked(target, _OWNER, run_git)
    assert second.drained == 0
    [after_second] = list_agent_publications("proj")
    assert after_second.logical_key == request.logical_key
    assert after_second.attempts == 2
    assert after_second.terminal
    assert after_second.terminal_reason == after_second.last_error
    assert after_second.last_error == first_error
    assert not after_second.quarantined


def test_missing_session_page_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _drain_with_planted_hood(
        monkeypatch,
        tmp_path,
        commit_shas=(),
        plant_page=False,
        plant_archive=True,
    )
    _enqueue_planner(scope=PUBLICATION_SCOPE_LINKED)
    result = publication_locked.publish_queued_locked(target, _OWNER, run_git)

    remaining = list_agent_publications("proj")
    assert result.drained == 0
    assert len(remaining) == 1
    assert remaining[0].attempts == 1
    assert remaining[0].last_error is not None
    assert "did not materialize" not in remaining[0].last_error
    assert "not acknowledged:" in remaining[0].last_error


def test_missing_prompt_bytes_are_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _drain_with_planted_hood(
        monkeypatch,
        tmp_path,
        commit_shas=(),
        plant_archive=False,
        has_prompt_file=True,
    )
    empty = tmp_path / "empty-artifacts"
    empty.mkdir()
    _enqueue_planner(scope=PUBLICATION_SCOPE_LINKED, artifacts_dir=empty)
    result = publication_locked.publish_queued_locked(target, _OWNER, run_git)

    remaining = list_agent_publications("proj")
    assert result.drained == 0
    assert len(remaining) == 1
    assert remaining[0].attempts == 1
    assert remaining[0].last_error is not None
    assert "did not materialize" not in remaining[0].last_error


def test_protection_failure_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.prompt_archive.protection import PROMPT_PROTECTION_BLOCKED
    from tests.agents_sync.test_prompt_archive_protection import (
        MARKER,
        _install_marker_scanner,
    )

    target = _drain_with_planted_hood(
        monkeypatch, tmp_path, commit_shas=(), plant_archive=False
    )
    artifacts_dir = tmp_path / "secret-artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_prompt.md").write_text(
        f"planner {MARKER.decode()}\n", encoding="utf-8"
    )
    _install_marker_scanner(monkeypatch)
    monkeypatch.setattr(
        archive_publish, "_hosted_resolver", lambda *_args: HostedLinks()
    )
    monkeypatch.setattr("sase.file_references.format_with_prettier", lambda text: text)
    _enqueue_planner(scope=PUBLICATION_SCOPE_LINKED, artifacts_dir=artifacts_dir)
    result = publication_locked.publish_queued_locked(target, _OWNER, run_git)

    remaining = list_agent_publications("proj")
    assert result.drained == 0
    assert len(remaining) == 1
    assert remaining[0].attempts == 0
    assert remaining[0].last_error == PROMPT_PROTECTION_BLOCKED
    assert remaining[0].last_error is not None
    assert "did not materialize" not in remaining[0].last_error
