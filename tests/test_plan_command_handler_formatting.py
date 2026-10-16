"""``sase plan propose`` validates the formatted bytes it archives."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import redirect_sase_home
from tests.plan_command_handler_helpers import (
    clear_bead_work_association_env,
    invoke_plan as _invoke_plan,
    make_artifacts_dir as _make_artifacts_dir,
)

DECISIONS_TALE = """---
tier: tale
title: Ship the planned change
goal: Ship the planned change
size: small
decisions:
  tui_note:
    ask: Edit the TUI note?
    default: false
  grouping:
    ask: Group the output?
    default: false
---
# Plan

Ship tui_note and grouping.

> [!decision] tui_note
> [!decision] grouping
> Covers both branches.
"""

HEADLINE = (
    "Error: formatting this plan for the archive would change its meaning; "
    "nothing was proposed."
)
HINT = (
    "Give each > [!decision] header its own paragraph or rephrase the "
    "affected text, then rerun sase plan propose."
)


@pytest.fixture(autouse=True)
def _clear_bead_work_association_env(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_bead_work_association_env(monkeypatch)


def _rename_first_callout(raw: str) -> str:
    return raw.replace("> [!decision] tui_note\n", "> [!decision] tui_nope\n")


def _merge_callout_headers(raw: str) -> str:
    return raw.replace(
        "> [!decision] tui_note\n> [!decision] grouping\n",
        "> [!decision] tui_note [!decision] grouping\n",
    )


def _propose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    formatter: Callable[[str], str],
) -> tuple[int, Path, Path, Path, object]:
    """Run propose with *formatter* standing in for prettier."""
    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "decisions.md"
    plan_file.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with (
        patch(
            "sase.main.plan_propose_handler.kill_agent_runner_group",
            side_effect=SystemExit(0),
        ) as kill,
        patch("sase.file_references.format_with_prettier", side_effect=formatter),
    ):
        code = _invoke_plan(plan_file)
    return code, plan_file, artifacts_dir, sase_home, kill


def _assert_nothing_proposed(
    plan_file: Path,
    content: str,
    artifacts_dir: Path,
    sase_home: Path,
    kill: object,
) -> None:
    assert plan_file.read_text(encoding="utf-8") == content
    assert list((sase_home / "plans").rglob("*.md")) == []
    assert not (artifacts_dir / ".sase_plan_pending").exists()
    kill.assert_not_called()  # type: ignore[attr-defined]


def test_formatter_renaming_a_callout_id_fails_before_any_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A callout that formatting made invalid never reaches the archive."""
    code, plan_file, artifacts_dir, sase_home, kill = _propose(
        tmp_path, monkeypatch, DECISIONS_TALE, _rename_first_callout
    )

    assert code == 1
    _assert_nothing_proposed(plan_file, DECISIONS_TALE, artifacts_dir, sase_home, kill)
    error = capsys.readouterr().err
    lines = error.splitlines()
    assert lines[0] == HEADLINE
    assert lines[-1] == HINT
    assert "decision-branch-unknown" in error
    assert "    > [!decision] tui_nope" in lines
    assert "Validation failed" not in error


def test_formatter_merging_callout_headers_reports_the_dropped_callout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A merged header still validates, so the callout drift check catches it."""
    code, plan_file, artifacts_dir, sase_home, kill = _propose(
        tmp_path, monkeypatch, DECISIONS_TALE, _merge_callout_headers
    )

    assert code == 1
    _assert_nothing_proposed(plan_file, DECISIONS_TALE, artifacts_dir, sase_home, kill)
    lines = capsys.readouterr().err.splitlines()
    assert lines == [HEADLINE, "lost callout: grouping = yes", HINT]


def test_identity_formatter_archives_a_plan_with_decision_callouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Formatting that preserves the callouts keeps today's success path."""
    code, plan_file, artifacts_dir, sase_home, kill = _propose(
        tmp_path, monkeypatch, DECISIONS_TALE, lambda raw: raw
    )

    assert code == 0
    assert not plan_file.exists()
    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    archived = Path(marker["plan_file"])
    assert archived.is_relative_to(sase_home / "plans")
    assert "> [!decision] tui_note [!decision]" not in archived.read_text(
        encoding="utf-8"
    )
    kill.assert_called_once()  # type: ignore[attr-defined]


