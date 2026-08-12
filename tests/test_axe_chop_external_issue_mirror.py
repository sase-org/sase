"""End-to-end coverage for the ``external_issue_mirror`` builtin chop."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pluggy
import pytest

from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.bead.project import BeadProject
from sase.chops.builtin import run_builtin_chop
from sase.vcs_provider import VCSHookSpec, VCSPluginManager
from sase.vcs_provider._types import IssueWire
from sase.vcs_provider.testing import FakeIssueProvider


@pytest.fixture(autouse=True)
def _isolate_chop_result_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_CHOP_RESULT_FILE", raising=False)


@pytest.fixture
def bead_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "bead-store"
    with BeadProject.init(root):
        pass
    beads_dir = root / "sdd" / "beads"
    monkeypatch.setattr(
        "sase.external_mirror.issues.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    return beads_dir


def _provider(*plugins: object) -> VCSPluginManager:
    manager = pluggy.PluginManager("sase_vcs")
    manager.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        manager.register(plugin)
    return VCSPluginManager(manager)


def _issue(
    number: int,
    *,
    state: str = "open",
    updated_at: str = "2026-08-10T18:00:00Z",
) -> IssueWire:
    return IssueWire(
        number=number,
        title=f"Issue {number}",
        state=state,  # type: ignore[arg-type]
        url=f"https://example.test/issues/{number}",
        provider_id=f"I_{number}",
        updated_at=updated_at,
        created_at=updated_at,
    )


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: object,
    *,
    listing_supported: bool = True,
) -> None:
    monkeypatch.setattr(
        "sase.external_mirror.issues.get_vcs_provider", lambda _cwd: provider
    )
    monkeypatch.setattr(
        "sase.external_mirror.issues.supports_issue_listing",
        lambda _cwd: listing_supported,
    )


def _run_chop(
    tmp_path: Path,
    *,
    target: dict[str, object] | None,
    dry_run: bool = False,
) -> dict[str, object]:
    importlib.import_module("sase.scripts.sase_chop_external_issue_mirror")
    result_path = tmp_path / "result.json"
    context_path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="checks",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
            result_file=str(result_path),
            dry_run=dry_run,
            target=target,
        ),
        str(context_path),
    )

    run_builtin_chop("external_issue_mirror", ["--context", str(context_path)])
    return json.loads(result_path.read_text(encoding="utf-8"))


def test_mirror_chop_creates_beads_and_reports_counters(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_provider(monkeypatch, _provider(FakeIssueProvider([_issue(1), _issue(2)])))

    result = _run_chop(
        tmp_path,
        target={
            "name": "sase",
            "project": "sase",
            "workspace_dir": "/repo",
        },
    )

    assert result["status"] == "ok"
    assert result["counters"]["issues_seen"] == 2
    assert result["counters"]["beads_created"] == 2
    assert result["counters"]["checkpoint_advanced"] == 1


def test_mirror_chop_closes_mirrored_bead_and_reports_counter(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_provider(monkeypatch, _provider(FakeIssueProvider([_issue(1)])))
    _run_chop(
        tmp_path,
        target={"name": "sase", "project": "sase", "workspace_dir": "/repo"},
    )
    _install_provider(
        monkeypatch,
        _provider(
            FakeIssueProvider(
                [_issue(1, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )

    result = _run_chop(
        tmp_path,
        target={"name": "sase", "project": "sase", "workspace_dir": "/repo"},
    )

    assert result["status"] == "ok"
    assert result["counters"]["beads_closed"] == 1
    assert result["counters"]["notes_appended"] == 1


def test_mirror_chop_fails_closed_without_target_workspace_dir(
    tmp_path: Path,
) -> None:
    result = _run_chop(tmp_path, target={"name": "sase", "project": "sase"})

    assert result["status"] == "check_error"
    assert result["reason"] == "missing_target_workspace"


def test_mirror_chop_check_error_counter_keys_match_ok_summary(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_provider(monkeypatch, _provider(FakeIssueProvider([])))
    ok = _run_chop(
        tmp_path,
        target={"name": "sase", "project": "sase", "workspace_dir": "/repo"},
    )
    check_error = _run_chop(
        tmp_path,
        target={"name": "sase", "project": "sase"},
    )

    assert set(check_error["counters"]) == set(ok["counters"])


def test_mirror_chop_fails_closed_without_target_project(tmp_path: Path) -> None:
    result = _run_chop(tmp_path, target={"name": "sase", "workspace_dir": "/repo"})

    assert result["status"] == "check_error"
    assert result["reason"] == "missing_target_project"


def test_mirror_chop_dry_run_mutates_nothing(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_provider(monkeypatch, _provider(FakeIssueProvider([_issue(1)])))

    result = _run_chop(
        tmp_path,
        target={"name": "sase", "project": "sase", "workspace_dir": "/repo"},
        dry_run=True,
    )

    assert result["status"] == "no_op"
    assert result["reason"] == "dry_run"
    assert result["counters"]["beads_created"] == 0
    with BeadProject(bead_store.parent.parent) as project:
        assert project.list_issues() == []


def test_mirror_chop_declines_unsupported_provider(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_provider(
        monkeypatch,
        _provider(FakeIssueProvider([], capabilities=[])),
        listing_supported=False,
    )

    result = _run_chop(
        tmp_path, target={"name": "sase", "project": "sase", "workspace_dir": "/repo"}
    )

    assert result["status"] == "no_op"
    assert result["reason"] == "unsupported_provider"


def test_mirror_chop_no_changes_reports_no_op(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_provider(monkeypatch, _provider(FakeIssueProvider([])))

    result = _run_chop(
        tmp_path, target={"name": "sase", "project": "sase", "workspace_dir": "/repo"}
    )

    assert result["status"] == "no_op"
    assert result["reason"] == "no_changes"
