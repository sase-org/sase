"""Tests for serialized convergent onboarding execution."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase import workspace_provider
from sase.core.paths import sase_projects_dir
from sase.history.vcs_macro_mru import vcs_macro_mru_path
from sase.project_onboarding import apply as apply_mod
from sase.project_onboarding import parse_event_line
from sase.project_onboarding.apply import apply_plan
from sase.project_onboarding.journal import lookup_journal
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoProbe,
    ResolvedRef,
    WorkflowMetadata,
)

_OWNER = "sase-org"
_NAME = "bob"
_IDENTITY = "github.com/sase-org/bob"
_REF = "sase-org/bob"
_KEY = "gh_sase-org__bob"


def _git(path: Path, *args: str) -> None:
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "Onboarding Test",
            "GIT_AUTHOR_EMAIL": "onboarding@example.test",
            "GIT_COMMITTER_NAME": "Onboarding Test",
            "GIT_COMMITTER_EMAIL": "onboarding@example.test",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    subprocess.run(
        ["git", *args],
        cwd=path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def _metadata() -> list[WorkflowMetadata]:
    return [
        WorkflowMetadata(
            workflow_type="gh",
            ref_pattern="",
            display_name="GitHub",
            pre_allocated_env_prefix="",
            sdd_storage_policy="separate_repo",
        )
    ]


class _FakeGh:
    """Provider double: parse/probe/resolve over a disposable bare remote.

    The bare file path stands in for the real remote URL, so ``parse``
    maps the bare path back to the repository identity exactly as the
    real provider maps its remote URLs.
    """

    def __init__(self, home: Path) -> None:
        self.home = home
        self.origin = home / "origin.git"
        self.checkouts: dict[str, str] = {}
        self.resolve_calls: list[str] = []
        self.allocate_key: str | None = None
        self.fail_resolve: str = ""
        self.probe_status = "found"
        self.probe_message = ""
        self.can_push: bool | None = True
        self.sase_managed = False

    def seed(self) -> None:
        self.origin.mkdir(parents=True, exist_ok=True)
        _git(self.home, "init", "--bare", "--initial-branch=main", str(self.origin))
        seed = self.home / "seed"
        seed.mkdir()
        _git(seed, "init", "--initial-branch=main")
        config = seed / "sase" / "sase.yml"
        config.parent.mkdir()
        config.write_text("# project settings\nname: bob\n", encoding="utf-8")
        _git(seed, "add", "sase/sase.yml")
        _git(seed, "commit", "-m", "initial project config")
        _git(seed, "remote", "add", "origin", str(self.origin))
        _git(seed, "push", "-u", "origin", "main")

    def checkout_for(self, identity: str, tmp_path: Path, name: str) -> str:
        path = tmp_path / name
        self.checkouts[identity] = str(path)
        return str(path)

    def _for_repo(self, owner: str, name: str) -> ParsedRepoRef:
        identity = f"github.com/{owner}/{name}".casefold()
        checkout = self.checkouts.get(identity, str(self.home / f"co-{name}"))
        return ParsedRepoRef(
            workflow_type="gh",
            ref=f"{owner}/{name}",
            identity_key=identity,
            display=f"{owner}/{name}",
            host="github.com",
            owner=owner,
            name=name,
            project_key_base=f"gh_{owner}__{name}",
            project_name_base=name,
            checkout_dir=checkout,
            web_url=f"https://github.com/{owner}/{name}",
        )

    def parse(self, workflow_type: str, text: str) -> ParsedRepoRef | None:
        if workflow_type != "gh":
            return None
        value = text.strip()
        if value == str(self.origin):
            return self._for_repo(_OWNER, _NAME)
        if value.startswith("gh:"):
            value = value[3:]
        marker = "github.com/"
        if marker in value:
            value = value.rstrip("/").split(marker)[-1].removesuffix(".git")
        if "/" not in value:
            return None
        owner, name = value.split("/", 1)
        if not owner or not name or "/" in name:
            return None
        return self._for_repo(owner, name)

    def probe(self, workflow_type: str, ref: str) -> RepoProbe:
        parsed = self.parse(workflow_type, ref)
        assert parsed is not None
        return RepoProbe(
            status=self.probe_status,  # type: ignore[arg-type]
            parsed=parsed,
            visibility="private",
            default_branch="main",
            can_push=self.can_push,
            sase_managed=self.sase_managed,
            web_url=parsed.web_url,
            repo_id="R1",
            message=self.probe_message,
        )

    def resolve(self, ref: str, workflow_type: str) -> ResolvedRef:
        self.resolve_calls.append(ref)
        if self.fail_resolve:
            raise ValueError(self.fail_resolve)
        parsed = self.parse(workflow_type, ref)
        assert parsed is not None
        checkout = Path(parsed.checkout_dir)
        if checkout.is_dir() and not any(checkout.iterdir()):
            raise ValueError(f"clone target {checkout} already exists")
        if not (checkout / ".git").exists():
            if checkout.exists():
                raise ValueError(f"{checkout} is not a matching clone")
            _git(self.home, "clone", str(self.origin), str(checkout))
            _git(checkout, "config", "user.name", "Onboarding Test")
            _git(checkout, "config", "user.email", "onboarding@example.test")
        key = self.allocate_key or parsed.project_key_base
        spec_dir = sase_projects_dir() / key
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec = spec_dir / f"{key}.sase"
        if not spec.is_file():
            spec.write_text(
                f"WORKSPACE_DIR: {checkout}\nPROJECT_NAME: {parsed.name}\n",
                encoding="utf-8",
            )
        return ResolvedRef(
            project_file=str(spec),
            project_name=key,
            primary_workspace_dir=str(checkout),
            checkout_target=str(checkout),
        )


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _FakeGh:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    fake = _FakeGh(home)
    fake.seed()
    fake.checkout_for(_IDENTITY, tmp_path, "checkout")
    monkeypatch.setattr(workspace_provider, "get_all_workflow_metadata", _metadata)
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", fake.parse)
    monkeypatch.setattr(workspace_provider, "probe_repo", fake.probe)
    monkeypatch.setattr(
        workspace_provider, "get_display_name", lambda workflow_type: "GitHub"
    )
    monkeypatch.setattr(workspace_provider, "resolve_ref", fake.resolve)
    monkeypatch.setattr(
        workspace_provider, "detect_workflow_type", lambda project_file: "gh"
    )
    return fake


def _request(checkout: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": "add",
        "actor": "human",
        "target": {
            "workflow_type": "gh",
            "identity_key": _IDENTITY,
            "ref": _REF,
            "display": _REF,
            "checkout_dir": checkout,
            "project_key_base": _KEY,
            "project_name_base": _NAME,
            "storage_policy": "separate_repo",
            "web_url": "https://github.com/sase-org/bob",
            "provider_display": "GitHub",
        },
        "requested": {"setup": "auto", "make_current": False},
    }
    payload.update(overrides)
    return payload


def _run(request: dict[str, Any], **kwargs: Any) -> tuple[dict, list[dict]]:
    events: list[dict[str, Any]] = []
    result = apply_plan(request, emit=events.append, **kwargs)
    return result, events


def _kinds(events: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(str(item.get("event")), str(item.get("status") or "")) for item in events]


def _step_ids(events: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id")) for item in events if item.get("event") == "step"]


def _marker_commits(bare: Path) -> list[str]:
    out = subprocess.run(
        ["git", "--git-dir", str(bare), "log", "--format=%H %s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


class TestFreshAdd:
    def test_ok_with_manage_identity_and_current(self, fake_gh: _FakeGh) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]
        request = _request(checkout)
        request["requested"] = {
            "setup": "auto",
            "make_current": True,
            "aliases": ["bobby"],
        }
        result, events = _run(request)

        assert result["status"] == "ok"
        assert result["project"] == {"key": _KEY, "name": _NAME}
        assert result["next_argv"] == ["sase", "init", "-p", _KEY]
        assert _kinds(events) == [
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
        assert _step_ids(events) == [
            "checkout",
            "checkout",
            "identity",
            "identity",
            "manage",
            "manage",
            "current",
            "current",
        ]
        journal = lookup_journal(_IDENTITY)
        assert journal is not None
        assert journal["status"] == "complete"
        assert journal["project_key"] == _KEY
        assert len(_marker_commits(fake_gh.origin)) == 2
        assert Path(checkout, "sase", "sase.yml").is_file()

    def test_rerun_converges_without_duplicate_effects(self, fake_gh: _FakeGh) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]
        request = _request(checkout)
        request["requested"] = {"setup": "auto", "make_current": True}
        first, _ = _run(request)
        assert first["status"] == "ok"
        mru_mtime = vcs_macro_mru_path().stat().st_mtime_ns
        commits = _marker_commits(fake_gh.origin)
        resolve_calls = len(fake_gh.resolve_calls)

        second, events = _run(request)

        assert second["status"] == "ok"
        assert _marker_commits(fake_gh.origin) == commits
        assert vcs_macro_mru_path().stat().st_mtime_ns == mru_mtime
        assert len(fake_gh.resolve_calls) == resolve_calls
        assert _step_ids(events) == ["current", "current"]

    def test_rerun_preserves_aliases_without_rewrite(self, fake_gh: _FakeGh) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]
        request = _request(checkout)
        request["requested"] = {"setup": "auto", "aliases": ["bobby"]}
        first, _ = _run(request)
        assert first["status"] == "ok"
        spec = sase_projects_dir() / _KEY / f"{_KEY}.sase"
        mtime = spec.stat().st_mtime_ns

        second, events = _run(request)

        assert second["status"] == "ok"
        assert spec.stat().st_mtime_ns == mtime
        assert "identity" not in _step_ids(events)


class TestBlockedRevalidation:
    def test_missing_remote_reports_blocked_without_effects(
        self, fake_gh: _FakeGh
    ) -> None:
        fake_gh.probe_status = "not_found"
        checkout = fake_gh.checkouts[_IDENTITY]
        result, events = _run(_request(checkout))

        assert result["status"] == "blocked"
        assert fake_gh.resolve_calls == []
        assert lookup_journal(_IDENTITY) is None
        assert _kinds(events) == [("plan", ""), ("result", "blocked")]

    def test_changed_preview_reports_blocked_without_effects(
        self, fake_gh: _FakeGh
    ) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]
        stale_preview = {"intent_fingerprint": "0" * 64}
        result, events = _run(_request(checkout), plan=stale_preview)

        assert result["status"] == "blocked"
        assert "changed since it was reviewed" in result["message"]
        assert fake_gh.resolve_calls == []
        assert lookup_journal(_IDENTITY) is None
        assert _kinds(events) == [("plan", ""), ("result", "blocked")]

    def test_lock_contention_reports_blocked(self, fake_gh: _FakeGh) -> None:
        lock_path = apply_mod._apply_identity_lock_path(_IDENTITY)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            checkout = fake_gh.checkouts[_IDENTITY]
            result, events = _run(_request(checkout), lock_timeout=0.2)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

        assert result["status"] == "blocked"
        assert "another onboarding operation" in result["message"]
        assert fake_gh.resolve_calls == []
        assert _kinds(events) == [("result", "blocked")]


class TestFailureRecovery:
    def test_checkout_failure_is_failed_without_registration(
        self, fake_gh: _FakeGh
    ) -> None:
        fake_gh.fail_resolve = "network is down"
        checkout = fake_gh.checkouts[_IDENTITY]
        result, events = _run(_request(checkout))

        assert result["status"] == "failed"
        assert result["next_argv"] == []
        journal = lookup_journal(_IDENTITY)
        assert journal is not None
        assert journal["status"] == "failed"
        assert journal["stopped_step"] == "checkout"
        assert _kinds(events)[0] == ("plan", "")
        assert _kinds(events)[-2:] == [("step", "failed"), ("result", "failed")]

    def test_manage_failure_is_partial_and_retry_converges(
        self, fake_gh: _FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]

        def _refused(*args: Any, **kwargs: Any) -> Any:
            raise apply_mod.ManagementError("push rejected: protected branch")

        real_manage = apply_mod.manage_repository
        monkeypatch.setattr(apply_mod, "manage_repository", _refused)
        result, _ = _run(_request(checkout))

        assert result["status"] == "partial"
        assert "protected branch" in result["message"]
        assert "re-run the same command" in result["message"]
        assert len(_marker_commits(fake_gh.origin)) == 1

        monkeypatch.setattr(apply_mod, "manage_repository", real_manage)
        retried, _ = _run(_request(checkout))

        assert retried["status"] == "ok"
        assert len(_marker_commits(fake_gh.origin)) == 2
        journal = lookup_journal(_IDENTITY)
        assert journal is not None
        assert journal["status"] == "complete"

    def test_identity_failure_is_partial(
        self, fake_gh: _FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]
        request = _request(checkout)
        request["requested"] = {"setup": "off", "name": "taken"}

        def _boom(project: str, name: str, **kwargs: Any) -> Any:
            raise ValueError("project name 'taken' is already taken")

        monkeypatch.setattr("sase.project_aliases.ensure_project_name_locked", _boom)
        result, _ = _run(request)

        assert result["status"] == "partial"
        assert "already taken" in result["message"]

    def test_current_failure_is_partial(
        self, fake_gh: _FakeGh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]
        request = _request(checkout)
        request["requested"] = {"setup": "off", "make_current": True}
        monkeypatch.setattr(
            "sase.current_project.set_current_project",
            lambda project_key, **kwargs: SimpleNamespace(
                status="ineligible",
                project=None,
                message="test project is disabled; enable it first.",
            ),
        )
        result, _ = _run(request)

        assert result["status"] == "partial"
        assert "disabled" in result["message"]


class TestActualPostconditions:
    def test_changed_allocation_uses_actual_record(self, fake_gh: _FakeGh) -> None:
        fake_gh.allocate_key = "gh_sase-org__bob2"
        checkout = fake_gh.checkouts[_IDENTITY]
        request = _request(checkout)
        request["requested"] = {"setup": "off", "make_current": True}
        result, _ = _run(request)

        assert result["status"] == "ok"
        assert result["project"]["key"] == "gh_sase-org__bob2"
        assert result["next_argv"] == []
        journal = lookup_journal(_IDENTITY)
        assert journal is not None
        assert journal["project_key"] == "gh_sase-org__bob2"

    def test_dirty_matching_clone_is_preserved(self, fake_gh: _FakeGh) -> None:
        checkout = Path(fake_gh.checkouts[_IDENTITY])
        _git(fake_gh.home, "clone", str(fake_gh.origin), str(checkout))
        dirty = checkout / "notes.txt"
        dirty.write_text("local work\n", encoding="utf-8")
        _git(checkout, "add", "notes.txt")
        spec_dir = sase_projects_dir() / _KEY
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / f"{_KEY}.sase").write_text(
            f"WORKSPACE_DIR: {checkout}\nPROJECT_NAME: {_NAME}\n",
            encoding="utf-8",
        )
        request = _request(str(checkout))
        request["requested"] = {"setup": "off"}

        result, _ = _run(request)

        assert result["status"] == "ok"
        assert fake_gh.resolve_calls == []
        assert dirty.read_text(encoding="utf-8") == "local work\n"

    def test_empty_checkout_dir_removed_for_clone(self, fake_gh: _FakeGh) -> None:
        checkout = Path(fake_gh.checkouts[_IDENTITY])
        checkout.mkdir(parents=True)
        request = _request(str(checkout))
        request["requested"] = {"setup": "off"}

        result, _ = _run(request)

        assert result["status"] == "ok"
        assert (checkout / ".git").is_dir()
        assert len(fake_gh.resolve_calls) == 2

    def test_reenable_restores_disabled_record(self, fake_gh: _FakeGh) -> None:
        checkout = Path(fake_gh.checkouts[_IDENTITY])
        _git(fake_gh.home, "clone", str(fake_gh.origin), str(checkout))
        spec_dir = sase_projects_dir() / _KEY
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / f"{_KEY}.sase").write_text(
            f"PROJECT_STATE: disabled\nWORKSPACE_DIR: {checkout}\n"
            f"PROJECT_NAME: {_NAME}\n",
            encoding="utf-8",
        )
        request = _request(str(checkout))
        request["requested"] = {"setup": "off"}

        result, events = _run(request)

        assert result["status"] == "ok"
        assert fake_gh.resolve_calls == []
        assert "reenable" in _step_ids(events)
        content = (spec_dir / f"{_KEY}.sase").read_text(encoding="utf-8")
        assert "disabled" not in content

    def test_simultaneous_submissions_share_one_commit(self, fake_gh: _FakeGh) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]
        request = _request(checkout)
        request["requested"] = {"setup": "auto", "make_current": True}
        barrier = threading.Barrier(2)
        outcomes: list[dict[str, Any]] = []
        errors: list[BaseException] = []

        def submit() -> None:
            try:
                barrier.wait(timeout=30)
                outcomes.append(apply_plan(dict(request), emit=lambda event: None))
            except BaseException as exc:  # noqa: BLE001 - collected by test
                errors.append(exc)

        workers = [threading.Thread(target=submit) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=300)

        assert not errors
        assert sorted(item["status"] for item in outcomes) == ["ok", "ok"]
        assert len(_marker_commits(fake_gh.origin)) == 2

    def test_result_events_are_valid_ndjson(self, fake_gh: _FakeGh) -> None:
        checkout = fake_gh.checkouts[_IDENTITY]
        result, events = _run(_request(checkout))

        assert result["status"] == "ok"
        lines = [json.dumps(item, ensure_ascii=True) for item in events]
        parsed = [parse_event_line(line) for line in lines]
        assert all(item is not None for item in parsed)
        assert parsed[-1] is not None and parsed[-1]["status"] == "ok"
