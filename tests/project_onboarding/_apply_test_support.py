"""Shared fixtures and helpers for project onboarding apply tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase import workspace_provider
from sase.core.paths import sase_projects_dir
from sase.project_onboarding.apply import apply_plan
from sase.workspace_provider._hookspec import (
    ParsedRepoRef,
    RepoCreateResult,
    RepoCreationChoice,
    RepoCreationField,
    RepoCreationForm,
    RepoProbe,
    ResolvedRef,
    WorkflowMetadata,
)

_OWNER = "sase-org"
NAME = "bob"
IDENTITY = "github.com/sase-org/bob"
REF = "sase-org/bob"
KEY = "gh_sase-org__bob"


def git(path: Path, *args: str) -> None:
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


class FakeGh:
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
        self.create_calls: list[tuple[str, str, dict[str, str]]] = []
        self.create_status = "created"
        self.create_raise = ""
        self.create_repo_id = "R1"
        self.is_empty: bool | None = None

    def seed(self) -> None:
        self.origin.mkdir(parents=True, exist_ok=True)
        git(self.home, "init", "--bare", "--initial-branch=main", str(self.origin))
        seed = self.home / "seed"
        seed.mkdir()
        git(seed, "init", "--initial-branch=main")
        config = seed / "sase" / "sase.yml"
        config.parent.mkdir()
        config.write_text("# project settings\nname: bob\n", encoding="utf-8")
        git(seed, "add", "sase/sase.yml")
        git(seed, "commit", "-m", "initial project config")
        git(seed, "remote", "add", "origin", str(self.origin))
        git(seed, "push", "-u", "origin", "main")

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
            return self._for_repo(_OWNER, NAME)
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
            is_empty=self.is_empty,
        )

    def describe(self, workflow_type: str, namespace: str) -> RepoCreationForm:
        return RepoCreationForm(
            workflow_type=workflow_type,
            namespace=namespace,
            fields=(
                RepoCreationField(
                    name="visibility",
                    label="Visibility",
                    kind="choice",
                    default="private",
                    choices=(
                        RepoCreationChoice(value="public", label="Public"),
                        RepoCreationChoice(value="private", label="Private"),
                    ),
                ),
                RepoCreationField(name="description", label="Description", kind="line"),
            ),
            can_create=True,
        )

    def create(
        self, workflow_type: str, ref: str, options: dict[str, str]
    ) -> RepoCreateResult:
        self.create_calls.append((workflow_type, ref, dict(options)))
        parsed = self.parse(workflow_type, ref)
        assert parsed is not None
        if self.create_raise:
            self.probe_status = "found"
            raise RuntimeError(self.create_raise)
        if self.create_status in {"created", "exists"}:
            self.probe_status = "found"
        return RepoCreateResult(
            status=self.create_status,  # type: ignore[arg-type]
            parsed=parsed,
            repo_id=self.create_repo_id,
            visibility="private",
            message="already exists" if self.create_status == "exists" else "",
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
            git(self.home, "clone", str(self.origin), str(checkout))
            git(checkout, "config", "user.name", "Onboarding Test")
            git(checkout, "config", "user.email", "onboarding@example.test")
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
def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    fake = FakeGh(home)
    fake.seed()
    fake.checkout_for(IDENTITY, tmp_path, "checkout")
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
    monkeypatch.setattr(workspace_provider, "create_repo", fake.create)
    monkeypatch.setattr(workspace_provider, "describe_repo_creation", fake.describe)
    return fake


def request(checkout: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": "add",
        "actor": "human",
        "target": {
            "workflow_type": "gh",
            "identity_key": IDENTITY,
            "ref": REF,
            "display": REF,
            "checkout_dir": checkout,
            "project_key_base": KEY,
            "project_name_base": NAME,
            "storage_policy": "separate_repo",
            "web_url": "https://github.com/sase-org/bob",
            "provider_display": "GitHub",
        },
        "requested": {"setup": "auto", "make_current": False},
    }
    payload.update(overrides)
    return payload


def run(request: dict[str, Any], **kwargs: Any) -> tuple[dict, list[dict]]:
    events: list[dict[str, Any]] = []
    result = apply_plan(request, emit=events.append, **kwargs)
    return result, events


def kinds(events: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(str(item.get("event")), str(item.get("status") or "")) for item in events]


def step_ids(events: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id")) for item in events if item.get("event") == "step"]


def marker_commits(bare: Path) -> list[str]:
    out = subprocess.run(
        ["git", "--git-dir", str(bare), "log", "--format=%H %s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]
