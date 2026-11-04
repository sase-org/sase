"""A deferred restore rebuilds the plan-named planner prompt archive.

The planner's outbox row names the pre-plan ``HEAD`` and its artifacts
directory, but not the archive inputs the inline publish used.  Approval records
those inputs beside the planner's artifacts so a restore after lock contention
lands the same ``prompts/<yyyymm>/<plan_name>.md`` with its PLAN link and the
plan-snapshot body, instead of the default agent-derived archive.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.models import ProjectTarget, TargetSelection
from sase.agents_sync.prompt_archive import publish as archive_publish
from sase.agents_sync.prompt_archive.deferred import prepare_deferred_prompt_archive
from sase.agents_sync.prompt_archive.inputs import (
    PROMPT_ARCHIVE_INPUTS_FILENAME,
    PROMPT_ARCHIVE_INPUTS_VERSION,
    PromptArchiveInputs,
    read_prompt_archive_inputs,
    write_prompt_archive_inputs,
)
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_LINKED,
    AgentPublicationOutboxItem,
    list_agent_publications,
)
from sase.agents_sync.v2_models import V2PublicationCounts
from sase.axe.run_agent_exec_plan_accept_sdd import publish_planner_prompt_archive
from sase.core.agent_identity_facade import AgentOwnerIdentity
from tests.agents_sync.commit_publication_fixtures import git, setup_target
from tests.agents_sync.git_sync_fixtures import plant_fulfilled_publication
from tests.agents_sync.test_deferred_prompt_archive._helpers import (
    HostedLinks,
    stub_full_sync,
)

_OWNER = AgentOwnerIdentity("alice", "athena")
_PLANNER_LOCAL = "worker"
_PLANNER_GLOBAL = "alice.athena.worker"
_PLAN_NAME = "restore_example"
_YYYYMM = "202610"
_PLAN_SNAPSHOT = "# Plan snapshot body\n\nShip the restore.\n"
_RAW_PROMPT = "Raw planner prompt that must not be archived.\n"


def _init_workspace(target: ProjectTarget) -> str:
    """Give the primary checkout a real HEAD the planner can record."""

    workspace = target.primary_checkout
    git(workspace, "init", "-q")
    git(workspace, "config", "user.name", "Tests")
    git(workspace, "config", "user.email", "tests@example.test")
    (workspace / "file.txt").write_text("landed by another agent\n", encoding="utf-8")
    git(workspace, "add", "file.txt")
    git(workspace, "commit", "-m", "another agent's landing commit")
    return git(workspace, "rev-parse", "HEAD").stdout.strip()


def _planner_artifacts(tmp_path: Path, target: ProjectTarget) -> Path:
    artifacts_dir = tmp_path / "runs" / "20261001120000"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)}),
        encoding="utf-8",
    )
    (artifacts_dir / "raw_prompt.md").write_text(_RAW_PROMPT, encoding="utf-8")
    return artifacts_dir


def _stub_planner_full_sync(
    monkeypatch: pytest.MonkeyPatch,
    target: ProjectTarget,
    artifacts_dir: Path,
) -> None:
    """Sync over a hood whose page proves only the page-only (linked) scope."""

    stub_full_sync(monkeypatch, target, artifacts_dir)

    def reconcile(_target: ProjectTarget, repo: Path, **_kwargs: object):
        for item in list_agent_publications(_target.project_key):
            plant_fulfilled_publication(
                repo,
                owner=_OWNER,
                local_agent=item.local_agent,
                global_agent=item.global_agent,
                revision=item.primary_revision,
                commit_shas=(),
                local_hood=item.local_hood,
                kind="session",
                has_prompt_file=True,
            )
        (repo / "README.md").write_text("# Agents\n", encoding="utf-8")
        (repo / "schema.json").write_text("{}\n", encoding="utf-8")
        for directory in ("users", "families", "sessions"):
            (repo / directory).mkdir(exist_ok=True)
            (repo / directory / ".gitkeep").write_text("", encoding="utf-8")
        return V2PublicationCounts(hoods_published=1)

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", reconcile)


@pytest.fixture
def deferred_planner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProjectTarget, Path, Path, str]:
    """Approve a plan whose inline archive publish loses the lock race."""

    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    target, remote = setup_target(tmp_path)
    head = _init_workspace(target)
    artifacts_dir = _planner_artifacts(tmp_path, target)
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

    real_lock = git_sync.bounded_agents_lock
    contended = [True]

    @contextmanager
    def busy_once(path: Path, timeout_seconds: float):
        """Contend only the planner's inline publish, not the sync after it."""

        if contended[0]:
            contended[0] = False
            yield False
            return
        with real_lock(path, timeout_seconds) as acquired:
            yield acquired

    monkeypatch.setattr(git_sync, "bounded_agents_lock", busy_once)
    path = publish_planner_prompt_archive(
        SimpleNamespace(
            workspace_dir=str(target.primary_checkout), project_name="Project"
        ),
        SimpleNamespace(current_artifacts_dir=str(artifacts_dir)),
        agent_name=f"{_PLANNER_LOCAL}--plan",
        prompt_content=_PLAN_SNAPSHOT,
        plan_name=_PLAN_NAME,
        yyyymm=_YYYYMM,
    )

    assert path is None
    [queued] = list_agent_publications(target.project_key)
    assert queued.logical_key == (_PLANNER_GLOBAL, head)
    assert queued.scope == PUBLICATION_SCOPE_LINKED
    assert queued.artifacts_dir == str(artifacts_dir.resolve())
    verify = tmp_path / "verify-deferred"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not (verify / "prompts").exists()
    return target, remote, artifacts_dir, head


