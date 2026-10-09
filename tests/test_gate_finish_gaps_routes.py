"""Gate finish gaps: grants, host checks, callers, reuse, writers, guard, receipt.

Covers plan section 3 items 4, 5, 6, 7, 8, 10, and 11: the new-strand grant
through the resolver, ``decision-host-check-failed`` on both handlers,
bead-work caller classification and reuse edges, the handoff writer side,
the memory guard through its public entry, and the quiet receipt on the
real ACE direct page.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ORDERED_EPIC = """---
tier: epic
title: Epic order
goal: Ship it in order.
phases:
  - id: implementation
    title: Implement
    depends_on: []
    description: "implementation: build it."
    size: small
decisions:
  zeta:
    ask: Pick zeta value?
    choices:
      b: Second choice
      a: First choice
    default: b
    why: zeta why
  alpha:
    ask: Turn alpha on?
    default: false
---
# Plan

> [!decision] zeta = b Zeta b branch.
> [!decision] alpha Alpha yes branch.
"""

MEMORY_EPIC = """---
tier: epic
title: Epic memory
goal: Ship it.
phases:
  - id: implementation
    title: Implement
    depends_on: []
    description: "implementation: build it."
    size: small
decisions:
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "and note the convention in the tui memory"
    default: true
    answer: true
decided_by: reviewer
decided_via: cli
---
# Plan

Body mentions tui_note.
"""

VALID_DECISIONS_TALE = """---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane, matching the footer hints
      mode: By leader mode; denser, but splits pane actions
    default: pane
    why: pane keeps the footer's order
---
# Plan

