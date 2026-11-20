"""The automatic publication pass retires quarantined unrecoverable prompt rows."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync import publication_job
from sase.agents_sync.inventory_models import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive import quarantine_sweep
from sase.agents_sync.prompt_archive.deferred import (
    DEFERRED_PROMPT_RESTORE_ERROR_PREFIX,
    UNRESOLVED_PROMPT_ARCHIVE_REASON,
)
from sase.agents_sync.prompt_archive.terminal import (
    is_terminal_prompt_archive_reason,
    terminal_obligations_path,
)
from sase.agents_sync.publication_outbox import (
    AgentPublicationOutboxItem,
    list_agent_publications,
    revive_agent_publications,
)
from sase.agents_sync.publication_outbox_store import mutate_publication_outbox
from tests._conftest_environment import redirect_sase_home
from tests.agents_sync._publication_job_helpers import configure_single_project_job
from tests.agents_sync.commit_publication_fixtures import git, setup_target
from tests.agents_sync.test_deferred_prompt_archive._helpers import OWNER

# Old enough to be past the deferred-prompt grace window on any clock.
_CREATED_AT = 1_000_000_000.0
_ATTEMPTS = 3


def _revision(index: int) -> str:
    return f"{index:040x}"


def _missing_source_error(global_agent: str, revision: str) -> str:
    return (
        f"{DEFERRED_PROMPT_RESTORE_ERROR_PREFIX}{global_agent}@{revision[:12]}: "
        f"{UNRESOLVED_PROMPT_ARCHIVE_REASON}"
    )


def _quarantined_row(
    tmp_path: Path,
    index: int,
    *,
    last_error: str | None = None,
) -> AgentPublicationOutboxItem:
    """A row that quarantined before the terminal state existed."""

    agent = f"worker{index}"
    global_agent = f"alice.athena.{agent}"
    revision = _revision(index)
    artifacts_dir = tmp_path / "runs" / agent
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return AgentPublicationOutboxItem(
        project_key="proj",
        project="Project",
        local_agent=agent,
        global_agent=global_agent,
        primary_revision=revision,
        local_hood=agent,
        artifacts_dir=str(artifacts_dir),
        run_id=f"run-{index}",
        attempts=_ATTEMPTS,
        last_error=last_error or _missing_source_error(global_agent, revision),
        quarantined=True,
        quarantined_at=_CREATED_AT + 60,
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT + 60,
    )


def _plant(*rows: AgentPublicationOutboxItem) -> None:
    mutate_publication_outbox("proj", lambda items: (*items, *rows))


def _configure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runs: tuple[object, ...] = (),
) -> tuple[ProjectTarget, list[frozenset[str]]]:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    target, _remote = setup_target(tmp_path)
    configure_single_project_job(monkeypatch, target)
    monkeypatch.setattr(
        publication_support, "require_agent_owner_identity", lambda: OWNER
    )
    builds: list[frozenset[str]] = []

    def build(_target: object, _identity: object, **kwargs: object):
        requested = kwargs["requested_hoods"]
        assert isinstance(requested, frozenset)
        builds.append(requested)
        return ProjectHoodInventory(OWNER, "proj", runs)

    monkeypatch.setattr(quarantine_sweep, "build_project_hood_inventory", build)
    return target, builds


def _audit_lines() -> list[dict[str, object]]:
    path = terminal_obligations_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _by_agent() -> dict[str, AgentPublicationOutboxItem]:
    return {item.local_agent: item for item in list_agent_publications("proj")}


def test_pass_retires_quarantined_unrecoverable_row_without_charging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck quarantined row with no source anywhere becomes terminal once."""

    _target, builds = _configure(tmp_path, monkeypatch)
    stuck = _quarantined_row(tmp_path, 0)
    other = _quarantined_row(tmp_path, 1, last_error="agents sync lock is busy")
    _plant(stuck, other)

    summary = publication_job.run_publication_job(work_budget_seconds=60)

    assert summary.errors == 0
    assert summary.standing == 0
    assert summary.standing_report == []
    rows = _by_agent()
    retired = rows["worker0"]
    assert retired.terminal is True
    assert retired.quarantined is False
    assert retired.attempts == _ATTEMPTS
    assert is_terminal_prompt_archive_reason(retired.terminal_reason)
    assert retired.last_error == retired.terminal_reason
    assert "quarantined=True" in (retired.terminal_reason or "")
    # A quarantined row whose failure was not a prompt restore is untouched.
    assert rows["worker1"] == other
    # The run's source label was probed through a scoped inventory build.
    assert builds == [frozenset({"worker0"})]

    [audit] = _audit_lines()
    assert audit["global_agent"] == stuck.global_agent
    assert audit["primary_revision"] == stuck.primary_revision
    assert audit["run_id"] == stuck.run_id
    probes = audit["probes"]
    assert isinstance(probes, dict)
    assert probes["attempts_before"] == probes["attempts_after"] == _ATTEMPTS
    assert probes["quarantined_before"] is True

    # Another pass neither re-audits nor touches the retired row.
    second = publication_job.run_publication_job(work_budget_seconds=60)
    assert second.errors == 0
    assert len(_audit_lines()) == 1
    assert _by_agent()["worker0"] == retired

    # --retry-quarantined still never revives a terminal row.
    revived, _diagnostics = revive_agent_publications(
        "proj", retry_retired=False, retry_quarantined=True
    )
    assert [item.local_agent for item in revived] == ["worker1"]
    assert _by_agent()["worker0"].terminal is True


