"""Tests for the ``sase project`` handler."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.main import project_handler
from sase.main.project_handler import handle_project_command
from sase.running_field._model import WorkspaceClaim
from tests.main.workspace_handler_helpers import make_args


def _write_project(projects_root: Path, name: str, content: str) -> Path:
    project_dir = projects_root / name
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / f"{name}.sase"
    project_file.write_text(content, encoding="utf-8")
    return project_file


def _fake_apply_project_lifecycle_update(content: str, state: str) -> str:
    lines = content.splitlines(keepends=True)
    state_line = f"PROJECT_STATE: {state}\n"
    for index, line in enumerate(lines):
        if line.startswith("PROJECT_STATE:"):
            lines[index] = state_line
            return "".join(lines)

    insert_index = len(lines)
    for index, line in enumerate(lines):
        if line.startswith(("RUNNING:", "NAME:")):
            insert_index = index
            break
    lines.insert(insert_index, state_line)
    return "".join(lines)


def _fake_list_workspace_claims_from_content(content: str) -> list[WorkspaceClaim]:
    claims: list[WorkspaceClaim] = []
    for line in content.splitlines():
        claim = WorkspaceClaim.from_line(line)
        if claim is not None:
            claims.append(claim)
    return claims


def _parse_header(content: str) -> tuple[str, bool, str | None, int]:
    state = "active"
    explicit = False
    workspace_dir: str | None = None
    active_claim_count = 0
    before_changespec = True
    in_running = False
    for line in content.splitlines():
        if line.startswith("NAME:"):
            before_changespec = False
            in_running = False
        if not before_changespec:
            continue
        if line.startswith("PROJECT_STATE:"):
            state = line.split(":", 1)[1].strip() or "active"
            explicit = True
        elif line.startswith("WORKSPACE_DIR:"):
            workspace_dir = line.split(":", 1)[1].strip() or None
        elif line.startswith("RUNNING:"):
            in_running = True
        elif in_running and WorkspaceClaim.from_line(line) is not None:
            active_claim_count += 1
        elif in_running and line and not line.startswith(" "):
            in_running = False
    return state, explicit, workspace_dir, active_claim_count


def _disk_project_records(
    root: str | Path,
    include_states: list[str],
    include_home: bool = False,
) -> list[ProjectRecordWire]:
    projects_root = Path(root)
    state_set = set(include_states)
    records: list[ProjectRecordWire] = []
    if not projects_root.is_dir():
        return records

    for project_dir in sorted(projects_root.iterdir()):
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if project_name == "home" and not include_home:
            continue
        project_file = project_dir / f"{project_name}.sase"
        if not project_file.is_file():
            continue
        content = project_file.read_text(encoding="utf-8")
        state, explicit, workspace_dir, active_claim_count = _parse_header(content)
        if state not in state_set:
            continue
        archive_file = project_dir / f"{project_name}-archive.sase"
        records.append(
            ProjectRecordWire(
                schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
                project_name=project_name,
                project_dir=str(project_dir),
                project_file=str(project_file),
                archive_file=str(archive_file) if archive_file.exists() else None,
                workspace_dir=workspace_dir,
                state=state,
                state_explicit=explicit,
                system_managed=project_name == "home",
                active_claim_count=active_claim_count,
                launchable=state == "active" and workspace_dir is not None,
                warnings=[],
                parse_warnings=[],
            )
        )
    return records


@pytest.fixture
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    projects = sase_home / "projects"
    projects.mkdir(parents=True)
    return projects


@pytest.fixture
def lifecycle_stubs(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[], None]:
    def install() -> None:
        monkeypatch.setattr(
            project_handler, "list_project_records", _disk_project_records
        )
        monkeypatch.setattr(
            project_handler,
            "apply_project_lifecycle_update",
            _fake_apply_project_lifecycle_update,
        )
        monkeypatch.setattr(
            project_handler,
            "list_workspace_claims_from_content",
            _fake_list_workspace_claims_from_content,
        )

    return install


class TestListAndShow:
    def test_list_json_includes_all_states(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")
        _write_project(
            projects_root,
            "beta",
            "PROJECT_STATE: archived\nWORKSPACE_DIR: /tmp/beta\nNAME: b\n",
        )

        args = make_args(project_subcommand="list", state="all", json=True)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert [item["project_name"] for item in payload] == ["alpha", "beta"]
        assert payload[0]["state"] == "active"
        assert payload[0]["state_source"] == "defaulted"
        assert payload[1]["state"] == "archived"
        assert payload[1]["state_source"] == "explicit"

    def test_list_defaults_to_active_projects(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")
        _write_project(projects_root, "beta", "PROJECT_STATE: closed\nNAME: b\n")

        args = make_args(project_subcommand="list", state="active", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "beta" not in out

    def test_show_json_reports_missing_state_default(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")

        args = make_args(project_subcommand="show", project="alpha", json=True)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["project_name"] == "alpha"
        assert payload["state"] == "active"
        assert payload["state_explicit"] is False
        assert payload["state_source"] == "defaulted"

    def test_show_missing_project_exits_one(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()

        args = make_args(project_subcommand="show", project="ghost", json=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "ghost" in capsys.readouterr().err


class TestMutation:
    def test_set_state_inserts_before_running(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nRUNNING:\n\nNAME: a\n",
        )

        args = make_args(project_subcommand="archive", project="alpha", force=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert (
            "WORKSPACE_DIR: /tmp/alpha\nPROJECT_STATE: archived\nRUNNING:\n"
            in project_file.read_text(encoding="utf-8")
        )
        assert "state is now archived" in capsys.readouterr().out

    def test_set_state_replaces_existing_state(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "PROJECT_STATE: archived\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )

        args = make_args(
            project_subcommand="set-state",
            project="alpha",
            state="active",
            force=False,
        )
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert project_file.read_text(encoding="utf-8").startswith(
            "PROJECT_STATE: active\n"
        )

    def test_rejects_live_running_claim_without_force(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nRUNNING:\n"
            "  #10 | 12345 | run | alpha_work_1 | 260601_120000\n"
            "\nNAME: a\n",
        )

        args = make_args(project_subcommand="archive", project="alpha", force=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "RUNNING claim" in capsys.readouterr().err
        assert "PROJECT_STATE" not in project_file.read_text(encoding="utf-8")

    def test_force_allows_live_running_claim(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nRUNNING:\n"
            "  #10 | 12345 | run | alpha_work_1 | 260601_120000\n"
            "\nNAME: a\n",
        )

        args = make_args(project_subcommand="close", project="alpha", force=True)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 0
        assert "PROJECT_STATE: closed\n" in project_file.read_text(encoding="utf-8")

    def test_rejects_live_artifact_marker_without_force(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )
        marker = projects_root / "alpha" / "artifacts" / "run" / "260601120000"
        marker.mkdir(parents=True)
        (marker / "waiting.json").write_text("{}", encoding="utf-8")

        args = make_args(project_subcommand="close", project="alpha", force=False)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "live artifact marker" in capsys.readouterr().err
        assert "PROJECT_STATE" not in project_file.read_text(encoding="utf-8")

    def test_home_project_mutation_is_rejected(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "home", "WORKSPACE_DIR: /tmp/home\nNAME: h\n")

        args = make_args(project_subcommand="archive", project="home", force=True)
        with pytest.raises(SystemExit) as exc:
            handle_project_command(args)

        assert exc.value.code == 1
        assert "system-managed" in capsys.readouterr().err


class TestDeletion:
    def test_delete_removes_entire_project_directory(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")
        project_dir = projects_root / "alpha"
        (project_dir / "alpha-archive.sase").write_text("NAME: old\n", encoding="utf-8")
        (project_dir / "sase.yml").write_text("xprompts: []\n", encoding="utf-8")
        artifact = project_dir / "artifacts" / "run" / "260601120000" / "done.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("{}", encoding="utf-8")

        deleted_dir = project_handler.delete_project_locked("alpha")

        assert deleted_dir == project_dir
        assert not project_dir.exists()

    def test_delete_rejects_home_project(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "home", "WORKSPACE_DIR: /tmp/home\nNAME: h\n")

        with pytest.raises(
            project_handler.ProjectLifecycleError, match="system-managed"
        ):
            project_handler.delete_project_locked("home")

        assert (projects_root / "home").is_dir()

    def test_delete_rejects_live_running_claim_and_leaves_directory_intact(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nRUNNING:\n"
            "  #10 | 12345 | run | alpha_work_1 | 260601_120000\n"
            "\nNAME: a\n",
        )

        with pytest.raises(
            project_handler.ProjectLifecycleBlockedError,
            match="RUNNING claim",
        ):
            project_handler.delete_project_locked("alpha")

        assert project_file.is_file()
        assert (projects_root / "alpha").is_dir()

    def test_delete_rejects_live_artifact_marker_and_leaves_directory_intact(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        project_file = _write_project(
            projects_root,
            "alpha",
            "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
        )
        marker = projects_root / "alpha" / "artifacts" / "run" / "260601120000"
        marker.mkdir(parents=True)
        (marker / "running.json").write_text("{}", encoding="utf-8")

        with pytest.raises(
            project_handler.ProjectLifecycleBlockedError,
            match="live artifact marker",
        ):
            project_handler.delete_project_locked("alpha")

        assert project_file.is_file()
        assert marker.is_dir()

    def test_delete_rejects_path_traversal_and_leaves_directory_intact(
        self,
        projects_root: Path,
        lifecycle_stubs: Callable[[], None],
    ) -> None:
        lifecycle_stubs()
        _write_project(projects_root, "alpha", "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n")

        with pytest.raises(project_handler.ProjectLifecycleError, match="invalid"):
            project_handler.delete_project_locked("../alpha")

        assert (projects_root / "alpha").is_dir()
