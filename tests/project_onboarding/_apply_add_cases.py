"""Add, revalidation, and recovery cases for onboarding apply."""

from __future__ import annotations

import fcntl
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.history.vcs_macro_mru import vcs_macro_mru_path
from sase.project_onboarding._apply_effects import manage_repository
from sase.project_onboarding._apply_locks import _apply_identity_lock_path
from sase.project_onboarding.journal import lookup_journal
from sase.project_onboarding.manage import ManagementError
from ._apply_test_support import (
    IDENTITY,
    KEY,
    NAME,
    FakeGh,
    kinds,
    marker_commits,
    request as make_request,
    run,
    step_ids,
)
from sase.core.paths import sase_projects_dir


class TestFreshAdd:
    def test_ok_with_manage_identity_and_current(self, fake_gh: FakeGh) -> None:
        checkout = fake_gh.checkouts[IDENTITY]
        request = make_request(checkout)
        request["requested"] = {
            "setup": "auto",
            "make_current": True,
            "aliases": ["bobby"],
        }
        result, events = run(request)

        assert result["status"] == "ok"
        assert result["project"] == {"key": KEY, "name": NAME}
        assert result["next_argv"] == ["sase", "init", "-p", KEY]
        assert kinds(events) == [
            ("plan", ""),
            ("step", "running"),
            ("step", "done"),
            ("step", "running"),
            ("step", "done"),
            ("step", "running"),
            ("step", "done"),
            ("step", "running"),
            ("step", "done"),
            ("result", "ok"),
        ]
        assert step_ids(events) == [
            "checkout",
            "checkout",
            "identity",
            "identity",
            "manage",
            "manage",
            "current",
            "current",
        ]
        journal = lookup_journal(IDENTITY)
        assert journal is not None
        assert journal["status"] == "complete"
        assert journal["project_key"] == KEY
        assert len(marker_commits(fake_gh.origin)) == 2
        assert Path(checkout, "sase", "sase.yml").is_file()

    def test_rerun_converges_without_duplicate_effects(self, fake_gh: FakeGh) -> None:
        checkout = fake_gh.checkouts[IDENTITY]
        request = make_request(checkout)
        request["requested"] = {"setup": "auto", "make_current": True}
        first, _ = run(request)
        assert first["status"] == "ok"
        mru_mtime = vcs_macro_mru_path().stat().st_mtime_ns
        commits = marker_commits(fake_gh.origin)
        resolve_calls = len(fake_gh.resolve_calls)

        second, events = run(request)

        assert second["status"] == "ok"
        assert marker_commits(fake_gh.origin) == commits
        assert vcs_macro_mru_path().stat().st_mtime_ns == mru_mtime
        assert len(fake_gh.resolve_calls) == resolve_calls
        assert step_ids(events) == ["current", "current"]

    def test_rerun_preserves_aliases_without_rewrite(self, fake_gh: FakeGh) -> None:
        checkout = fake_gh.checkouts[IDENTITY]
        request = make_request(checkout)
        request["requested"] = {"setup": "auto", "aliases": ["bobby"]}
        first, _ = run(request)
        assert first["status"] == "ok"
        spec = sase_projects_dir() / KEY / f"{KEY}.sase"
        mtime = spec.stat().st_mtime_ns

        second, events = run(request)

        assert second["status"] == "ok"
        assert spec.stat().st_mtime_ns == mtime
        assert "identity" not in step_ids(events)


class TestBlockedRevalidation:
    def test_missing_remote_reports_blocked_without_effects(
        self, fake_gh: FakeGh
    ) -> None:
        fake_gh.probe_status = "not_found"
        checkout = fake_gh.checkouts[IDENTITY]
        result, events = run(make_request(checkout))

        assert result["status"] == "blocked"
        assert fake_gh.resolve_calls == []
        assert lookup_journal(IDENTITY) is None
        assert kinds(events) == [("plan", ""), ("result", "blocked")]

    def test_changed_preview_reports_blocked_without_effects(
        self, fake_gh: FakeGh
    ) -> None:
        checkout = fake_gh.checkouts[IDENTITY]
        stale_preview = {"intent_fingerprint": "0" * 64}
        result, events = run(make_request(checkout), plan=stale_preview)

        assert result["status"] == "blocked"
        assert "changed since it was reviewed" in result["message"]
        assert fake_gh.resolve_calls == []
        assert lookup_journal(IDENTITY) is None
        assert kinds(events) == [("plan", ""), ("result", "blocked")]

    def test_lock_contention_reports_blocked(self, fake_gh: FakeGh) -> None:
        lock_path = _apply_identity_lock_path(IDENTITY)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            checkout = fake_gh.checkouts[IDENTITY]
            result, events = run(make_request(checkout), lock_timeout=0.2)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

        assert result["status"] == "blocked"
        assert "another onboarding operation" in result["message"]
        assert fake_gh.resolve_calls == []
        assert kinds(events) == [("result", "blocked")]


class TestFailureRecovery:
    def test_checkout_failure_is_failed_without_registration(
        self, fake_gh: FakeGh
    ) -> None:
        fake_gh.fail_resolve = "network is down"
        checkout = fake_gh.checkouts[IDENTITY]
        result, events = run(make_request(checkout))

        assert result["status"] == "failed"
        assert result["next_argv"] == []
        journal = lookup_journal(IDENTITY)
        assert journal is not None
        assert journal["status"] == "failed"
        assert journal["stopped_step"] == "checkout"
        assert kinds(events)[0] == ("plan", "")
        assert kinds(events)[-2:] == [("step", "failed"), ("result", "failed")]

    def test_manage_failure_is_partial_and_retry_converges(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = fake_gh.checkouts[IDENTITY]

        def _refused(*args: Any, **kwargs: Any) -> Any:
            raise ManagementError("push rejected: protected branch")

        real_manage = manage_repository
        monkeypatch.setattr(
            "sase.project_onboarding._apply_effects.manage_repository", _refused
        )
        result, _ = run(make_request(checkout))

        assert result["status"] == "partial"
        assert "protected branch" in result["message"]
        assert "re-run the same command" in result["message"]
        assert len(marker_commits(fake_gh.origin)) == 1

        monkeypatch.setattr(
            "sase.project_onboarding._apply_effects.manage_repository", real_manage
        )
        retried, _ = run(make_request(checkout))

        assert retried["status"] == "ok"
        assert len(marker_commits(fake_gh.origin)) == 2
        journal = lookup_journal(IDENTITY)
        assert journal is not None
        assert journal["status"] == "complete"

    def test_identity_failure_is_partial(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = fake_gh.checkouts[IDENTITY]
        request = make_request(checkout)
        request["requested"] = {"setup": "off", "name": "taken"}

        def _boom(project: str, name: str, **kwargs: Any) -> Any:
            raise ValueError("project name 'taken' is already taken")

        monkeypatch.setattr("sase.project_aliases.ensure_project_name_locked", _boom)
        result, _ = run(request)

        assert result["status"] == "partial"
        assert "already taken" in result["message"]

    def test_current_failure_is_partial(
        self, fake_gh: FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = fake_gh.checkouts[IDENTITY]
        request = make_request(checkout)
        request["requested"] = {"setup": "off", "make_current": True}
        monkeypatch.setattr(
            "sase.current_project.set_current_project",
            lambda project_key, **kwargs: SimpleNamespace(
                status="ineligible",
                project=None,
                message="test project is disabled; enable it first.",
            ),
        )
        result, _ = run(request)

        assert result["status"] == "partial"
        assert "disabled" in result["message"]
