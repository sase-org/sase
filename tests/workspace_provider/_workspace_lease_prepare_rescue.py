"""Rescue-on-dirty preparation tests (sase-mq.2)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from tests.workspace_provider._workspace_lease_prepare_helpers import (
    prepared_lease_checkout,
)

__all__ = ["TestLeasePrepareRescue"]


class TestLeasePrepareRescue:
    def test_dirty_tracked_file_triggers_rescue_and_resets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        from sase.workspace_provider.lease import _prepare_from_primary_remote

        _remote, checkout = prepared_lease_checkout(tmp_path)
        _prepare_from_primary_remote(checkout, workspace_num=7)
        (checkout / "README").write_text("dirty\n", encoding="utf-8")

        calls: list[dict[str, Any]] = []

        def _fake_rescue(
            repo_root: Path | str,
            *,
            workspace_dir: Path | str,
            workspace_num: int,
            label: str,
            reason: str,
            include_worktree: bool,
        ) -> object:
            calls.append(
                {
                    "repo_root": Path(repo_root),
                    "workspace_dir": Path(workspace_dir),
                    "workspace_num": workspace_num,
                    "label": label,
                    "reason": reason,
                    "include_worktree": include_worktree,
                }
            )
            return object()

        monkeypatch.setattr(
            "sase.workspace_provider.rescue.rescue_git_repo", _fake_rescue
        )

        _prepare_from_primary_remote(checkout, workspace_num=7)

        assert len(calls) == 1
        assert calls[0]["repo_root"] == checkout
        assert calls[0]["workspace_dir"] == checkout
        assert calls[0]["workspace_num"] == 7
        assert calls[0]["label"] == "lease-checkout"
        assert "operational lease preparation" in calls[0]["reason"]
        assert calls[0]["include_worktree"] is True
        assert (checkout / "README").read_text(encoding="utf-8") == "two\n"

    def test_clean_tree_with_stash_triggers_no_rescue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess

        from sase.workspace_provider.lease import _prepare_from_primary_remote

        _remote, checkout = prepared_lease_checkout(tmp_path)
        _prepare_from_primary_remote(checkout, workspace_num=7)
        (checkout / "README").write_text("stashed\n", encoding="utf-8")
        subprocess.run(
            ["git", "stash", "push", "-m", "pooled"],
            cwd=checkout,
            check=True,
            capture_output=True,
        )

        calls: list[dict[str, Any]] = []

        def _fake_rescue(*args: Any, **kwargs: Any) -> object | None:
            calls.append({"args": args, "kwargs": kwargs})
            return object()

        monkeypatch.setattr(
            "sase.workspace_provider.rescue.rescue_git_repo", _fake_rescue
        )

        _prepare_from_primary_remote(checkout, workspace_num=7)

        assert calls == []
        assert (checkout / "README").read_text(encoding="utf-8") == "two\n"

    def test_untracked_only_triggers_no_rescue_and_keeps_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        _remote, checkout = prepared_lease_checkout(tmp_path)
        _prepare_from_primary_remote(checkout, workspace_num=7)
        (checkout / "untracked.txt").write_text("keep me\n", encoding="utf-8")

        calls: list[dict[str, Any]] = []

        def _fake_rescue(*args: Any, **kwargs: Any) -> object | None:
            calls.append({"args": args, "kwargs": kwargs})
            return object()

        monkeypatch.setattr(
            "sase.workspace_provider.rescue.rescue_git_repo", _fake_rescue
        )

        _prepare_from_primary_remote(checkout, workspace_num=7)

        assert calls == []
        assert (checkout / "untracked.txt").read_text(encoding="utf-8") == "keep me\n"
        assert (checkout / "README").read_text(encoding="utf-8") == "two\n"

    def test_rescue_failure_warns_and_resets_anyway(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from sase.workspace_provider.lease import _prepare_from_primary_remote

        _remote, checkout = prepared_lease_checkout(tmp_path)
        _prepare_from_primary_remote(checkout, workspace_num=7)
        (checkout / "README").write_text("dirty\n", encoding="utf-8")

        def _failing_rescue(*args: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr(
            "sase.workspace_provider.rescue.rescue_git_repo", _failing_rescue
        )

        with caplog.at_level(
            logging.WARNING, logger="sase.workspace_provider._lease_git"
        ):
            _prepare_from_primary_remote(checkout, workspace_num=7)

        warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING
            and "sase.workspace_provider._lease_git" in r.name
        ]
        assert len(warnings) == 1
        assert str(checkout) in warnings[0].getMessage()
        assert (checkout / "README").read_text(encoding="utf-8") == "two\n"