> [!decision] grouping = pane Order by pane.
"""


def _needs_core(*names: str) -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    for name in names:
        if not hasattr(core, name):
            pytest.skip(f"stale core without {name}")


def test_new_strand_grant_through_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _needs_core("plan_decisions_payload")
    from sase.sdd._plan_decisions_shared import (
        PlanDecisionError,
        resolve_memory_records,
    )

    monkeypatch.chdir(tmp_path)
    (tmp_path / "sase" / "memory").mkdir(parents=True)
    (tmp_path / "sase" / "memory" / "glossary.md").write_text(
        "---\nweb: true\n---\n\n# Glossary\n", encoding="utf-8"
    )

    records, keys = resolve_memory_records(["glossary:plan-decision"])

    assert records == [
        {
            "selector": "glossary:plan-decision",
            "kind": "strand",
            "scope": "project",
            "path": "sase/memory/glossary/plan-decision.md",
            "type": "strand",
            "exists": False,
        }
    ]
    assert keys == {"strand:project:sase/memory/glossary/plan-decision.md"}
    # An unknown web still refuses the grant.
    with pytest.raises(PlanDecisionError):
        resolve_memory_records(["no-such-web-xyz:missing-strand"])


def test_host_check_failed_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.main.plan_validate_handler import _apply_decision_host_checks
    from sase.sdd.plan_validate import validate_plan

    monkeypatch.setenv("SASE_AGENT", "1")
    validation = validate_plan(VALID_DECISIONS_TALE, "tale", mode="launch")
    assert validation.ok and validation.plan is not None

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("host check boom")

    monkeypatch.setattr("sase.sdd.plan_decisions.validate_host_checks", _boom)
    failed = _apply_decision_host_checks(
        VALID_DECISIONS_TALE, validation, "plan.md", "tale"
    )

    assert not failed.ok
    assert failed.plan is None
    codes = [str(item.code) for item in failed.diagnostics]
    assert "decision-host-check-failed" in codes


def test_host_check_failed_propose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from sase.main.plan_propose_handler import handle_plan_propose_command

    monkeypatch.setenv("SASE_AGENT", "test-agent")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    plan = tmp_path / "propose.md"
    plan.write_text(VALID_DECISIONS_TALE, encoding="utf-8")

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("host check boom")

    monkeypatch.setattr("sase.sdd.plan_decisions.validate_host_checks", _boom)
    with pytest.raises(SystemExit) as exitinfo:
        handle_plan_propose_command(str(plan))

    assert int(exitinfo.value.code or 0) != 0
    captured = capsys.readouterr()
    assert "decision-host-check-failed" in captured.out + captured.err


@pytest.mark.parametrize(
    ("env", "expected_by"),
    [({}, "reviewer"), ({"SASE_AGENT": "1"}, "agent")],
)
def test_bead_work_caller_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: dict, expected_by: str
) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    from sase.bead import cli_work_from_plan as bead_module
    from sase.sdd.plan_validate import validate_plan_file

    for name in ("SASE_AGENT", "SASE_AGENT_NAME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if not env:
        monkeypatch.setattr("sase.agent.identity.discover_agent_identity", lambda: None)
    plan = tmp_path / "caller.md"
    plan.write_text(ORDERED_EPIC, encoding="utf-8")
    validation = validate_plan_file(plan, "epic", mode="launch")
    assert validation.ok

    bead_module._stamp_bead_work_decisions(plan, validation, dry_run=False)

    from sase.sdd.frontmatter import parse_frontmatter

    frontmatter, _, _ = parse_frontmatter(plan.read_text(encoding="utf-8"))
    assert frontmatter["decided_by"] == expected_by
    assert frontmatter["decided_via"] == "cli"


def test_bead_reuse_agent_caller_on_reviewer_memory_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead import cli_work_from_plan as bead_module
    from sase.sdd.frontmatter import parse_frontmatter
    from sase.sdd.plan_validate import validate_plan_file

    monkeypatch.setenv("SASE_AGENT", "1")
    for name in ("SASE_ARTIFACTS_DIR",):
        monkeypatch.delenv(name, raising=False)
    plan = tmp_path / "reuse-memory.md"
    plan.write_text(MEMORY_EPIC, encoding="utf-8")
    frontmatter, _, had = parse_frontmatter(plan.read_text(encoding="utf-8"))
    assert had
    validation = validate_plan_file(plan, "epic", mode="launch")
    assert validation.ok

    def _fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("resolver must not run for accepted plans")

    monkeypatch.setattr(
        "sase.sdd.plan_decisions.resolve_plan_decisions_for_direct_approval", _fail
    )
    monkeypatch.setattr("sase.sdd.plan_decisions.build_definitions", _fail)
    # An agent caller reuses the reviewer-accepted memory-yes answers.
    bead_module._stamp_bead_work_decisions(plan, validation, dry_run=False)


def test_bead_fresh_stamp_surfaces_resolver_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead import cli_work_from_plan as bead_module
    from sase.bead.cli_work_from_plan_types import PlanFileWorkError
    from sase.sdd.plan_validate import validate_plan_file

    plan = tmp_path / "fresh-errors.md"
    plan.write_text(ORDERED_EPIC, encoding="utf-8")
    validation = validate_plan_file(plan, "epic", mode="launch")
    assert validation.ok
    monkeypatch.setattr(
        "sase.sdd.plan_decisions.resolve_plan_decisions_for_direct_approval",
        lambda *args, **kwargs: {"errors": [{"code": "boom", "message": "nope"}]},
    )
    with pytest.raises(PlanFileWorkError, match="failed to resolve"):
        bead_module._stamp_bead_work_decisions(plan, validation, dry_run=False)


def test_bead_reuse_writes_no_sibling_from_reader_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead import cli_work_from_plan as bead_module
    from sase.sdd.frontmatter import parse_frontmatter
    from sase.sdd.plan_decision_freeze import sibling_path_for_plan
    from sase.sdd.plan_validate import validate_plan_file

    for name in ("SASE_AGENT", "SASE_AGENT_NAME", "SASE_ARTIFACTS_DIR"):
        monkeypatch.delenv(name, raising=False)
    plan = tmp_path / "reuse-clean.md"
    plan.write_text(MEMORY_EPIC, encoding="utf-8")
    frontmatter, _, had = parse_frontmatter(plan.read_text(encoding="utf-8"))
    assert had
    validation = validate_plan_file(plan, "epic", mode="launch")
    assert validation.ok

    monkeypatch.chdir("/tmp")
    bead_module._reuse_stamped_bead_work_answers(plan, frontmatter, validation)

    assert not sibling_path_for_plan(plan).exists()


def test_freeze_writes_bundle_sibling(tmp_path: Path) -> None:
    import json as _json

    from sase.sdd.plan_decision_freeze import (
        read_frozen_definitions,
        sibling_path_for_plan,
        write_frozen_definitions_if_missing,
    )

    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    definitions = [{"id": "zeta", "kind": "choice"}]

    assert write_frozen_definitions_if_missing(plan, definitions) is True
    sibling = sibling_path_for_plan(plan)
    assert sibling.is_file()
    payload = _json.loads(sibling.read_text(encoding="utf-8"))
    assert payload["definitions"] == definitions
    assert read_frozen_definitions(plan) == definitions


def test_freeze_never_overwrites_existing_sibling(tmp_path: Path) -> None:
    from sase.sdd.plan_decision_freeze import (
        sibling_path_for_plan,
        write_frozen_definitions_if_missing,
    )

    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    sibling = sibling_path_for_plan(plan)
    sentinel = '{"schema": 1, "definitions": [{"id": "kept"}]}\n'
    sibling.write_text(sentinel, encoding="utf-8")

    assert write_frozen_definitions_if_missing(plan, [{"id": "zeta"}]) is False
    assert sibling.read_text(encoding="utf-8") == sentinel
    assert write_frozen_definitions_if_missing(plan, None) is False
    assert write_frozen_definitions_if_missing(plan, []) is False


def test_archive_copies_plan_and_commits_sibling(tmp_path: Path) -> None:
    from sase._plan_archive_approval import (
        _ApprovedPlanArchive,
        _archive_commit_paths,
        archive_approved_plan,
    )
    from sase.sdd.plan_decision_freeze import sibling_path_for_plan
    from tests.workspace_lease_helpers import (
        patched_operational_lease as _patched_operational_lease,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    bundle_plan = tmp_path / "bundle" / "plan.md"
    bundle_plan.parent.mkdir()
    bundle_plan.write_text(VALID_DECISIONS_TALE, encoding="utf-8")
    # Store materialization needs a managed repo; stub the store so the
    # real copy-and-commit logic runs. The repo must sit inside the leased
    # checkout, so it lives under the workspace.
    store_root = workspace / "store"
    plans_root = store_root / "plans"
    (plans_root / "202608").mkdir(parents=True)
    sibling = sibling_path_for_plan(plans_root / "202608" / "plan.md")
    sibling.write_text('{"schema": 1, "definitions": []}\n', encoding="utf-8")
    store = SimpleNamespace(
        is_in_tree=False,
        repo_root=store_root,
        sdd_dir=store_root,
        kind_root=lambda kind: plans_root,
    )

    commits: list = []

    def _spy(*args: object, **kwargs: object) -> object:
        commits.append((args, kwargs))
        from types import SimpleNamespace as _NS

        return _NS(push=None)

    with (
        _patched_operational_lease(workspace),
        patch("sase.sdd.store.materialize_sdd_store", return_value=store),
        patch("sase.sdd.files.get_yyyymm", return_value="202608"),
        patch(
            "sase.file_references.format_with_prettier",
            side_effect=lambda content: content,
        ),
        patch("sase.sdd.files.commit_sdd_store_files", _spy),
    ):
        saved = archive_approved_plan(
            {"project_dir": str(workspace)},
            bundle_plan,
            tier="tale",
            push_after_commit=False,
        )

    assert isinstance(saved, _ApprovedPlanArchive)
    expected = Path(str(saved))
    assert expected.is_file()
    # The archive adds header bookkeeping, so compare the plan content.
    from sase.sdd.frontmatter import parse_frontmatter

    saved_front, saved_body, _ = parse_frontmatter(expected.read_text(encoding="utf-8"))
    src_front, src_body, _ = parse_frontmatter(bundle_plan.read_text(encoding="utf-8"))
    assert saved_front["decisions"] == src_front["decisions"]
    assert saved_body == src_body
    # The archive commit covers the copy plus its frozen-decisions sibling.
    assert len(commits) == 1
    assert commits[0][1]["paths"] == [expected, sibling]
    assert _archive_commit_paths(expected) == [expected, sibling]


def _guard_markers() -> tuple[list[dict], list[dict]]:
    before = [
        {
            "cwd": "/repo",
            "result": "x",
            "commit_sha": "a",
            "commit_tree": "t",
            "entry_id": "e",
        }
    ]
    after = [
        *before,
        {
            "cwd": "/repo",
            "result": "y",
            "commit_sha": "b",
            "commit_tree": "t2",
            "entry_id": "e2",
        },
    ]
    return before, after


def _guard_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sheet: dict
) -> str:
    import sase.sdd.plan_decision_handoff as handoff

    monkeypatch.delenv("SASE_PLAN", raising=False)
    monkeypatch.chdir("/tmp")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# plan\n", encoding="utf-8")
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"sdd_plan_path": str(plan_file)}), encoding="utf-8"
    )
    monkeypatch.setattr(
        handoff,
        "load_stamped_decisions",
        lambda _path, _tier=None: SimpleNamespace(
            sheet=sheet, title="Demo", decided_by="reviewer", decided_via="tui"
        ),
    )
    monkeypatch.setattr(handoff, "epic_decision_context", lambda _dir: None)
    return str(artifacts)


def test_guard_public_entry_covers_note_from_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_memory_guard as guard
    from sase.finalizers.commit_memory_guard import memory_guard_for_new_markers

    sheet = {
        "rows": [
            {
                "id": "tui_note",
                "kind": "toggle",
                "value": True,
                "memory": {
                    "selectors": ["tui.md"],
                    "resolved": [
                        {
                            "selector": "tui.md",
                            "kind": "note",
                            "scope": "project",
                            "path": "sase/memory/tui.md",
                            "type": "reference",
                            "exists": True,
                        }
                    ],
                    "provenance": "asked",
                },
            }
        ]
    }
    artifacts = _guard_artifacts(tmp_path, monkeypatch, sheet)
    before, after = _guard_markers()
    monkeypatch.setattr(
        guard,
        "_git_diff_tree_files",
        lambda _cwd, _sha: ["sase/memory/tui.md"],
    )
    assert memory_guard_for_new_markers(artifacts, before, after) == []


def test_guard_public_entry_covers_granted_strand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_memory_guard as guard
    from sase.finalizers.commit_memory_guard import memory_guard_for_new_markers

    sheet = {
        "rows": [
            {
                "id": "glossary_note",
                "kind": "toggle",
                "value": True,
                "memory": {
                    "selectors": ["glossary:plan-decision"],
                    "resolved": [
                        {
                            "selector": "glossary:plan-decision",
                            "kind": "strand",
                            "scope": "project",
                            "path": "sase/memory/glossary/plan-decision.md",
                            "type": "strand",
                            "exists": False,
                        }
                    ],
                    "provenance": "asked",
                },
            }
        ]
    }
    artifacts = _guard_artifacts(tmp_path, monkeypatch, sheet)
    before, after = _guard_markers()
    monkeypatch.setattr(
        guard,
        "_git_diff_tree_files",
        lambda _cwd, _sha: ["sase/memory/glossary/plan-decision.md"],
    )
    assert memory_guard_for_new_markers(artifacts, before, after) == []


def test_guard_public_entry_nested_agents_md_stays_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_memory_guard as guard
    from sase.finalizers.commit_memory_guard import memory_guard_for_new_markers

    artifacts = _guard_artifacts(tmp_path, monkeypatch, {"rows": []})
    before, after = _guard_markers()
    monkeypatch.setattr(
        guard,
        "_git_diff_tree_files",
        lambda _cwd, _sha: ["src/sase/ace/AGENTS.md"],
    )
    assert memory_guard_for_new_markers(artifacts, before, after) == []


def test_quiet_receipt_visible_on_direct_page_but_skips_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui.actions.agents._notification_provider_direct import (
        direct_unread_notification_page,
    )
    from sase.ace.tui.actions.agents._notification_matching import (
        unread_notification_buckets,
    )
    from sase.ace.tui.actions.lifecycle import LifecycleMixin
    from sase.notifications import read_notification_snapshot
    from sase.notifications import store as store_mod
    from sase.sdd.plan_decision_handoff import post_auto_approval_receipt

    notifications_dir = tmp_path / "notifications"
    monkeypatch.setattr(store_mod, "NOTIFICATIONS_DIR", str(notifications_dir))
    monkeypatch.setattr(
        store_mod, "NOTIFICATIONS_FILE", str(notifications_dir / "notifications.jsonl")
    )
    store_mod._LOAD_CACHE.clear()

    sheet = {"rows": [{"id": "zeta", "value": "b"}]}
    assert (
        post_auto_approval_receipt(request_id="r1", plan_label="Demo", sheet=sheet)
        is True
    )

    page = direct_unread_notification_page(include_dismissed=False)
    assert len(page.notifications) == 1
    receipt = page.notifications[0]
    assert receipt.silent is True

    snapshot = read_notification_snapshot()
    priority, errors, rest, muted = unread_notification_buckets(snapshot.notifications)
    assert [n.id for n in priority + errors + rest + muted] == []

    mixin = LifecycleMixin.__new__(LifecycleMixin)
    assert receipt.id not in mixin._read_unread_notification_ids()
    state = mixin._read_notifications_for_startup()
    assert receipt.id not in state[0]
    assert all(cursor[1] != receipt.id for cursor in state[1])
