"""Tests for versioned onboarding plan documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase import workspace_provider
from sase.project_onboarding import planning as planning_mod
from sase.project_onboarding.journal import (
    journal_path,
    lookup_journal,
    record_intent,
)
from sase.project_onboarding.planning import build_plan_document
from sase.workspace_provider._hookspec import ParsedRepoRef, RepoProbe, WorkflowMetadata


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


def _parsed(ref: str = "sase-org/bob") -> ParsedRepoRef:
    owner, name = ref.split("/")
    return ParsedRepoRef(
        workflow_type="gh",
        ref=ref,
        identity_key=f"github.com/{owner}/{name}".casefold(),
        display=ref,
        host="github.com",
        owner=owner,
        name=name,
        project_key_base=f"gh_{owner}__{name}",
        project_name_base=name,
        checkout_dir=f"/tmp/{name}",
        web_url=f"https://github.com/{ref}",
    )


def _probe(**overrides: Any) -> RepoProbe:
    payload: dict[str, Any] = {
        "status": "found",
        "parsed": _parsed(),
        "visibility": "private",
        "default_branch": "main",
        "can_push": True,
        "sase_managed": False,
        "web_url": "https://github.com/sase-org/bob",
        "repo_id": "R1",
    }
    payload.update(overrides)
    return RepoProbe(**payload)


def _target(checkout_dir: str = "/tmp/bob", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow_type": "gh",
        "identity_key": "github.com/sase-org/bob",
        "ref": "sase-org/bob",
        "display": "sase-org/bob",
        "checkout_dir": checkout_dir,
        "project_key_base": "gh_sase-org__bob",
        "project_name_base": "bob",
        "storage_policy": "separate_repo",
        "web_url": "https://github.com/sase-org/bob",
        "provider_display": "GitHub",
    }
    payload.update(overrides)
    return payload


def _request(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": "add",
        "actor": "human",
        "target": _target(),
        "requested": {"setup": "auto", "make_current": False},
    }
    payload.update(overrides)
    return payload


def _facts(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "remote": {
            "status": "found",
            "visibility": "private",
            "can_push": True,
            "sase_managed": False,
            "repo_id": "R1",
            "default_branch": "main",
            "web_url": "https://github.com/sase-org/bob",
        },
        "checkout": {"state": "absent"},
    }
    payload.update(overrides)
    return payload


def _step(document: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in document["steps"]:
        if step["id"] == step_id:
            return step
    raise AssertionError(f"missing step {step_id}")


def _codes(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("code") or "") for item in items]


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


@pytest.fixture
def gh_provider(monkeypatch: pytest.MonkeyPatch) -> list[RepoProbe]:
    probes: list[RepoProbe] = [_probe()]

    def parse(workflow_type: str, text: str) -> ParsedRepoRef | None:
        if workflow_type != "gh":
            return None
        value = text.strip()
        if "github.com/" in value:
            value = value.rstrip("/").split("github.com/")[-1].removesuffix(".git")
        if value.startswith("gh:"):
            value = value[3:]
        if "/" not in value:
            return None
        return _parsed(value)

    monkeypatch.setattr(workspace_provider, "get_all_workflow_metadata", _metadata)
    monkeypatch.setattr(workspace_provider, "parse_repo_ref", parse)
    monkeypatch.setattr(
        workspace_provider, "probe_repo", lambda workflow_type, ref: probes[0]
    )
    monkeypatch.setattr(
        workspace_provider, "get_display_name", lambda workflow_type: "GitHub"
    )
    return probes


class TestBuildPlanDocument:
    def test_fresh_gh_add_is_ready_with_init_handoff(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(_request(), facts=_facts())
        assert document["schema_version"] == 1
        assert document["kind"] == "project_onboarding_plan"
        assert document["mode"] == "add"
        assert document["status"] == "ready"
        assert len(document["intent_fingerprint"]) == 64
        assert document["provider"] == {"workflow_type": "gh", "display": "GitHub"}
        assert document["project"]["key"] == "gh_sase-org__bob"
        assert document["project"]["existing"] is False
        assert document["project"]["state"] == "enabled"
        assert document["setup"]["code"] == "unmanaged_can_push"
        assert _step(document, "checkout")["state"] == "pending"
        assert _step(document, "init")["state"] == "pending"
        assert document["next_argv"] == ["sase", "init", "-p", "gh_sase-org__bob"]
        assert document["apply_argv"][:3] == ["sase", "project", "add"]
        assert document["apply_argv"][-2:] == ["--yes", "--json"]
        assert "--check" not in document["apply_argv"]
        assert "--setup" not in document["apply_argv"]
        assert "--no-setup" not in document["apply_argv"]

    def test_omitted_setup_matches_explicit_auto_fingerprint(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        omitted = build_plan_document(
            _request(requested={"make_current": False}), facts=_facts()
        )
        explicit = build_plan_document(
            _request(requested={"setup": "auto", "make_current": False}),
            facts=_facts(),
        )
        assert omitted["intent_fingerprint"] == explicit["intent_fingerprint"]
        assert "--setup" not in omitted["apply_argv"]
        assert "--no-setup" not in omitted["apply_argv"]

    def test_matching_clone_without_record_registers(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(
            _request(), facts=_facts(checkout={"state": "matching"})
        )
        assert document["status"] == "ready"
        checkout = _step(document, "checkout")
        assert checkout["state"] == "pending"
        assert checkout["operation"] == "update"

    def test_already_registered_managed_is_current(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(
            _request(),
            facts=_facts(
                checkout={"state": "matching"},
                record={
                    "key": "gh_sase-org__bob",
                    "name": "bob",
                    "aliases": [],
                    "state": "enabled",
                },
                remote={
                    "status": "found",
                    "visibility": "private",
                    "can_push": True,
                    "sase_managed": True,
                    "repo_id": "R1",
                    "default_branch": "main",
                    "web_url": "https://github.com/sase-org/bob",
                },
            ),
        )
        assert document["status"] == "current"
        assert document["project"]["existing"] is True
        assert _step(document, "checkout")["state"] == "done"
        assert _step(document, "init")["state"] == "skipped"
        assert document["next_argv"] == []

    def test_disabled_record_reenable_is_pending(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(
            _request(),
            facts=_facts(
                checkout={"state": "matching"},
                record={
                    "key": "gh_sase-org__bob",
                    "name": "bob",
                    "aliases": [],
                    "state": "disabled",
                },
            ),
        )
        assert document["project"]["state"] == "disabled"
        assert document["project"]["existing"] is True
        assert _step(document, "reenable")["state"] == "pending"
        assert document["status"] == "ready"

    def test_checkout_conflict_is_blocked(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(
            _request(), facts=_facts(checkout={"state": "mismatch"})
        )
        assert document["status"] == "blocked"
        assert "checkout_conflict" in _codes(document["blockers"])

    def test_no_push_rights_warns_and_skips_setup(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(
            _request(),
            facts=_facts(
                remote={
                    "status": "found",
                    "visibility": "private",
                    "can_push": False,
                    "sase_managed": False,
                    "repo_id": "R1",
                    "default_branch": "main",
                    "web_url": "https://github.com/sase-org/bob",
                }
            ),
        )
        assert document["setup"]["code"] == "no_push"
        assert document["setup"]["enabled"] is False
        assert "not_launchable" in _codes(document["warnings"])
        assert _step(document, "manage")["state"] == "skipped"
        assert document["next_argv"] == []

    def test_agent_auto_setup_is_off_without_human_only(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(_request(actor="agent"), facts=_facts())
        assert document["setup"]["code"] == "agent"
        assert document["setup"]["enabled"] is False
        assert "human_only" not in _codes(document["blockers"])
        assert _step(document, "init")["state"] == "skipped"
        assert document["next_argv"] == []

    def test_agent_explicit_setup_is_human_only(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(
            _request(actor="agent", requested={"setup": "on"}),
            facts=_facts(),
        )
        assert document["status"] == "blocked"
        assert "human_only" in _codes(document["blockers"])
        assert "--setup" in document["apply_argv"]

    def test_apply_argv_includes_requested_options(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        document = build_plan_document(
            _request(
                requested={
                    "setup": "off",
                    "make_current": True,
                    "name": "bob",
                    "aliases": ["demo"],
                }
            ),
            facts=_facts(),
        )
        argv = document["apply_argv"]
        assert argv[0:4] == ["sase", "project", "add", "sase-org/bob"]
        assert argv[argv.index("--alias") + 1] == "demo"
        assert "--make-current" in argv
        assert argv[argv.index("--name") + 1] == "bob"
        assert "--no-setup" in argv
        assert argv[-2:] == ["--yes", "--json"]
        assert "--check" not in argv
        assert "--request-path" not in argv
        assert "--result-path" not in argv

    def test_matching_journal_attaches_after_fingerprint(
        self,
        isolated_home: Path,
        gh_provider: list[RepoProbe],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        del isolated_home, gh_provider
        calls: list[dict[str, Any]] = []
        real = planning_mod.plan_project_onboarding

        def wrapped(request: Any, facts: Any) -> dict[str, Any]:
            calls.append(dict(facts))
            return real(request, facts)

        monkeypatch.setattr(planning_mod, "plan_project_onboarding", wrapped)
        first = build_plan_document(_request(), facts=_facts())
        fingerprint = first["intent_fingerprint"]
        record_intent(
            identity_key="github.com/sase-org/bob",
            ref="sase-org/bob",
            display="sase-org/bob",
            workflow_type="gh",
            mode="add",
            intent_fingerprint=fingerprint,
        )
        calls.clear()
        build_plan_document(_request(), facts=_facts())
        assert "journal" not in calls[0]
        assert calls[1]["journal"]["remote_created"] is False

        record_intent(
            identity_key="github.com/sase-org/bob",
            ref="sase-org/bob",
            display="sase-org/bob",
            workflow_type="gh",
            mode="add",
            intent_fingerprint="deadbeef" * 8,
        )
        calls.clear()
        build_plan_document(_request(), facts=_facts())
        assert len(calls) == 1
        assert "journal" not in calls[0]

    def test_create_journal_adopts_matching_remote(
        self, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home, gh_provider
        request = _request(
            mode="create",
            creation={"visibility": "private", "summary": []},
        )
        found = _facts(
            remote={
                "status": "found",
                "visibility": "private",
                "can_push": True,
                "sase_managed": False,
                "repo_id": "R1",
                "default_branch": "main",
                "is_empty": False,
                "web_url": "https://github.com/sase-org/bob",
            },
            can_create=True,
        )
        blocked = build_plan_document(request, facts=found)
        assert blocked["status"] == "blocked"
        assert "remote_exists" in _codes(blocked["blockers"])
        record_intent(
            identity_key="github.com/sase-org/bob",
            ref="sase-org/bob",
            display="sase-org/bob",
            workflow_type="gh",
            mode="create",
            intent_fingerprint=blocked["intent_fingerprint"],
        )
        path = journal_path("github.com/sase-org/bob", "sase-org/bob")
        stored = lookup_journal("github.com/sase-org/bob")
        assert stored is not None
        stored["remote"] = {"created": True, "repo_id": "R1", "created_at": ""}
        path.write_text(json.dumps(stored, indent=2, sort_keys=True), encoding="utf-8")
        adopted = build_plan_document(request, facts=found)
        assert _step(adopted, "create_remote")["state"] == "done"
        assert "remote_exists" not in _codes(adopted["blockers"])

    def test_preview_does_not_write(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        checkout = tmp_path / "bob"
        document = build_plan_document(
            _request(target=_target(checkout_dir=str(checkout)))
        )
        assert document["status"] == "ready"
        assert checkout.exists() is False
        assert (isolated_home / "project_onboarding").exists() is False

    def test_supplied_facts_skip_probe(
        self, tmp_path: Path, isolated_home: Path, gh_provider: list[RepoProbe]
    ) -> None:
        del isolated_home
        checkout = tmp_path / "bob"
        gh_provider[0] = _probe(status="unavailable", message="should not probe")
        document = build_plan_document(
            _request(target=_target(checkout_dir=str(checkout))),
            facts=_facts(),
        )
        assert document["target"]["can_push"] is True
        assert checkout.exists() is False
