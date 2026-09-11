"""Acceptance coverage for a real killed publisher process.

The audited defect forked a child process and SIGKILLed it inside
``os.fdopen`` immediately after the event installer created its final,
content-addressed path with ``O_EXCL``. That left a permanent zero-byte
file, and every later replay raised ``ArtifactLinkEventCorruptionError``
forever. Simulating the crash by writing a complete file before a replay
(as an in-process fixture might) never exercises that failure mode -- only
an actual killed process, interrupted mid-write, does. This module forks a
real child process through the production ``publish_artifact_link_events``
entry point and kills it there.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess

import pytest

from sase.sdd.artifact_link_event_publisher import (
    observation_or_put_event_from_row,
    publish_artifact_link_events,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes

PROJECT_KEY = "gh_sase-org__sase"


def test_real_killed_publisher_process_leaves_no_corrupt_object_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    plans = tmp_path / "plans"
    _init_local_repo(plans, {"202609/hot.md": "# Hot report\n"})
    store = ArtifactLinkStore(
        project_key=PROJECT_KEY,
        sidecar_roots={"plan": plans},
    )
    event = observation_or_put_event_from_row(
        _row(
            source="agent:reader.athena.worker",
            relation="read",
            target="plan:202609/hot.md",
            origin="read",
        ),
        project_key=PROJECT_KEY,
        operation_id="a" * 32,
    )

    child = os.fork()
    if child == 0:
        _die_mid_install_and_exit(store, event)

    _, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL

    staging_dir = plans / "link-events" / "v1" / ".staging"
    leftover_staging = list(staging_dir.glob("*.tmp")) if staging_dir.is_dir() else []
    assert leftover_staging, "expected an orphaned staging temp file after the kill"
    final_paths = list(plans.glob("link-events/v1/**/*.json"))
    assert final_paths == [], (
        "a killed installer must never leave a partial final object"
    )

    report = publish_artifact_link_events(
        store,
        (event,),
        push_after_commit=False,
        mutation_origin="machine",
    )

    assert report.publication_error is None
    assert report.published == 1
    assert report.published_operation_ids == ("a" * 32,)
    [installed] = plans.glob("link-events/v1/**/*.json")
    assert installed.read_bytes()
    assert not list(staging_dir.glob("*.tmp"))
    assert _git(plans, "status", "--porcelain", "--untracked-files=all") == ""
    [row] = store.load_aggregate()["rows"]
    assert row["uses"] == 1
    assert row["target_ref"] == "plan:202609/hot.md"


def _die_mid_install_and_exit(store: ArtifactLinkStore, event: object) -> None:
    """Run in the forked child: SIGKILL itself while writing the staged object."""

    import sase.sdd._artifact_link_event_install as installer

    def _kill_self(*_args: object, **_kwargs: object) -> None:
        os.kill(os.getpid(), signal.SIGKILL)

    installer.os.fdopen = _kill_self
    try:
        publish_artifact_link_events(
            store,
            (event,),  # type: ignore[arg-type]
            push_after_commit=False,
            mutation_origin="machine",
        )
    finally:
        # Only reached if the SIGKILL patch above did not fire.
        os._exit(1)


def _init_local_repo(repo: Path, documents: dict[str, str]) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "sase-test@example.invalid")
    _git(repo, "config", "user.name", "SASE Test")
    for relpath, content in documents.items():
        path = repo / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed local plans")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()
