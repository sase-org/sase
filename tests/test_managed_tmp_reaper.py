"""Core horizon-selection and safety semantics for the managed-tmp reaper."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from sase.core.managed_tmp_reaper import (
    BUILD_SCRATCH_HORIZON_SECONDS,
    COMMAND_SCRATCH_HORIZON_SECONDS,
    DEFAULT_HORIZON_SECONDS,
    HANDOFF_HORIZON_SECONDS,
    MANAGED_TMPDIR_HORIZONS,
)
from sase.core.paths import PYTEST_SANDBOX_MANAGED_TMPDIR_NAME
from sase.core.state_write_guard import PYTEST_SANDBOX_DIR_ENV_VAR
from tests._managed_tmp_reaper_helpers import (
    DAY,
    HOUR,
    NOW,
    _aged_dir,
    _aged_file,
    reap_managed_tmpdir,
)


def test_horizons_are_chosen_per_subdirectory(tmp_path: Path) -> None:
    stale_editor = _aged_file(tmp_path, "editors/note.md", age_seconds=13 * HOUR)
    fresh_editor = _aged_file(tmp_path, "editors/open.md", age_seconds=11 * HOUR)
    stale_agent_cli = _aged_dir(
        tmp_path, "agent-clis/command-old", age_seconds=13 * HOUR
    )
    fresh_agent_cli = _aged_dir(
        tmp_path, "agent-clis/command-live", age_seconds=11 * HOUR
    )
    stale_agent_tmp = _aged_dir(tmp_path, "agent-tmp/launch-old", age_seconds=13 * HOUR)
    fresh_agent_tmp = _aged_dir(
        tmp_path, "agent-tmp/launch-live", age_seconds=11 * HOUR
    )
    stale_cargo_target = _aged_dir(
        tmp_path,
        "cargo-targets/launch-old",
        age_seconds=BUILD_SCRATCH_HORIZON_SECONDS + HOUR,
    )
    fresh_cargo_target = _aged_dir(
        tmp_path,
        "cargo-targets/launch-live",
        age_seconds=BUILD_SCRATCH_HORIZON_SECONDS - HOUR,
    )
    # Well past the command-scratch horizon, but the Agents tab still reads it.
    young_prompt = _aged_file(tmp_path, "launch-prompts/a.md", age_seconds=13 * HOUR)
    old_prompt = _aged_file(tmp_path, "launch-prompts/b.md", age_seconds=15 * DAY)

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert not stale_editor.exists()
    assert fresh_editor.exists()
    assert not stale_agent_cli.exists()
    assert fresh_agent_cli.exists()
    assert not stale_agent_tmp.exists()
    assert fresh_agent_tmp.exists()
    assert not stale_cargo_target.exists()
    assert fresh_cargo_target.exists()
    assert young_prompt.exists()
    assert not old_prompt.exists()
    assert result.removed == 5
    assert result.removed_by_subdir == {
        "agent-clis": 1,
        "agent-tmp": 1,
        "cargo-targets": 1,
        "editors": 1,
        "launch-prompts": 1,
    }
    assert result.scanned == 10
    assert not result.capped


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
    stale_unknown_child = _aged_file(
        tmp_path,
        "some-future-bucket/old.tmp",
        age_seconds=DEFAULT_HORIZON_SECONDS + HOUR,
    )
    fresh_unknown_child = _aged_file(
        tmp_path,
        "some-future-bucket/new.tmp",
        age_seconds=DEFAULT_HORIZON_SECONDS - HOUR,
    )
    unknown_bucket = tmp_path / "some-future-bucket"

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert not residue.exists()
    assert recent.exists()
    assert unknown_bucket.is_dir()
    assert not stale_unknown_child.exists()
    assert fresh_unknown_child.exists()
    assert result.removed_by_subdir == {"<root>": 1, "some-future-bucket": 1}


def test_every_literal_managed_tmpdir_bucket_has_a_horizon() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    buckets: set[str] = set()

    for source in (repo_root / "src" / "sase").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        if "get_sase_managed_tmpdir" not in text:
            continue
        module = ast.parse(text)
        constants = _module_string_constants(module)
        for node in ast.walk(module):
            if not isinstance(node, ast.Call) or not _calls_managed_tmpdir(node):
                continue
            if not node.args:
                continue
            bucket = _literal_or_module_constant(node.args[0], constants)
            if bucket is not None:
                buckets.add(bucket)

    assert buckets - set(MANAGED_TMPDIR_HORIZONS) == set()


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


def test_muse_prompts_bucket_uses_the_handoff_horizon(tmp_path: Path) -> None:
    """Regression test: muse-prompts is a handoff bucket, not command scratch.

    A provider re-reads this file mid-run, so the old 12h command-scratch
    horizon could delete it out from under an in-progress launch.
    """
    from sase.core.managed_tmp_reaper import MANAGED_TMPDIR_HORIZONS

    assert MANAGED_TMPDIR_HORIZONS["muse-prompts"] == HANDOFF_HORIZON_SECONDS

    survives = _aged_file(tmp_path, "muse-prompts/prompt.md", age_seconds=13 * HOUR)

    result = reap_managed_tmpdir(tmp_path, now=NOW)

    assert survives.exists()
    assert result.removed == 0


def _module_string_constants(module: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                constants[target.id] = node.value.value
    return constants


def _calls_managed_tmpdir(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "get_sase_managed_tmpdir"
    if isinstance(func, ast.Attribute):
        return func.attr == "get_sase_managed_tmpdir"
    return False


def _literal_or_module_constant(
    node: ast.expr,
    constants: dict[str, str],
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None
