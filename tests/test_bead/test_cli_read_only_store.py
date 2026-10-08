"""Read-only bead resolution never initializes or commits (sase-1gx).

``get_read_view()`` must open an existing usable store or raise
``BeadStoreUnavailableError``. In a checkout with no store it must not
create ``sdd/`` scaffolding, commit anything, or leave the git tree dirty.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_common import BeadStoreUnavailableError, get_read_view
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.plan_show.model import PlanShowMiss
from sase.plan_show.resolve import resolve_plan_show_target
from tests.main.parser_cli_helpers import parse_sase_args
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


def _git(checkout: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", *argv],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()


def _bare_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Make a git checkout with a marker but no bead store; return its HEAD."""
    checkout = tmp_path / "checkout"
    isolate_bead_store_resolution(monkeypatch, checkout)
    _git(checkout, "init", "-q")
    _git(checkout, "config", "user.email", "test@example.com")
    _git(checkout, "config", "user.name", "Test")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-qm", "setup")
    return checkout


def _head(checkout: Path) -> str:
    return _git(checkout, "rev-parse", "HEAD")


def _assert_no_writes(checkout: Path, head: str) -> None:
    assert not (checkout / "sdd").exists()
    assert _git(checkout, "status", "--porcelain") == ""
    assert _head(checkout) == head


def test_get_read_view_raises_unavailable_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _bare_checkout(tmp_path, monkeypatch)
    head = _head(checkout)

    with pytest.raises(BeadStoreUnavailableError) as excinfo:
        get_read_view()

    assert str(checkout) in str(excinfo.value)
    assert excinfo.value.cwd == checkout.resolve()
    assert excinfo.value.searched
    _assert_no_writes(checkout, head)


def test_get_read_view_opens_existing_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _bare_checkout(tmp_path, monkeypatch)
    with BeadProject.init(checkout) as project:
        created = project.create(
            "Read target", IssueType.TASK, task_type="bug", size="small"
        )
    head = _head(checkout)

    with get_read_view() as view:
        assert view.show(created.id).id == created.id

    assert _head(checkout) == head


def test_bead_list_reports_unavailable_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _bare_checkout(tmp_path, monkeypatch)
    head = _head(checkout)

    with pytest.raises(BeadStoreUnavailableError):
        bead_cli.handle_bead_list(parse_sase_args(["bead", "list"]))

    _assert_no_writes(checkout, head)


def test_bead_dep_list_reports_unavailable_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _bare_checkout(tmp_path, monkeypatch)
    head = _head(checkout)

    with pytest.raises(BeadStoreUnavailableError):
        bead_cli.handle_bead_dep(
            parse_sase_args(["bead", "dep", "list", "--color", "never"])
        )

    _assert_no_writes(checkout, head)


def test_attachment_doctor_returns_empty_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.attachment_doctor import inspect_attachment_health

    checkout = _bare_checkout(tmp_path, monkeypatch)
    head = _head(checkout)

    report = inspect_attachment_health()

    assert not report.has_attachments
    _assert_no_writes(checkout, head)


def test_artifact_create_bead_lookup_reports_unavailable_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.artifact_cli.create import _bead_exists

    checkout = _bare_checkout(tmp_path, monkeypatch)
    head = _head(checkout)

    with pytest.raises(ValueError, match="bead store is unavailable"):
        _bead_exists("sase-1")

    _assert_no_writes(checkout, head)


def test_agent_bead_display_returns_none_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agent.bead_display import lookup_bead_issue

    checkout = _bare_checkout(tmp_path, monkeypatch)
    head = _head(checkout)

    assert lookup_bead_issue("sase-1", local_only=True) is None

    _assert_no_writes(checkout, head)


def test_plan_show_target_misses_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _bare_checkout(tmp_path, monkeypatch)
    head = _head(checkout)

    result = resolve_plan_show_target("sase-1", cwd=checkout)

    assert isinstance(result, PlanShowMiss)
    _assert_no_writes(checkout, head)