def test_link_inlet_publication_that_breaks_the_archive_restores_the_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Publishing rewrites the archive, so the archived bytes are checked too."""
    content = DECISIONS_TALE.replace(
        "size: small\n",
        "size: small\n"
        "links:\n"
        "  - ref: research:202608/source.md\n"
        "    relation: derives-from\n"
        "    description: uses source report\n",
    )

    def _corrupting_publish(archived: Path, **_kwargs: object) -> tuple[()]:
        archived.write_text(
            _rename_first_callout(archived.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        return ()

    monkeypatch.setattr(
        "sase.sdd.artifact_link_inlet.publish_plan_artifact_link_inlet",
        _corrupting_publish,
    )
    monkeypatch.setattr(
        "sase.main.plan_propose_handler._derive_links_for_archived_plan",
        lambda *_args, **_kwargs: None,
    )

    code, plan_file, artifacts_dir, sase_home, kill = _propose(
        tmp_path, monkeypatch, content, lambda raw: raw
    )

    assert code == 1
    _assert_nothing_proposed(plan_file, content, artifacts_dir, sase_home, kill)
    error = capsys.readouterr().err
    assert error.splitlines()[0] == HEADLINE
    assert "decision-branch-unknown" in error


def test_second_formatting_pass_that_breaks_validation_proposes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Archival formats the plan again; propose checks that pass too."""
    calls: list[str] = []

    def formatter(raw: str) -> str:
        calls.append(raw)
        if len(calls) == 1:
            return raw
        return _rename_first_callout(raw)

    code, plan_file, artifacts_dir, sase_home, kill = _propose(
        tmp_path, monkeypatch, DECISIONS_TALE, formatter
    )

    assert code == 1
    _assert_nothing_proposed(plan_file, DECISIONS_TALE, artifacts_dir, sase_home, kill)
    error = capsys.readouterr().err
    assert error.splitlines()[0] == HEADLINE
    assert "decision-branch-unknown" in error
    assert "    > [!decision] tui_nope" in error.splitlines()


_prettier_required = pytest.mark.skipif(
    shutil.which("prettier") is None, reason="prettier is unavailable"
)

INCIDENT_EPIC = """---
tier: epic
title: Stop Prettier from rewriting identifiers
goal: Keep decision IDs intact across prettier
phases:
  - id: protection
    title: Protect underscores
    depends_on: []
    description: "protection: protect intraword underscores before prettier."
    size: small
decisions:
  memory_glossary:
    ask: Add `/sase_memory_write`?
    default: false
---
# Plan

> [!decision] memory_glossary Add `/sase_memory_write`. (also called an *article*) as a Bob note.
"""


@_prettier_required
def test_incident_shaped_epic_proposes_and_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real prettier keeps memory_glossary through propose and archival."""
    from sase.sdd.plan_archive import archive_plan_file
    from sase.sdd.store import SddStore

    sase_home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, sase_home)
    artifacts_dir = _make_artifacts_dir(sase_home)
    plan_file = tmp_path / "incident.md"
    plan_file.write_text(INCIDENT_EPIC, encoding="utf-8")
    monkeypatch.setenv("SASE_AGENT", "agent-x")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))

    with patch(
        "sase.main.plan_propose_handler.kill_agent_runner_group",
        side_effect=SystemExit(0),
    ) as kill:
        code = _invoke_plan(plan_file)

    assert code == 0
    marker = json.loads(
        (artifacts_dir / ".sase_plan_pending").read_text(encoding="utf-8")
    )
    proposed = Path(marker["plan_file"]).read_text(encoding="utf-8")
    assert "memory_glossary" in proposed
    assert "memory*glossary" not in proposed
    kill.assert_called_once()  # type: ignore[attr-defined]

    store_root = tmp_path / "sidecar-plans"
    store_root.mkdir()
    source = tmp_path / "to-archive.md"
    source.write_text(proposed, encoding="utf-8")
    result = archive_plan_file(
        source,
        SddStore("sidecar_repos", store_root, store_root),
        tier="epic",
        yyyymm="202610",
        primary_root=tmp_path,
        preserve_existing=False,
    )
    archived = result.path.read_text(encoding="utf-8")
    assert "memory_glossary" in archived
    assert "memory*glossary" not in archived
