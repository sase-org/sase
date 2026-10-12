"""Tests for cache-first discovery feeding core classification."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase import workspace_provider
from sase._repo_inventory_models import RepoRecord
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.macro.vcs_repo_completion import VcsRepoFetchResult
from sase.project_onboarding import discovery
from sase.workspace_provider._hookspec import (
    LocalRepoCandidate,
    LocalRepoCandidates,
    ParsedRepoRef,
    VcsRepoEntry,
    WorkflowMetadata,
)

_GH_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(\.git)?$"
)


def _metadata(*workflow_types: str) -> list[WorkflowMetadata]:
    return [
        WorkflowMetadata(
            workflow_type=workflow_type,
            ref_pattern="",
            display_name=f"{workflow_type}-display",
            pre_allocated_env_prefix="",
        )
        for workflow_type in workflow_types
    ]


def _fake_parse(workflow_type: str, text: str) -> ParsedRepoRef | None:
    """Pure ``owner/name``/URL parsing for the ``gh`` test provider."""

    if workflow_type != "gh":
        return None
    value = text.strip()
    if value.startswith("gh:"):
        value = value[3:]
    match = _GH_URL_RE.match(value)
    if match is not None:
        owner, repo = match.group("owner"), match.group("repo")
    elif re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        owner, repo = value.split("/")
    else:
        return None
    ref = f"{owner}/{repo}"
    return ParsedRepoRef(
        workflow_type="gh",
        ref=ref,
        identity_key=f"github.com/{owner}/{repo}".casefold(),
        display=ref,
        host="github.com",
        owner=owner,
        name=repo,
        project_key_base=f"gh_{owner}__{repo}",
        project_name_base=repo,
        checkout_dir=f"~/projects/github/{owner}/{repo}/",
    )


def _entry(ref: str, **overrides: Any) -> VcsRepoEntry:
    name = ref.split("/")[-1]
    payload: dict[str, Any] = {
        "name": name,
        "ref": ref,
        "description": "",
        "visibility": "public",
    }
    payload.update(overrides)
    return VcsRepoEntry(**payload)


def _ok_result(*refs: str, **kwargs: Any) -> VcsRepoFetchResult:
    return VcsRepoFetchResult(
        status="ok",
        provider_display="GitHub",
        entries=tuple(_entry(ref) for ref in refs),
        **kwargs,
    )


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``$SASE_HOME`` at a fresh directory."""

    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