def test_planner_publish_persists_archive_inputs(
    deferred_planner: tuple[ProjectTarget, Path, Path, str],
) -> None:
    _target, _remote, artifacts_dir, head = deferred_planner

    assert read_prompt_archive_inputs(artifacts_dir, primary_revision=head) == (
        PromptArchiveInputs(
            primary_revision=head,
            prompt_content=_PLAN_SNAPSHOT,
            plan_ref=f"plan:{_YYYYMM}/{_PLAN_NAME}.md",
            prompt_name=_PLAN_NAME,
            yyyymm=_YYYYMM,
        )
    )
    assert not list(artifacts_dir.glob(".prompt_archive_inputs*"))


def test_deferred_restore_rebuilds_the_plan_named_archive(
    deferred_planner: tuple[ProjectTarget, Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target, remote, artifacts_dir, _head = deferred_planner
    _stub_planner_full_sync(monkeypatch, target, artifacts_dir)

    [outcome] = git_sync.sync_agents(("proj",))

    assert outcome.error is None
    assert outcome.pushed
    verify = tmp_path / "verify-restored"
    git(tmp_path, "clone", str(remote), str(verify))
    archive = verify / "prompts" / _YYYYMM / f"{_PLAN_NAME}.md"
    assert archive.is_file()
    text = archive.read_text(encoding="utf-8")
    assert "Ship the restore." in text
    assert _RAW_PROMPT.strip() not in text
    assert f"https://example.test/plans/plan:{_YYYYMM}/{_PLAN_NAME}.md" in text
    assert not (verify / "prompts" / _YYYYMM / f"{_PLANNER_GLOBAL}.md").exists()
    # The planner's primary revision is not one of its commits, so only the
    # linked scope lets the restored row acknowledge.
    assert list_agent_publications("proj") == ()


def test_deferred_restore_without_a_record_keeps_the_default_archive(
    deferred_planner: tuple[ProjectTarget, Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target, remote, artifacts_dir, _head = deferred_planner
    (artifacts_dir / PROMPT_ARCHIVE_INPUTS_FILENAME).unlink()
    _stub_planner_full_sync(monkeypatch, target, artifacts_dir)

    [outcome] = git_sync.sync_agents(("proj",))

    assert outcome.error is None
    verify = tmp_path / "verify-default"
    git(tmp_path, "clone", str(remote), str(verify))
    assert not (verify / "prompts" / _YYYYMM / f"{_PLAN_NAME}.md").exists()
    default = verify / "prompts" / _YYYYMM / f"{_PLANNER_GLOBAL}.md"
    assert default.is_file()
    assert _RAW_PROMPT.strip() in default.read_text(encoding="utf-8")


def _capture_prepare(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_prepare(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(protection_status=None)

    monkeypatch.setattr(archive_publish, "prepare_prompt_archive", fake_prepare)
    return captured


def _restore_request(artifacts_dir: Path, revision: str) -> AgentPublicationOutboxItem:
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=_PLANNER_LOCAL,
        global_agent=_PLANNER_GLOBAL,
        primary_revision=revision,
        local_hood=_PLANNER_LOCAL,
        scope=PUBLICATION_SCOPE_LINKED,
        artifacts_dir=str(artifacts_dir),
    )


def test_deferred_restore_passes_recorded_inputs_to_the_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, _remote = setup_target(tmp_path)
    artifacts_dir = _planner_artifacts(tmp_path, target)
    revision = "a" * 40
    write_prompt_archive_inputs(
        artifacts_dir,
        PromptArchiveInputs(
            primary_revision=revision,
            prompt_content=_PLAN_SNAPSHOT,
            plan_ref=f"plan:{_YYYYMM}/{_PLAN_NAME}.md",
            prompt_name=_PLAN_NAME,
            yyyymm=_YYYYMM,
        ),
    )
    captured = _capture_prepare(monkeypatch)

    result = prepare_deferred_prompt_archive(
        target,
        _restore_request(artifacts_dir, revision),
        git_sync.run_git,
        prompt_runs={},
    )

    assert result.wrote
    assert captured["prompt_content"] == _PLAN_SNAPSHOT
    assert captured["plan_ref"] == f"plan:{_YYYYMM}/{_PLAN_NAME}.md"
    assert captured["prompt_name"] == _PLAN_NAME
    assert captured["yyyymm"] == _YYYYMM


def test_deferred_restore_ignores_inputs_recorded_for_another_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, _remote = setup_target(tmp_path)
    artifacts_dir = _planner_artifacts(tmp_path, target)
    write_prompt_archive_inputs(
        artifacts_dir,
        PromptArchiveInputs(
            primary_revision="a" * 40,
            prompt_content=_PLAN_SNAPSHOT,
            plan_ref=f"plan:{_YYYYMM}/{_PLAN_NAME}.md",
            prompt_name=_PLAN_NAME,
            yyyymm=_YYYYMM,
        ),
    )
    captured = _capture_prepare(monkeypatch)

    prepare_deferred_prompt_archive(
        target,
        _restore_request(artifacts_dir, "b" * 40),
        git_sync.run_git,
        prompt_runs={},
    )

    assert captured["prompt_content"] is None
    assert captured["plan_ref"] is None
    assert captured["prompt_name"] is None
    assert captured["yyyymm"] is None


def test_inputs_round_trip_and_replace_atomically(tmp_path: Path) -> None:
    inputs = PromptArchiveInputs(
        primary_revision="a" * 40,
        prompt_content="first\n",
        plan_ref="plan:202610/x.md",
        prompt_name="x",
        yyyymm="202610",
    )
    path = write_prompt_archive_inputs(tmp_path / "nested" / "artifacts", inputs)

    assert path.name == PROMPT_ARCHIVE_INPUTS_FILENAME
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == (
        PROMPT_ARCHIVE_INPUTS_VERSION
    )
    assert read_prompt_archive_inputs(path.parent, primary_revision="a" * 40) == inputs

    newer = PromptArchiveInputs(primary_revision="b" * 40, prompt_content="second\n")
    write_prompt_archive_inputs(path.parent, newer)
    assert read_prompt_archive_inputs(path.parent, primary_revision="a" * 40) is None
    assert read_prompt_archive_inputs(path.parent, primary_revision="b" * 40) == newer
    assert sorted(entry.name for entry in path.parent.iterdir()) == [
        PROMPT_ARCHIVE_INPUTS_FILENAME
    ]


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        json.dumps(
            {"version": 99, "primary_revision": "a" * 40, "prompt_content": "x"}
        ),
        json.dumps({"version": 1, "primary_revision": "a" * 40}),
        json.dumps({"version": 1, "primary_revision": "a" * 40, "prompt_content": 3}),
    ],
)
def test_unusable_inputs_read_as_absent(tmp_path: Path, content: str) -> None:
    (tmp_path / PROMPT_ARCHIVE_INPUTS_FILENAME).write_text(content, encoding="utf-8")

    assert read_prompt_archive_inputs(tmp_path, primary_revision="a" * 40) is None


def test_missing_inputs_read_as_absent(tmp_path: Path) -> None:
    assert read_prompt_archive_inputs(tmp_path, primary_revision="a" * 40) is None


def test_failed_inputs_write_does_not_stop_the_planner_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[str] = []

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    def fake_publish(*_args: object, **_kwargs: object):
        published.append("called")
        return archive_publish.PromptArchivePublicationOutcome(queued=True)

    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.inputs.write_prompt_archive_inputs",
        fail_write,
    )
    monkeypatch.setattr(
        "sase.agents_sync.prompt_archive.publish_prompt_archive", fake_publish
    )
    monkeypatch.setattr(
        "sase.agents_sync.git.run_git",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=f"{'a' * 40}\n", stderr=""
        ),
    )

    publish_planner_prompt_archive(
        SimpleNamespace(workspace_dir=str(tmp_path), project_name="Project"),
        SimpleNamespace(current_artifacts_dir=str(tmp_path / "artifacts")),
        agent_name=f"{_PLANNER_LOCAL}--plan",
        prompt_content=_PLAN_SNAPSHOT,
        plan_name=_PLAN_NAME,
        yyyymm=_YYYYMM,
    )

    assert published == ["called"]
