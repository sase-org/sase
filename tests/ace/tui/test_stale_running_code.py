"""Stat-gated detection for stale editable code imported by ACE."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.stale_running_code import (
    RunningCodeRoot,
    RunningCodeState,
    _capture_running_code_state,
    _revalidate_running_code_state,
)
from sase.updates import CommitSourceSpec, CommitSummary, IncomingCommits
from sase.version._models import GitVersionMetadata, VersionPackageRecord

_OLD_SHA = "1" * 40
_NEW_SHA = "2" * 40


def _record(
    *,
    root: Path,
    name: str = "sase",
    install_type: str = "editable",
    git: GitVersionMetadata | None | object = ...,
) -> VersionPackageRecord:
    if git is ...:
        git = GitVersionMetadata(
            root=str(root),
            commit=_OLD_SHA,
            short_commit=_OLD_SHA[:9],
            tag=None,
            distance=None,
            dirty=False,
        )
    return VersionPackageRecord(
        name=name,
        role="host",
        display_version="dev",
        distribution_version=None,
        source_version=None,
        import_module="sase",
        import_path=None,
        code_directory=str(root / "src"),
        source_root=str(root),
        distribution_location=None,
        install_type=install_type,  # type: ignore[arg-type]
        git=git if isinstance(git, GitVersionMetadata) else None,
    )


def _git_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    ref = root / ".git" / "refs" / "heads" / "main"
    ref.parent.mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    ref.write_text(_OLD_SHA, encoding="utf-8")
    return root, ref


def _touch_new_ref(ref: Path) -> None:
    ref.write_text(_NEW_SHA, encoding="utf-8")
    stat = ref.stat()
    os.utime(ref, ns=(stat.st_atime_ns + 1_000_000, stat.st_mtime_ns + 1_000_000))


def test_capture_records_editable_git_roots_from_runtime_inventory(
    tmp_path: Path,
) -> None:
    root, ref = _git_root(tmp_path)

    state = _capture_running_code_state(
        inventory_fn=lambda: SimpleNamespace(
            packages=(
                _record(root=root, name="sase"),
                _record(root=root, name="sase-github"),
            )
        )
    )

    assert len(state.roots) == 1
    captured = state.roots[0]
    assert captured.label == "sase + 1 more"
    assert captured.git_root == str(root)
    assert captured.imported_sha == _OLD_SHA
    assert captured.current_sha == _OLD_SHA
    assert captured.head_path == str(ref)
    assert captured.is_stale is False


def test_capture_ignores_unknown_and_non_editable_roots(tmp_path: Path) -> None:
    root, _ref = _git_root(tmp_path)

    state = _capture_running_code_state(
        inventory_fn=lambda: SimpleNamespace(
            packages=(
                _record(root=root, install_type="wheel"),
                _record(root=root, git=None),
            )
        )
    )

    assert state.roots == ()


def test_revalidate_uses_only_stat_tokens_when_head_is_quiet(tmp_path: Path) -> None:
    root, _ref = _git_root(tmp_path)
    state = _capture_running_code_state(
        inventory_fn=lambda: SimpleNamespace(packages=(_record(root=root),))
    )

    updated = _revalidate_running_code_state(
        state,
        head_fn=lambda _root: (_ for _ in ()).throw(AssertionError("no git read")),
    )

    assert updated is state


def test_revalidate_resolves_head_and_fetches_preview_after_stat_drift(
    tmp_path: Path,
) -> None:
    root, ref = _git_root(tmp_path)
    state = _capture_running_code_state(
        inventory_fn=lambda: SimpleNamespace(packages=(_record(root=root),))
    )
    _touch_new_ref(ref)
    head_calls: list[str] = []
    specs: list[CommitSourceSpec] = []

    def fetch(spec: CommitSourceSpec, **_kwargs: Any) -> IncomingCommits:
        specs.append(spec)
        return IncomingCommits(
            total=1,
            commits=(CommitSummary("2222222", "land fix"),),
            source="git",
        )

    updated = _revalidate_running_code_state(
        state,
        head_fn=lambda git_root: head_calls.append(git_root) or _NEW_SHA,
        fetch_incoming_fn=fetch,
    )

    assert head_calls == [str(root)]
    assert updated.is_stale is True
    stale = updated.stale_roots[0]
    assert stale.current_sha == _NEW_SHA
    assert stale.incoming is not None
    assert specs[0].git_root == str(root)
    assert specs[0].current_ref == _OLD_SHA
    assert specs[0].upstream_ref == _NEW_SHA


def test_revalidate_clears_stale_state_when_head_returns_to_imported_sha(
    tmp_path: Path,
) -> None:
    root, ref = _git_root(tmp_path)
    state = RunningCodeState(
        roots=(
            RunningCodeRoot(
                label="sase",
                git_root=str(root),
                imported_sha=_OLD_SHA,
                current_sha=_NEW_SHA,
                git_dir=str(root / ".git"),
                head_path=str(ref),
                packed_refs_path=str(root / ".git" / "packed-refs"),
                token=type("Token", (), {})(),  # type: ignore[arg-type]
                incoming=IncomingCommits(total=1, commits=(), source="git"),
            ),
        )
    )
    _touch_new_ref(ref)

    updated = _revalidate_running_code_state(state, head_fn=lambda _root: _OLD_SHA)

    assert updated.is_stale is False
    assert updated.roots[0].incoming is None