@pytest.fixture
def gh_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a pure fake ``gh`` provider behind discovery."""

    monkeypatch.setattr(
        workspace_provider,
        "get_all_workflow_metadata",
        lambda: _metadata("gh"),
    )
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", _fake_parse)
    monkeypatch.setattr(
        workspace_provider,
        "get_display_name",
        lambda workflow_type: "GitHub",
    )
    monkeypatch.setattr(
        workspace_provider,
        "list_ref_namespaces",
        lambda workflow_type: SimpleNamespace(
            entries=[
                SimpleNamespace(name="sase-org", kind_label="org", host=""),
            ],
            account="bbugyi200",
        ),
    )
    monkeypatch.setattr(
        workspace_provider,
        "list_local_repo_candidates",
        lambda workflow_type: None,
    )
    monkeypatch.setattr(
        discovery, "load_merged_config", lambda: {"github_orgs": ["sase-org"]}
    )
    monkeypatch.setattr(discovery, "list_project_records", lambda *a, **k: [])
    monkeypatch.setattr(
        discovery, "collect_repo_inventory", lambda **k: SimpleNamespace(records=[])
    )


def _write_origin(checkout: Path, url: str) -> Path:
    git_dir = checkout / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8"
    )
    return checkout


def _project_record(
    key: str,
    *,
    state: str,
    workspace_dir: str | None,
    aliases: list[str] | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=3,
        project_name=key,
        project_dir=f"/tmp/{key}",
        project_file=f"/tmp/{key}/{key}.sase",
        archive_file=None,
        workspace_dir=workspace_dir,
        state=state,
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=aliases or [],
    )


def _group_rows(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    providers = payload["providers"]
    assert len(providers) == 1
    return {group["id"]: group["rows"] for group in providers[0]["groups"]}


class TestSuggestClassification:
    def test_groups_cover_all_five_groups(
        self,
        tmp_path: Path,
        isolated_home: Path,
        gh_provider: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fetch_calls: list[tuple[str, str]] = []

        def fake_fetch(
            workflow_type: str,
            namespace: str,
            *,
            host: str = "",
            config: Any = None,
        ) -> VcsRepoFetchResult:
            fetch_calls.append((workflow_type, namespace))
            return _ok_result(
                "sase-org/sase",
                "sase-org/old",
                "sase-org/new",
                "sase-org/sase--plans",
                "sase-org/forge",
            )

        monkeypatch.setattr(discovery, "fetch_repo_candidates", fake_fetch)
        monkeypatch.setattr(
            workspace_provider,
            "list_local_repo_candidates",
            lambda workflow_type: LocalRepoCandidates(
                entries=(
                    LocalRepoCandidate(
                        parsed=ParsedRepoRef(
                            workflow_type="gh",
                            ref="sase-org/clone",
                            identity_key="github.com/sase-org/clone",
                            display="sase-org/clone",
                            owner="sase-org",
                            name="clone",
                        ),
                        path=str(tmp_path / "clone"),
                    ),
                )
            ),
        )
        sase_checkout = _write_origin(
            tmp_path / "co-sase", "https://github.com/sase-org/sase.git"
        )
        old_checkout = _write_origin(
            tmp_path / "co-old", "https://github.com/sase-org/old.git"
        )
        monkeypatch.setattr(
            discovery,
            "list_project_records",
            lambda *a, **k: [
                _project_record(
                    "gh_sase-org__sase",
                    state="enabled",
                    workspace_dir=str(sase_checkout),
                ),
                _project_record(
                    "oldproj", state="disabled", workspace_dir=str(old_checkout)
                ),
            ],
        )
        sidecar_checkout = _write_origin(
            tmp_path / "co-sidecar", "https://github.com/sase-org/sase--plans.git"
        )
        monkeypatch.setattr(
            discovery,
            "collect_repo_inventory",
            lambda **k: SimpleNamespace(
                records=[
                    RepoRecord(
                        name="sase--plans",
                        kind="sidecar",
                        project="sase",
                        project_key="gh_sase-org__sase",
                        path=str(sidecar_checkout),
                        exists=True,
                        auto_clone=False,
                        description=None,
                        source="test",
                        env_name=None,
                    )
                ]
            ),
        )
        journals = isolated_home / "project_onboarding" / "journals"
        journals.mkdir(parents=True, exist_ok=True)
        (journals / "forge.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "identity_key": "github.com/sase-org/forge",
                    "ref": "sase-org/forge",
                    "display": "sase-org/forge",
                    "status": "running",
                }
            ),
            encoding="utf-8",
        )

        payload = discovery.suggest(
            providers=["gh"], include_hidden=True, owners=["sase-org"]
        )

        assert fetch_calls == [("gh", "sase-org")]
        groups = _group_rows(payload)
        assert set(groups) == {"resume", "local", "suggested", "disabled"}
        assert [row["display"] for row in groups["resume"]] == ["sase-org/forge"]
        assert [row["display"] for row in groups["local"]] == ["sase-org/clone"]
        assert [row["display"] for row in groups["suggested"]] == ["sase-org/new"]
        assert [row["display"] for row in groups["disabled"]] == ["sase-org/old"]
        hidden = {
            row["display"]: row["hidden_reason"]
            for row in payload["providers"][0]["search_only"]
        }
        assert hidden == {
            "sase-org/sase": "enabled_project",
            "sase-org/sase--plans": "sidecar",
        }

    def test_record_key_fallback_parses_gh_identity(
        self, isolated_home: Path, gh_provider: None
    ) -> None:
        del isolated_home, gh_provider

        record = _project_record(
            "gh_sase-org__sase", state="enabled", workspace_dir=None
        )

        assert discovery.record_identity_keys(record) == ["github.com/sase-org/sase"]


class TestDiscoveryCacheBehavior:
    def test_cache_only_uses_peek_without_fetch(
        self, isolated_home: Path, gh_provider: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del isolated_home
        peek_calls: list[tuple[str, str]] = []

        def fake_peek(
            workflow_type: str, namespace: str, *, host: str = "", config: Any = None
        ) -> VcsRepoFetchResult:
            peek_calls.append((workflow_type, namespace))
            return _ok_result(f"{namespace}/cached")

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("live fetch must not run when cache_only")

        monkeypatch.setattr(discovery, "peek_cached_repo_candidates", fake_peek)
        monkeypatch.setattr(discovery, "fetch_repo_candidates", boom)

        inputs = discovery.load_candidate_inputs("gh", cache_only=True)

        assert peek_calls == [("gh", "sase-org"), ("gh", "bbugyi200")]
        assert [entry["ref"] for entry in inputs.remote] == [
            "sase-org/cached",
            "bbugyi200/cached",
        ]

    def test_refresh_bypasses_cache_with_zero_ttl(
        self, isolated_home: Path, gh_provider: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del isolated_home
        seen: list[Any] = []

        def fake_fetch(
            workflow_type: str,
            namespace: str,
            *,
            host: str = "",
            config: Any = None,
        ) -> VcsRepoFetchResult:
            seen.append(config)
            return _ok_result()

        monkeypatch.setattr(discovery, "fetch_repo_candidates", fake_fetch)

        discovery.load_candidate_inputs("gh", refresh=True)

        assert seen and all(config.cache_ttl_seconds == 0 for config in seen)

    def test_failing_owner_keeps_stale_rows(
        self, isolated_home: Path, gh_provider: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del isolated_home

        def fake_fetch(
            workflow_type: str,
            namespace: str,
            *,
            host: str = "",
            config: Any = None,
        ) -> VcsRepoFetchResult:
            if namespace == "sase-org":
                return VcsRepoFetchResult(
                    status="error",
                    error_kind="auth",
                    message="gh auth expired",
                    provider_display="GitHub",
                    entries=(_entry("sase-org/stale"),),
                    stale=True,
                    remedy_argv=("gh", "auth", "login"),
                )
            return _ok_result("bbugyi200/mine")

        monkeypatch.setattr(discovery, "fetch_repo_candidates", fake_fetch)

        payload = discovery.suggest(providers=["gh"])

        owners = {o["name"]: o for o in payload["providers"][0]["owners"]}
        assert owners["sase-org"]["status"] == "error"
        assert owners["sase-org"]["remedy_argv"] == ["gh", "auth", "login"]
        groups = _group_rows(payload)
        displays = [row["display"] for rows in groups.values() for row in rows]
        assert "sase-org/stale" in displays

    def test_owner_filter_restricts_namespaces(
        self, isolated_home: Path, gh_provider: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del isolated_home
        fetched: list[str] = []

        def fake_fetch(
            workflow_type: str,
            namespace: str,
            *,
            host: str = "",
            config: Any = None,
        ) -> VcsRepoFetchResult:
            fetched.append(namespace)
            return _ok_result()

        monkeypatch.setattr(discovery, "fetch_repo_candidates", fake_fetch)

        inputs = discovery.load_candidate_inputs("gh", namespaces=["sase-org"])

        assert fetched == ["sase-org"]
        assert [owner.name for owner in inputs.owners] == ["sase-org"]

    def test_account_included_as_namespace_when_absent(
        self, isolated_home: Path, gh_provider: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del isolated_home
        monkeypatch.setattr(
            workspace_provider,
            "list_ref_namespaces",
            lambda workflow_type: SimpleNamespace(entries=[], account="solo"),
        )
        monkeypatch.setattr(
            discovery,
            "fetch_repo_candidates",
            lambda *a, **k: _ok_result(),
        )

        inputs = discovery.load_candidate_inputs("gh")

        assert [(o.name, o.kind_label) for o in inputs.owners] == [("solo", "you")]

    def test_cache_only_spawns_no_subprocess(
        self, isolated_home: Path, gh_provider: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del isolated_home

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("subprocess must not spawn when cache_only")

        monkeypatch.setattr(subprocess, "run", boom)
        monkeypatch.setattr(subprocess, "Popen", boom)
        monkeypatch.setattr(
            discovery,
            "peek_cached_repo_candidates",
            lambda *a, **k: _ok_result(),
        )

        payload = discovery.suggest(providers=["gh"], cache_only=True)

        assert payload["schema_version"] == 1
        assert len(payload["providers"]) == 1

    def test_golden_json_shape(
        self, isolated_home: Path, gh_provider: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del isolated_home
        monkeypatch.setattr(
            discovery,
            "fetch_repo_candidates",
            lambda *a, **k: _ok_result("sase-org/new"),
        )

        payload = discovery.suggest(
            providers=["gh"], include_hidden=True, owners=["sase-org"]
        )

        assert payload["schema_version"] == 1
        (provider,) = payload["providers"]
        assert provider["workflow_type"] == "gh"
        assert provider["display"] == "GitHub"
        assert provider["account"] == "bbugyi200"
        (owner,) = provider["owners"]
        assert owner["name"] == "sase-org"
        assert owner["entry_count"] == 1
        assert owner["remedy_argv"] == []
        assert {group["id"] for group in provider["groups"]} == {"suggested"}
        assert provider["hidden"] == []
        assert provider["search_only"] == []
        json.dumps(payload)
