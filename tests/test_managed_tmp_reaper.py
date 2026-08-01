"""Tests for the bounded reaper over the managed SASE temp root."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sase.core.managed_tmp_reaper import (
    COMMAND_SCRATCH_HORIZON_SECONDS,
    DEFAULT_HORIZON_SECONDS,
    RUN_ARTIFACT_HORIZON_SECONDS,
    reap_managed_tmpdir,
)
from sase.core.paths import PYTEST_SANDBOX_MANAGED_TMPDIR_NAME
from sase.core.state_write_guard import PYTEST_SANDBOX_DIR_ENV_VAR


NOW = 1_800_000_000.0
HOUR = 3600.0
DAY = 24 * HOUR


def _fail_on_call(dirs: object) -> int:
    raise AssertionError(f"artifact index touched for {dirs!r}")


def _aged_file(root: Path, relative: str, *, age_seconds: float) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("scratch", encoding="utf-8")
    stamp = NOW - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def _aged_dir(root: Path, relative: str, *, age_seconds: float) -> Path:
    path = root / relative
    path.mkdir(parents=True, exist_ok=True)
    (path / "state.json").write_text("{}", encoding="utf-8")
    stamp = NOW - age_seconds
    os.utime(path / "state.json", (stamp, stamp))
    os.utime(path, (stamp, stamp))
    return path


def test_horizons_are_chosen_per_subdirectory(tmp_path: Path) -> None:
    stale_editor = _aged_file(tmp_path, "editors/note.md", age_seconds=13 * HOUR)
    fresh_editor = _aged_file(tmp_path, "editors/open.md", age_seconds=11 * HOUR)
    stale_agent_cli = _aged_dir(
        tmp_path, "agent-clis/command-old", age_seconds=13 * HOUR
    )
    fresh_agent_cli = _aged_dir(
        tmp_path, "agent-clis/command-live", age_seconds=11 * HOUR
    )
    # Well past the command-scratch horizon, but the Agents tab still reads it.
    young_prompt = _aged_file(tmp_path, "launch-prompts/a.md", age_seconds=13 * HOUR)
    old_prompt = _aged_file(tmp_path, "launch-prompts/b.md", age_seconds=15 * DAY)

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert not stale_editor.exists()
    assert fresh_editor.exists()
    assert not stale_agent_cli.exists()
    assert fresh_agent_cli.exists()
    assert young_prompt.exists()
    assert not old_prompt.exists()
    assert result.removed == 3
    assert result.removed_by_subdir == {
        "agent-clis": 1,
        "editors": 1,
        "launch-prompts": 1,
    }
    assert result.scanned == 6
    assert not result.capped


def test_reaped_directories_drop_their_artifact_index_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A reaped ``workflow-artifacts/`` entry may have been an agents_dir."""
    stale = _aged_dir(
        tmp_path,
        "workflow-artifacts/workflow-simple-abc",
        age_seconds=RUN_ARTIFACT_HORIZON_SECONDS + HOUR,
    )
    _aged_file(tmp_path, "editors/note.md", age_seconds=13 * HOUR)
    deleted: list[list[Path]] = []
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle_mutations."
        "delete_agent_artifact_index_artifacts",
        lambda dirs: deleted.append(list(dirs)) or len(deleted[-1]),
    )

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    # Only the directory is de-indexed; the reaped editor file never had a row.
    assert deleted == [[stale]]
    assert result.deindexed == 1


def test_a_file_only_pass_never_touches_the_artifact_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _aged_file(tmp_path, "editors/note.md", age_seconds=13 * HOUR)
    monkeypatch.setattr(
        "sase.core.agent_artifact_index_lifecycle_mutations."
        "delete_agent_artifact_index_artifacts",
        _fail_on_call,
    )

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert result.removed == 1
    assert result.deindexed == 0


def test_workflow_artifact_directories_are_pruned_whole(tmp_path: Path) -> None:
    stale = _aged_dir(
        tmp_path,
        "workflow-artifacts/workflow-refresh_docs-abc",
        age_seconds=RUN_ARTIFACT_HORIZON_SECONDS + HOUR,
    )
    fresh = _aged_dir(
        tmp_path,
        "workflow-artifacts/workflow-refresh_docs-def",
        age_seconds=RUN_ARTIFACT_HORIZON_SECONDS - HOUR,
    )

    reap_managed_tmpdir(tmp_path, now=NOW)

    assert not stale.exists()
    assert (fresh / "state.json").exists()


def test_managed_subdirectories_themselves_always_survive(tmp_path: Path) -> None:
    """An empty, ancient ``editors/`` is a mount point, not stale scratch.

    Removing it would race every ``get_sase_managed_tmpdir("editors")`` caller
    that has just created it and is about to write into it.
    """
    editors = tmp_path / "editors"
    editors.mkdir()
    stamp = NOW - 400 * DAY
    os.utime(editors, (stamp, stamp))

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert editors.is_dir()
    assert result.removed == 0


