"""Monitor-turn prompt sources resolve through their starter artifacts."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest

from sase.agents_sync.git import run_git
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.deferred import (
    DeferredPromptRestoreFailure,
    classify_quarantined_prompt_archives,
    restore_deferred_prompt_archives,
)
from sase.agents_sync.prompt_archive.source import prompt_source_dirs
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    enqueue_agent_publication,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts
from tests.agents_sync.commit_publication_fixtures import setup_target
from tests.agents_sync.test_deferred_prompt_archive._helpers import OWNER

_REVISION = "a" * 40
_NOW = 2_000_000_000.0


def _request(artifacts_dir: Path, **overrides: object) -> AgentPublicationOutboxItem:
    values: dict[str, object] = {
        "project_key": "proj",
        "project": "Project",
        "local_agent": "worker",
        "global_agent": "alice.athena.worker",
        "primary_revision": _REVISION,
        "local_hood": "worker",
        "artifacts_dir": str(artifacts_dir),
        "created_at": 0.0,
    }
    values.update(overrides)
    return AgentPublicationOutboxItem(**values)  # type: ignore[arg-type]


def _monitor_and_starter(
    tmp_path: Path,
    target: ProjectTarget,
    *,
    prompt: str | None,
    starter_name: str = "20260801120000",
) -> tuple[Path, Path]:
    monitor_dir = tmp_path / "runs/20260801130000"
    starter_dir = tmp_path / "runs" / starter_name
    monitor_dir.mkdir(parents=True)
    starter_dir.mkdir(parents=True, exist_ok=True)
    (monitor_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "workspace_dir": str(target.primary_checkout),
                "monitor_starter_artifacts_dir": str(starter_dir),
            }
        ),
        encoding="utf-8",
    )
    (starter_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(target.primary_checkout)}),
        encoding="utf-8",
    )
    if prompt is not None:
        (starter_dir / "raw_prompt.md").write_text(prompt, encoding="utf-8")
    return monitor_dir, starter_dir


def _restore(
    target: ProjectTarget,
    request: AgentPublicationOutboxItem,
    *,
    now: float = _NOW,
) -> dict[tuple[str, str], DeferredPromptRestoreFailure]:
    return restore_deferred_prompt_archives(
        target,
        (request,),
        run_git,
        identity=AgentIdentitySnapshot(OWNER),
        inventory=ProjectHoodInventory(OWNER, "proj", ()),
        now=now,
    )


def test_monitor_row_restores_prompt_from_starter(
    tmp_path: Path,
) -> None:
    target, _remote = setup_target(tmp_path)
    monitor_dir, starter_dir = _monitor_and_starter(
        tmp_path, target, prompt="Starter prompt content.\n"
    )

    failures = _restore(target, _request(monitor_dir))

    assert failures == {}
    archived = target.sidecar_path / "prompts/202608/alice.athena.worker.md"
    assert "Starter prompt content." in archived.read_text(encoding="utf-8")
    assert (starter_dir / "raw_prompt.md").is_file()


def test_missing_monitor_starter_stays_pending_then_reports_both_probes(
    tmp_path: Path,
) -> None:
    target, _remote = setup_target(tmp_path)
    monitor_dir, starter_dir = _monitor_and_starter(
        tmp_path, target, prompt=None, starter_name="missing-starter"
    )
    shutil.rmtree(starter_dir)
    request = _request(
        monitor_dir,
        created_at=_NOW - 60,
        quarantined=True,
    )

    pending = _restore(target, request)
    pending_failure = pending[request.logical_key]
    assert pending_failure.pending is True
    assert pending_failure.terminal is False

    terminal = _restore(target, replace(request, created_at=0.0))
    terminal_failure = terminal[request.logical_key]
    assert terminal_failure.terminal is True
    assert str(monitor_dir.resolve()) in terminal_failure.message
    assert str(starter_dir.resolve()) in terminal_failure.message


def test_quarantine_classifier_sees_monitor_starter_prompt(
    tmp_path: Path,
) -> None:
    target, _remote = setup_target(tmp_path)
    monitor_dir, _starter_dir = _monitor_and_starter(
        tmp_path, target, prompt="Still available.\n"
    )
    request = _request(monitor_dir, quarantined=True)

    terminal = classify_quarantined_prompt_archives(
        target,
        (request,),
        identity=AgentIdentitySnapshot(OWNER),
        load_inventory=lambda: (_ for _ in ()).throw(
            AssertionError("starter prompt should avoid inventory loading")
        ),
        now=_NOW,
    )

    assert terminal == {}


def test_prompt_source_dirs_are_cycle_safe_bounded_and_tolerate_bad_meta(
    tmp_path: Path,
) -> None:
    chain = [tmp_path / f"chain-{index}" for index in range(5)]
    for index, directory in enumerate(chain):
        directory.mkdir()
        if index < len(chain) - 1:
            (directory / "agent_meta.json").write_text(
                json.dumps({"monitor_starter_artifacts_dir": str(chain[index + 1])}),
                encoding="utf-8",
            )

    assert prompt_source_dirs(chain[0]) == tuple(path.resolve() for path in chain[:4])

    first, second = tmp_path / "cycle-first", tmp_path / "cycle-second"
    first.mkdir()
    second.mkdir()
    (first / "agent_meta.json").write_text(
        json.dumps({"monitor_starter_artifacts_dir": str(second)}),
        encoding="utf-8",
    )
    (second / "agent_meta.json").write_text(
        json.dumps({"monitor_starter_artifacts_dir": str(first)}),
        encoding="utf-8",
    )
    assert prompt_source_dirs(first) == (first.resolve(), second.resolve())

    unreadable = tmp_path / "unreadable-meta"
    unreadable.mkdir()
    (unreadable / "agent_meta.json").write_text("{invalid", encoding="utf-8")
    assert prompt_source_dirs(unreadable) == (unreadable.resolve(),)


def test_active_row_pins_dismissed_starter_until_prompt_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    target, _remote = setup_target(tmp_path)
    monitor_dir, starter_dir = _monitor_and_starter(
        tmp_path, target, prompt="Survives dismissal.\n"
    )
    request = _request(monitor_dir)
    enqueue_agent_publication(request)

    assert delete_agent_artifacts(str(starter_dir)) is False
    assert (starter_dir / "raw_prompt.md").is_file()
    assert _restore(target, request) == {}
    archived = target.sidecar_path / "prompts/202608/alice.athena.worker.md"
    assert "Survives dismissal." in archived.read_text(encoding="utf-8")
