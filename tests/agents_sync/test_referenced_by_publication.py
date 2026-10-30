"""The agents-sync Referenced By drain routes through the machine store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sase.agents_sync.referenced_by_publication as referenced_by_publication
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.referenced_by_outbox import ReferencedByOutboxItem
from sase.agents_sync.referenced_by_publication import (
    _resolve_store,
    drain_referenced_by_requests,
)
from sase.sdd._referenced_by_refresh_models import ReferencedByRefreshReport


def _unused_git_runner(
    cwd: Path, args: list[str], *, network: bool = False, op: str = ""
) -> Any:
    raise AssertionError("git_runner is unused by drain_referenced_by_requests")


def _target(tmp_path: Path) -> ProjectTarget:
    primary = tmp_path / "primary"
    primary.mkdir(exist_ok=True)
    return ProjectTarget(
        project_key="proj",
        project="Project",
        primary_checkout=primary,
        primary_roots=(primary,),
        sidecar_path=primary / "sase" / "repos" / "agents",
        remote_url="https://example.test/proj--agents.git",
    )


def _item(*, sidecar_role: str = "plans") -> ReferencedByOutboxItem:
    return ReferencedByOutboxItem(
        project_key="proj",
        project="Project",
        global_agent="alice.athena.worker",
        agent_url="https://example.test/agents/worker",
        primary_revision="a" * 40,
        sidecar_role=sidecar_role,
        provider="plan",
        artifact_id="plan:202608/example.md",
        repo_relpath="202608/example.md",
        identity_value=None,
        canonical_ref="plan:202608/example.md",
        destination="https://example.test/prompts/1",
        uses=1,
        published_date="2026-08-12",
    )


class TestResolveStoreUsesTheMachineResolver:
    def test_resolve_store_forwards_project_key_and_primary_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = _target(tmp_path)
        calls: list[tuple[str, Path]] = []
        fake_sdd_store = object()

        def _fake_resolve(project_key: str, primary_checkout: Path) -> Any:
            calls.append((project_key, primary_checkout))
            return type("Link", (), {"sdd_store": fake_sdd_store})()

        monkeypatch.setattr(
            "sase.sdd.artifact_link_store.resolve_machine_artifact_link_store",
            _fake_resolve,
        )

        store = _resolve_store(target)

        assert calls == [("proj", target.primary_checkout)]
        assert store is fake_sdd_store


class TestDrainRoutesRequestsThroughTheMachineStore:
    def test_drain_refreshes_with_the_resolved_machine_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = _target(tmp_path)
        item = _item()
        monkeypatch.setattr(
            referenced_by_publication,
            "list_referenced_by_requests",
            lambda project_key, include_quarantined=False: (item,),
        )
        fake_sdd_store = object()
        resolve_calls: list[tuple[str, Path]] = []

        def _fake_resolve_store(target: ProjectTarget) -> Any:
            resolve_calls.append((target.project_key, target.primary_checkout))
            return fake_sdd_store

        monkeypatch.setattr(
            referenced_by_publication, "_resolve_store", _fake_resolve_store
        )
        refresh_calls: list[Any] = []

        def _fake_refresh(
            store: Any, *, role: str, requests: tuple[Any, ...], write: bool
        ) -> ReferencedByRefreshReport:
            refresh_calls.append(store)
            return ReferencedByRefreshReport(
                root=tmp_path,
                role=role,
                write=write,
                scanned=0,
                actions=(),
                issues=(),
                changed_files=(),
                committed=False,
            )

        monkeypatch.setattr(
            referenced_by_publication, "refresh_referenced_by", _fake_refresh
        )
        acknowledged: list[str] = []
        monkeypatch.setattr(
            referenced_by_publication,
            "acknowledge_referenced_by_requests",
            lambda project_key, keys: acknowledged.extend(keys),
        )
        monkeypatch.setattr(
            referenced_by_publication,
            "legacy_referenced_by_writes_fenced",
            lambda _target: False,
        )

        diagnostics = drain_referenced_by_requests(
            target, git_runner=_unused_git_runner
        )

        assert diagnostics == ()
        assert resolve_calls == [("proj", target.primary_checkout)]
        assert refresh_calls == [fake_sdd_store]
        assert acknowledged == [item.logical_key]

    def test_fenced_drain_skips_store_resolve_lock_and_refresh(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = _target(tmp_path)
        convert_calls: list[str] = []
        monkeypatch.setattr(
            referenced_by_publication,
            "legacy_referenced_by_writes_fenced",
            lambda _target: True,
        )
        monkeypatch.setattr(
            referenced_by_publication,
            "convert_fenced_referenced_by_backlog",
            lambda drained: convert_calls.append(drained.project_key) or (),
        )
        monkeypatch.setattr(
            referenced_by_publication,
            "_resolve_store",
            lambda _target: (_ for _ in ()).throw(
                AssertionError("fenced drain must not resolve the machine store")
            ),
        )
        monkeypatch.setattr(
            referenced_by_publication,
            "refresh_referenced_by",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("fenced drain must not refresh")
            ),
        )

        diagnostics = drain_referenced_by_requests(
            target, git_runner=_unused_git_runner
        )

        assert diagnostics == ()
        assert convert_calls == ["proj"]

    def test_refresh_exception_charges_attempts_and_quarantines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.agents_sync.referenced_by_outbox import (
            enqueue_referenced_by_request,
            list_referenced_by_requests,
        )

        monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
        monkeypatch.setenv("SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS", "2")
        target = _target(tmp_path)
        item = enqueue_referenced_by_request(_item())
        monkeypatch.setattr(
            referenced_by_publication,
            "legacy_referenced_by_writes_fenced",
            lambda _target: False,
        )
        monkeypatch.setattr(
            referenced_by_publication,
            "_resolve_store",
            lambda _target: object(),
        )

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError(
                "artifact-link legacy index writes are fenced; use link events"
            )

        monkeypatch.setattr(referenced_by_publication, "refresh_referenced_by", _raise)

        first = drain_referenced_by_requests(target, git_runner=_unused_git_runner)
        second = drain_referenced_by_requests(target, git_runner=_unused_git_runner)

        assert first and "legacy index writes are fenced" in first[0]
        assert second and "legacy index writes are fenced" in second[0]
        active = list_referenced_by_requests(
            item.project_key, include_quarantined=False
        )
        queued = list_referenced_by_requests(item.project_key, include_quarantined=True)
        assert active == ()
        assert len(queued) == 1
        assert queued[0].attempts == 2
        assert queued[0].quarantined is True