def test_unknown_top_level_entries_use_the_default_horizon(tmp_path: Path) -> None:
    residue = _aged_file(
        tmp_path, "sase_ace_prompt_old.md", age_seconds=DEFAULT_HORIZON_SECONDS + HOUR
    )
    recent = _aged_file(
        tmp_path, "sase_ace_prompt_new.md", age_seconds=DEFAULT_HORIZON_SECONDS - HOUR
    )
    unknown_subdir = _aged_dir(
        tmp_path, "some-future-bucket", age_seconds=DEFAULT_HORIZON_SECONDS + HOUR
    )

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert not residue.exists()
    assert recent.exists()
    assert not unknown_subdir.exists()
    assert result.removed_by_subdir == {"<root>": 2}


def test_a_concurrent_command_s_fresh_scratch_survives(tmp_path: Path) -> None:
    """Entries written while the reaper runs keep a present-day mtime."""
    (tmp_path / "wrappers").mkdir()
    live = tmp_path / "wrappers" / "tmpabc.sh"
    live.write_text("#!/bin/sh\n", encoding="utf-8")
    os.utime(live, (NOW, NOW))

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert live.exists()
    assert result.removed == 0


def test_symlinks_are_neither_followed_nor_removed(tmp_path: Path) -> None:
    target = tmp_path.parent / "precious.txt"
    target.write_text("keep me", encoding="utf-8")
    (tmp_path / "editors").mkdir()
    link = tmp_path / "editors" / "link.md"
    link.symlink_to(target)
    stamp = NOW - 400 * DAY
    os.utime(link, (stamp, stamp), follow_symlinks=False)

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert link.is_symlink()
    assert target.exists()
    assert result.removed == 0


def test_removals_are_capped_per_invocation(tmp_path: Path) -> None:
    for index in range(5):
        _aged_file(
            tmp_path,
            f"editors/note-{index}.md",
            age_seconds=COMMAND_SCRATCH_HORIZON_SECONDS + HOUR,
        )

    first = reap_managed_tmpdir(tmp_path, now=NOW, max_removals=2)

    assert first.removed == 2
    assert first.capped
    assert len(list((tmp_path / "editors").iterdir())) == 3

    second = reap_managed_tmpdir(tmp_path, now=NOW, max_removals=100)

    assert second.removed == 3
    assert not second.capped
    assert list((tmp_path / "editors").iterdir()) == []


def test_a_missing_root_is_not_an_error(tmp_path: Path) -> None:
    result = reap_managed_tmpdir(tmp_path / "absent", now=NOW)

    assert result.removed == 0
    assert result.scanned == 0
    assert not result.capped


@pytest.mark.parametrize(
    "unsafe_root",
    [Path("/"), Path("/tmp"), Path("/var/tmp"), Path.cwd(), Path.cwd().parent],
)
def test_broad_cleanup_roots_are_rejected(unsafe_root: Path) -> None:
    with pytest.raises(ValueError, match="dedicated directory"):
        reap_managed_tmpdir(unsafe_root, now=NOW)


def test_describe_names_the_busiest_buckets(tmp_path: Path) -> None:
    for index in range(3):
        _aged_file(tmp_path, f"editors/n{index}.md", age_seconds=13 * HOUR)
    _aged_file(tmp_path, "viewers/diff.txt", age_seconds=13 * HOUR)

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert result.describe() == (
        f"reclaimed 4 entries under {tmp_path}: editors=3, viewers=1"
    )


def test_describe_reports_an_idle_pass(tmp_path: Path) -> None:
    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert result.describe() == f"nothing stale under {tmp_path}"


def test_describe_flags_a_capped_pass(tmp_path: Path) -> None:
    for index in range(2):
        _aged_file(tmp_path, f"editors/n{index}.md", age_seconds=13 * HOUR)

    result = reap_managed_tmpdir(tmp_path, now=NOW, max_removals=1)

    assert result.describe().endswith("(removal budget reached)")


def test_the_default_root_follows_the_managed_tmpdir_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No explicit root means the same sandbox-aware root writers resolve."""
    sandbox = tmp_path / "sandbox"
    managed = sandbox / PYTEST_SANDBOX_MANAGED_TMPDIR_NAME
    monkeypatch.setenv(PYTEST_SANDBOX_DIR_ENV_VAR, str(sandbox))
    monkeypatch.setenv("SASE_TMPDIR", str(tmp_path / "developer-root"))
    stale = _aged_file(managed, "editors/note.md", age_seconds=13 * HOUR)

    result = reap_managed_tmpdir(now=NOW)

    assert result.root == managed
    assert not stale.exists()
    assert not (tmp_path / "developer-root").exists()