@pytest.mark.parametrize("source", ["artifacts_dir", "run_source_label"])
def test_pass_keeps_quarantined_row_whose_source_still_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    """A source in either probed location keeps the row quarantined, unchanged."""

    row = _quarantined_row(tmp_path, 0)
    live_dir = Path(row.artifacts_dir or "")
    runs: tuple[object, ...] = ()
    if source == "run_source_label":
        live_dir = tmp_path / "runs" / "live"
        live_dir.mkdir(parents=True)
        runs = (
            SimpleNamespace(
                local_name=row.local_agent,
                global_name=row.global_agent,
                commits=(SimpleNamespace(sha=row.primary_revision),),
                source_label=str(live_dir),
            ),
        )
    (live_dir / "raw_prompt.md").write_text("Still here.\n", encoding="utf-8")
    target, builds = _configure(tmp_path, monkeypatch, runs=runs)
    _plant(row)

    summary = publication_job.run_publication_job(work_budget_seconds=60)
    again = publication_job.run_publication_job(work_budget_seconds=60)

    assert summary.errors == 0
    assert again.errors == 0
    assert list_agent_publications("proj") == (row,)
    assert _audit_lines() == []
    # The run label is only needed when the row's own dir has no source, and
    # the re-check ledger keeps the second pass from probing the row again.
    expected_builds = [] if source == "artifacts_dir" else [frozenset({"worker0"})]
    assert builds == expected_builds
    # Nothing reached the sidecar: the sweep never publishes.
    verify = tmp_path / "verify"
    git(tmp_path, "clone", target.remote_url, str(verify))
    assert not (verify / "prompts").exists()


def test_pass_retires_at_most_the_per_pass_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backlog drains in capped batches across passes."""

    limit = quarantine_sweep.QUARANTINED_PROMPT_SWEEP_LIMIT
    _configure(tmp_path, monkeypatch)
    _plant(*(_quarantined_row(tmp_path, index) for index in range(limit + 3)))

    first = publication_job.run_publication_job(work_budget_seconds=60)

    assert first.errors == 0
    rows = list_agent_publications("proj")
    assert sum(item.terminal for item in rows) == limit
    assert sum(item.quarantined and not item.terminal for item in rows) == 3
    assert len(_audit_lines()) == limit

    second = publication_job.run_publication_job(work_budget_seconds=60)

    assert second.errors == 0
    rows = list_agent_publications("proj")
    assert all(item.terminal for item in rows)
    assert all(item.attempts == _ATTEMPTS for item in rows)
    assert len(_audit_lines()) == limit + 3
