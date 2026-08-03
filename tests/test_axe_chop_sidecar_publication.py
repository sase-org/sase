"""Asynchronous sidecar publication chop tests."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    AgentPublicationOutboxItem,
    PublicationKind,
    acknowledge_agent_publications,
    list_agent_publications,
)
from sase.axe.chop_script_context import ChopScriptContext
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger
import sase.scripts.sase_chop_sidecar_publication as publication


def _runtime(tmp_path: Path) -> BuiltinChopRuntime:
    return BuiltinChopRuntime(
        name="sidecar_publication",
        context=ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="publications",
            state_dir=str(tmp_path / "state"),
            all_changespecs_file=str(tmp_path / "all.json"),
            filtered_changespecs_file=str(tmp_path / "filtered.json"),
        ),
        log=ChopLogger(stdout=StringIO(), stderr=StringIO()),
    )


def _request(
    project_key: str,
    kind: PublicationKind,
    *,
    attempts: int = 0,
) -> AgentPublicationOutboxItem:
    common = {
        "project_key": project_key,
        "project": project_key.title(),
        "kind": kind,
        "attempts": attempts,
        "created_at": float(
            {"agent_hood": 1, "bead_pages": 2, "plan_header": 3, "sidecar_push": 4}[
                kind
            ]
        ),
        "updated_at": 1.0,
    }
    if kind == "agent_hood":
        return AgentPublicationOutboxItem(
            **common,
            local_agent="worker",
            global_agent=f"alice.athena.{project_key}.worker",
            primary_revision="a" * 40,
            local_hood="worker",
        )
    if kind == "bead_pages":
        return AgentPublicationOutboxItem(
            **common,
            bead_id=f"{project_key}-1.2",
            lineage_root=f"{project_key}-1",
            primary_revision="a" * 40,
        )
    if kind == "plan_header":
        return AgentPublicationOutboxItem(
            **common,
            plan_ref=f"plans:202608/{project_key}.md",
            primary_revision="a" * 40,
            commit_message=f"work\n\nSASE_PLAN: plans:202608/{project_key}.md",
        )
    return AgentPublicationOutboxItem(
        **common,
        sidecar_kind="beads",
    )


def _write_queue(
    projects_root: Path,
    project_key: str,
    requests: list[AgentPublicationOutboxItem],
) -> None:
    project_dir = projects_root / project_key
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / publication.AGENT_PUBLICATION_OUTBOX_FILENAME
    path.write_text(
        json.dumps(
            {
                "schema_version": PUBLICATION_OUTBOX_SCHEMA_VERSION,
                "items": [request.to_json_dict() for request in requests],
            }
        ),
        encoding="utf-8",
    )


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    monkeypatch.setattr(publication, "sase_projects_dir", lambda: projects_root)
    monkeypatch.setattr(
        "sase.agents_sync.publication_outbox_store.sase_projects_dir",
        lambda: projects_root,
    )
    monkeypatch.setattr(
        publication,
        "_resolve_project_target",
        lambda project_key: ProjectTarget(
            project_key=project_key,
            project=project_key.title(),
            primary_checkout=tmp_path / project_key,
            primary_roots=(tmp_path / project_key,),
            sidecar_path=tmp_path / f"{project_key}-agents",
            remote_url="git@example.invalid:agents.git",
        ),
    )
    return projects_root


def test_empty_queue_is_a_stable_no_op(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, tmp_path)

    result = publication._run(_runtime(tmp_path))

    assert result.status == "no_op"
    assert result.reason == "no_pending_requests"
    assert result.counters == {
        "projects_pending": 0,
        "agents_published": 0,
        "bead_pages_published": 0,
        "plan_headers_refreshed": 0,
        "pushes_completed": 0,
        "requests_failed": 0,
        "requests_quarantined": 0,
        "projects_backed_off": 0,
        "projects_deferred": 0,
    }


def test_one_project_drains_every_kind_in_rank_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = _configure(monkeypatch, tmp_path)
    requests = [
        _request("proj", kind)
        for kind in ("sidecar_push", "plan_header", "bead_pages", "agent_hood")
    ]
    _write_queue(projects_root, "proj", requests)
    calls: list[str] = []

    def drain_agents(project_key: str, **_kwargs: object) -> SimpleNamespace:
        calls.append("agent_hood")
        acknowledge_agent_publications(
            project_key,
            (requests[-1].logical_key,),
        )
        return SimpleNamespace(drained=1, error=None, skip_reason=None)

    def drain_other(
        request: AgentPublicationOutboxItem,
        _target: ProjectTarget,
        **_kwargs: object,
    ) -> None:
        calls.append(request.kind)

    monkeypatch.setattr(publication, "drain_agent_publications", drain_agents)
    monkeypatch.setattr(publication, "_drain_non_agent_request", drain_other)

    result = publication._run(_runtime(tmp_path))

    assert calls == ["agent_hood", "bead_pages", "plan_header", "sidecar_push"]
    assert list_agent_publications("proj") == ()
    assert result.status == "ok"
    assert result.counters["agents_published"] == 1
    assert result.counters["bead_pages_published"] == 1
    assert result.counters["plan_headers_refreshed"] == 1
    assert result.counters["pushes_completed"] == 1


def test_contended_agent_lock_is_declined_and_backed_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = _configure(monkeypatch, tmp_path)
    request = _request("proj", "agent_hood")
    _write_queue(projects_root, "proj", [request])
    timeouts: list[float] = []

    def busy(_project_key: str, *, lock_timeout_seconds: float) -> SimpleNamespace:
        timeouts.append(lock_timeout_seconds)
        return SimpleNamespace(
            drained=0,
            error="agents sync lock is busy",
            skip_reason=None,
        )

    monkeypatch.setattr(publication, "drain_agent_publications", busy)

    result = publication._run(_runtime(tmp_path))

    assert timeouts == [publication._project_lock_timeout(1)]
    assert result.reason == "publication_failed"
    [pending] = list_agent_publications("proj")
    assert pending.attempts == 1
    state_path = (
        Path(_runtime(tmp_path).context.state_dir) / publication._BACKOFF_STATE_FILENAME
    )
    assert json.loads(state_path.read_text(encoding="utf-8"))["proj"]["failures"] == 1


def test_failing_request_quarantines_at_configured_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS", "2")
    request = _request("proj", "bead_pages", attempts=1)
    _write_queue(projects_root, "proj", [request])

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("beads store write lock is busy")

    monkeypatch.setattr(publication, "_drain_non_agent_request", fail)

    result = publication._run(_runtime(tmp_path))

    [pending] = list_agent_publications("proj")
    assert pending.attempts == 2
    assert pending.quarantined
    assert result.counters["requests_failed"] == 1
    assert result.counters["requests_quarantined"] == 1


def test_exhausted_work_budget_defers_later_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = _configure(monkeypatch, tmp_path)
    for project_key in ("one", "two"):
        _write_queue(projects_root, project_key, [_request(project_key, "bead_pages")])
    clock = iter([0.0, 0.0, publication._WORK_BUDGET_SECONDS + 1.0])
    monkeypatch.setattr(
        publication,
        "time",
        SimpleNamespace(monotonic=lambda: next(clock)),
    )
    drained: list[str] = []
    monkeypatch.setattr(
        publication,
        "_drain_non_agent_request",
        lambda request, *_args, **_kwargs: drained.append(request.project_key),
    )

    result = publication._run(_runtime(tmp_path))

    assert drained == ["one"]
    assert result.counters["bead_pages_published"] == 1
    assert result.counters["projects_deferred"] == 1
    assert [item.project_key for item in list_agent_publications("two")] == ["two"]


def test_backoff_survives_a_kill_during_project_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects_root = _configure(monkeypatch, tmp_path)
    _write_queue(projects_root, "proj", [_request("proj", "bead_pages")])
    now = datetime(2026, 8, 3, 12, tzinfo=UTC)
    monkeypatch.setattr(publication, "_utc_now", lambda: now)

    def killed(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(publication, "_drain_non_agent_request", killed)
    runtime = _runtime(tmp_path)

    with pytest.raises(KeyboardInterrupt):
        publication._run(runtime)

    state_path = Path(runtime.context.state_dir) / publication._BACKOFF_STATE_FILENAME
    assert json.loads(state_path.read_text(encoding="utf-8"))["proj"]["failures"] == 1

    monkeypatch.setattr(
        publication,
        "_drain_non_agent_request",
        lambda *_args, **_kwargs: pytest.fail("backed-off project was attempted"),
    )
    backed_off = publication._run(runtime)

    assert backed_off.reason == "all_backed_off"
    assert backed_off.counters["projects_backed_off"] == 1
