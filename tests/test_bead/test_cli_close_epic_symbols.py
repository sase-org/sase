"""CLI coverage for close-time leftover ``--epic-symbol`` discovery."""

from __future__ import annotations

from pathlib import Path

import subprocess

import pytest

from sase.bead import cli as bead_cli
from sase.bead.epic_symbol_freshness import _run_preflight
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import BeadProject
from sase.main.parser import create_parser
from tests._axe_chop_bead_task_triage_helpers import flag_task_fields
from tests.test_bead.resolution_test_helpers import (
    bead_store_snapshot,
    isolate_bead_store_resolution,
)


def _write_justfile(project_dir: Path, *flags: str) -> None:
    lines = " \\\n        ".join(flags)
    project_dir.joinpath("Justfile").write_text(
        f"symvision src \\\n        {lines}\n",
        encoding="utf-8",
    )


def _route_to_owner_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner: Path,
    project_name: str,
    issue_ids: tuple[str, ...],
) -> None:
    monkeypatch.setattr(
        "sase.bead.operation_context._local_location_for_resolution",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.bead.operation_context.enabled_project_store_snapshots",
        lambda: (bead_store_snapshot(project_name, owner, *issue_ids),),
    )


def test_close_refuses_leftover_epic_symbols_for_a_phase(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = project.create("Store", IssueType.PHASE, parent_id=epic.id)
    _write_justfile(
        project_dir,
        f'--epic-symbol "{phase.id}(CommonPlaceholderIndex)"',
        f'--epic-symbol "{phase.id}(load_common_placeholder_index)"',
        '--epic-symbol "sase-unrelated(OtherSymbol)"',
    )

    args = create_parser().parse_args(["bead", "close", phase.id, "--note", "done"])
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    error = capsys.readouterr().err
    assert f"refusing to close {phase.id}" in error
    assert f'--epic-symbol "{phase.id}(CommonPlaceholderIndex)"' in error
    assert f'--epic-symbol "{phase.id}(load_common_placeholder_index)"' in error
    assert "sase-unrelated(OtherSymbol)" not in error
    assert f"sase bead epic-symbols {phase.id}" in error
    with BeadProject(project_dir) as project:
        assert project.show(phase.id).status is not Status.CLOSED


def test_close_of_epic_surfaces_descendant_phase_entries(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
        phase = project.create("Scoring", IssueType.PHASE, parent_id=epic.id)
        project.close([phase.id])
    _write_justfile(
        project_dir,
        f'--epic-symbol "{phase.id}(RankedPlaceholder)"',
    )

    args = create_parser().parse_args(["bead", "close", epic.id])
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    error = capsys.readouterr().err
    assert f"refusing to close {epic.id}" in error
    assert f'--epic-symbol "{phase.id}(RankedPlaceholder)"' in error
    with BeadProject(project_dir) as project:
        assert project.show(epic.id).status is not Status.CLOSED


def test_close_of_one_phase_ignores_sibling_phase_entries(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
        first = project.create("Context", IssueType.PHASE, parent_id=epic.id)
        second = project.create("Scoring", IssueType.PHASE, parent_id=epic.id)
    _write_justfile(project_dir, f'--epic-symbol "{second.id}(RankedPlaceholder)"')

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", first.id]))

    with BeadProject(project_dir) as project:
        assert project.show(first.id).status is Status.CLOSED
        assert project.show(second.id).status is not Status.CLOSED


def test_close_succeeds_after_justfile_entries_are_removed(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    _write_justfile(project_dir, f'--epic-symbol "{issue.id}(TempSymbol)"')
    project_dir.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", issue.id]))

    with BeadProject(project_dir) as project:
        assert project.show(issue.id).status is Status.CLOSED


def test_close_refuses_flag_bead_until_registry_definition_is_removed(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create(
            "Remove the old_path flag",
            IssueType.TASK,
            size="small",
            task_type="flag",
            task_type_fields=flag_task_fields(key="old_path"),
        )
    _write_justfile(project_dir, "--exclude-decorator builtin_chop")
    registry = project_dir / "src/sase/feature_flags/registry.py"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "FeatureFlagDefinition(\n"
        "    key=FeatureFlag.old_path,\n"
        '    kind="sunset",\n'
        f'    bead="{issue.id}",\n'
        ")\n",
        encoding="utf-8",
    )

    args = create_parser().parse_args(["bead", "close", issue.id, "--note", "done"])
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    error = capsys.readouterr().err
    assert f"refusing to close {issue.id}" in error
    assert f"old_path (bead={issue.id})" in error
    with BeadProject(project_dir) as project:
        assert project.show(issue.id).status is not Status.CLOSED

    registry.write_text("", encoding="utf-8")
    bead_cli.handle_bead_close(args)

    with BeadProject(project_dir) as project:
        assert project.show(issue.id).status is Status.CLOSED


def test_reclose_of_already_closed_bead_skips_leftover_check(
    project_dir: Path,
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Already landed", IssueType.PLAN)
        project.close([issue.id])
    _write_justfile(project_dir, f'--epic-symbol "{issue.id}(StaleSymbol)"')

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", issue.id]))

    with BeadProject(project_dir) as project:
        assert project.show(issue.id).status is Status.CLOSED


def test_force_close_still_refuses_leftover_epic_symbols(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        epic = project.create("Canceled", IssueType.PLAN, tier=BeadTier.EPIC)
        project.create("Unfinished", IssueType.PHASE, parent_id=epic.id)
    _write_justfile(project_dir, f'--epic-symbol "{epic.id}(TempSymbol)"')

    args = create_parser().parse_args(
        [
            "bead",
            "close",
            epic.id,
            "--force",
            "--reason",
            "abandoning",
            "--resolution",
            "canceled",
        ]
    )
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    error = capsys.readouterr().err
    assert f'--epic-symbol "{epic.id}(TempSymbol)"' in error
    with BeadProject(project_dir) as project:
        assert project.show(epic.id).status is not Status.CLOSED


def test_close_same_project_uses_invocation_checkout_not_stale_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "owner_21"
    with BeadProject.init(owner) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    isolate_bead_store_resolution(
        monkeypatch,
        caller,
        primary=owner,
        workspace_num=21,
        project_name="owner",
    )
    _route_to_owner_snapshot(
        monkeypatch,
        owner=owner,
        project_name="owner",
        issue_ids=(issue.id,),
    )
    _write_justfile(owner, f'--epic-symbol "{issue.id}(PrimaryStale)"')
    caller.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")

    bead_cli.handle_bead_close(create_parser().parse_args(["bead", "close", issue.id]))

    with BeadProject(owner) as project:
        assert project.show(issue.id).status is Status.CLOSED


def test_close_same_project_invocation_checkout_exemption_still_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "owner_21"
    with BeadProject.init(owner) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    isolate_bead_store_resolution(
        monkeypatch,
        caller,
        primary=owner,
        workspace_num=21,
        project_name="owner",
    )
    _route_to_owner_snapshot(
        monkeypatch,
        owner=owner,
        project_name="owner",
        issue_ids=(issue.id,),
    )
    _write_justfile(caller, f'--epic-symbol "{issue.id}(ImplementingStale)"')

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(
            create_parser().parse_args(["bead", "close", issue.id])
        )

    error = capsys.readouterr().err
    assert "ImplementingStale" in error
    with BeadProject(owner) as project:
        assert project.show(issue.id).status is not Status.CLOSED


def test_close_foreign_project_ignores_caller_decoy_and_checks_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "caller"
    with BeadProject.init(owner) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    isolate_bead_store_resolution(monkeypatch, caller, project_name="caller")
    _route_to_owner_snapshot(
        monkeypatch,
        owner=owner,
        project_name="owner",
        issue_ids=(issue.id,),
    )
    _write_justfile(owner, f'--epic-symbol "{issue.id}(OwnerStale)"')
    _write_justfile(caller, f'--epic-symbol "{issue.id}(CallerDecoy)"')

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(
            create_parser().parse_args(["bead", "close", issue.id])
        )

    error = capsys.readouterr().err
    assert "OwnerStale" in error
    assert "CallerDecoy" not in error
    with BeadProject(owner) as project:
        assert project.show(issue.id).status is not Status.CLOSED


def test_close_same_project_subdirectory_uses_checkout_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    caller = tmp_path / "owner_21"
    subdir = caller / "src" / "pkg"
    with BeadProject.init(owner) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    isolate_bead_store_resolution(
        monkeypatch,
        caller,
        primary=owner,
        workspace_num=21,
        project_name="owner",
    )
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    _route_to_owner_snapshot(
        monkeypatch,
        owner=owner,
        project_name="owner",
        issue_ids=(issue.id,),
    )
    _write_justfile(caller, f'--epic-symbol "{issue.id}(NestedCheckoutStale)"')

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(
            create_parser().parse_args(["bead", "close", issue.id])
        )

    assert "NestedCheckoutStale" in capsys.readouterr().err
    with BeadProject(owner) as project:
        assert project.show(issue.id).status is not Status.CLOSED


def test_close_without_usable_local_checkout_falls_back_to_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owner = tmp_path / "owner"
    outside = tmp_path / "outside"
    outside.mkdir()
    with BeadProject.init(owner) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    isolate_bead_store_resolution(monkeypatch, owner, project_name="owner")
    monkeypatch.chdir(outside)
    _route_to_owner_snapshot(
        monkeypatch,
        owner=owner,
        project_name="owner",
        issue_ids=(issue.id,),
    )
    _write_justfile(owner, f'--epic-symbol "{issue.id}(OwnerFallback)"')

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(
            create_parser().parse_args(["bead", "close", issue.id])
        )

    assert "OwnerFallback" in capsys.readouterr().err
    with BeadProject(owner) as project:
        assert project.show(issue.id).status is not Status.CLOSED


def _git_run(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, capture_output=True, check=True)


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git_run(path, "init", "-b", "master")
    _git_run(path, "config", "user.email", "sase-test@example.com")
    _git_run(path, "config", "user.name", "sase-test")
    _git_run(path, "config", "commit.gpgsign", "false")


def test_close_refuses_upstream_only_epic_symbol_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = tmp_path / "work"
    remote = tmp_path / "remote"
    _init_git_repo(remote)
    remote.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")
    _git_run(remote, "add", "Justfile")
    _git_run(remote, "commit", "-m", "initial justfile")
    _git_run(tmp_path, "clone", str(remote), str(work))
    with BeadProject.init(work):
        pass
    isolate_bead_store_resolution(monkeypatch, work, project_name="test-project")
    with BeadProject(work) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
    remote.joinpath("Justfile").write_text(
        f'symvision src \\\n        --epic-symbol "{epic.id}(UpstreamSymbol)"\n',
        encoding="utf-8",
    )
    _git_run(remote, "add", "Justfile")
    _git_run(remote, "commit", "-m", "sibling phase lands a whitelist row")
    work.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")

    args = create_parser().parse_args(["bead", "close", epic.id])
    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(args)

    error = capsys.readouterr().err
    assert f"refusing to close {epic.id}" in error
    assert f'--epic-symbol "{epic.id}(UpstreamSymbol)"' in error
    assert "origin/master" in error
    with BeadProject(work) as project:
        assert project.show(epic.id).status is not Status.CLOSED


def test_epic_symbols_lists_upstream_only_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = tmp_path / "work"
    remote = tmp_path / "remote"
    _init_git_repo(remote)
    remote.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")
    _git_run(remote, "add", "Justfile")
    _git_run(remote, "commit", "-m", "initial justfile")
    _git_run(tmp_path, "clone", str(remote), str(work))
    with BeadProject.init(work):
        pass
    isolate_bead_store_resolution(monkeypatch, work, project_name="test-project")
    with BeadProject(work) as project:
        epic = project.create("Ranking", IssueType.PLAN, tier=BeadTier.EPIC)
    remote.joinpath("Justfile").write_text(
        f'symvision src \\\n        --epic-symbol "{epic.id}(UpstreamSymbol)"\n',
        encoding="utf-8",
    )
    _git_run(remote, "add", "Justfile")
    _git_run(remote, "commit", "-m", "sibling phase lands a whitelist row")
    work.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")

    bead_cli.handle_bead_epic_symbols(
        create_parser().parse_args(
            ["bead", "epic-symbols", epic.id, "--color", "never"]
        )
    )

    output = capsys.readouterr().out
    assert f'--epic-symbol "{epic.id}(UpstreamSymbol)"' in output
    assert "origin/master" in output


def test_close_fetch_failure_falls_back_to_local_with_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    work = tmp_path / "work"
    _init_git_repo(work)
    with BeadProject.init(work):
        pass
    isolate_bead_store_resolution(monkeypatch, work, project_name="test-project")
    with BeadProject(work) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    work.joinpath("Justfile").write_text(
        f'symvision src \\\n        --epic-symbol "{issue.id}(LocalSymbol)"\n',
        encoding="utf-8",
    )
    _git_run(work, "add", "Justfile")
    _git_run(work, "commit", "-m", "local justfile")
    _git_run(work, "remote", "add", "origin", str(tmp_path / "no-such-remote"))

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_close(
            create_parser().parse_args(["bead", "close", issue.id])
        )

    error = capsys.readouterr().err
    assert f'--epic-symbol "{issue.id}(LocalSymbol)"' in error
    assert "upstream" in error.lower()
    assert "local Justfile" in error
    with BeadProject(work) as project:
        assert project.show(issue.id).status is not Status.CLOSED


def test_update_status_closed_refuses_leftover_epic_symbols(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("Cleanup", IssueType.PLAN)
    _write_justfile(project_dir, f'--epic-symbol "{issue.id}(TempSymbol)"')

    with pytest.raises(SystemExit, match="1"):
        bead_cli.handle_bead_update(
            create_parser().parse_args(["bead", "update", issue.id, "-s", "closed"])
        )

    error = capsys.readouterr().err
    assert f"refusing to close {issue.id}" in error
    assert f'--epic-symbol "{issue.id}(TempSymbol)"' in error
    with BeadProject(project_dir) as project:
        assert project.show(issue.id).status is not Status.CLOSED


def test_old_observer_retains_row_after_published_cleanup_and_guarded_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = tmp_path / "seed"
    remote = tmp_path / "remote.git"
    producer = tmp_path / "producer"
    observer = tmp_path / "observer"
    bead_store = tmp_path / "bead-store"
    _init_git_repo(seed)
    source = seed / "src" / "example.py"
    source.parent.mkdir()
    source.write_text(
        "def CommonPlaceholderIndex():\n    return None\n",
        encoding="utf-8",
    )
    with BeadProject.init(bead_store) as project:
        epic = project.create(
            "Placeholder work",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
        )
        issue = project.create(
            "Finish the placeholder",
            IssueType.PHASE,
            parent_id=epic.id,
        )

    symbol = "CommonPlaceholderIndex"
    _write_justfile(seed, f'--epic-symbol "{issue.id}({symbol})"')
    _git_run(seed, "add", "Justfile", "src/example.py")
    _git_run(seed, "commit", "-m", "publish phase whitelist row")
    _git_run(tmp_path, "clone", "--bare", str(seed), str(remote))
    _git_run(tmp_path, "clone", str(remote), str(producer))
    _git_run(tmp_path, "clone", str(remote), str(observer))

    for checkout in (producer, observer):
        checkout.joinpath("sdd").mkdir()
        checkout.joinpath("sdd", "beads").symlink_to(bead_store / "sdd" / "beads")

    producer.joinpath("Justfile").write_text("symvision src\n", encoding="utf-8")
    producer.joinpath("src", "example.py").write_text(
        "def unrelated_helper():\n    return None\n",
        encoding="utf-8",
    )
    _git_run(producer, "add", "Justfile", "src/example.py")
    _git_run(producer, "commit", "-m", "publish whitelist cleanup")
    _git_run(producer, "push", "origin", "master")

    # The published cleanup is already visible, but live bead status is still
    # open. This is the first check stage; the Symvision boundary must repeat
    # the preflight after status can change below.
    assert _run_preflight(observer) == 0

    monkeypatch.chdir(producer)
    bead_cli.handle_bead_close(
        create_parser().parse_args(["bead", "close", issue.id, "--note", "landed"])
    )

    with BeadProject(bead_store) as project:
        assert project.show(issue.id).status is Status.CLOSED
    assert f"{issue.id}({symbol})" in observer.joinpath("Justfile").read_text()
    assert (
        f"{issue.id}({symbol})"
        not in subprocess.run(
            ["git", "-C", str(remote), "show", "master:Justfile"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert f"def {symbol}" in observer.joinpath("src", "example.py").read_text()

    observer.joinpath("local-work.txt").write_text("keep this staged\n")
    _git_run(observer, "add", "local-work.txt")
    local_head = subprocess.run(
        ["git", "-C", str(observer), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    index_before = subprocess.run(
        ["git", "-C", str(observer), "diff", "--cached", "--binary"],
        capture_output=True,
        check=True,
    ).stdout
    assert _run_preflight(observer) == 1
    error = capsys.readouterr().err
    assert "stale_checkout" in error
    assert issue.id in error
    assert symbol in error
    assert f"local HEAD {local_head}" in error
    assert "observed upstream revision" in error
    assert "Preserve local work" in error
    assert (
        "integrate the upstream cleanup through the normal workspace workflow" in error
    )
    assert observer.joinpath("local-work.txt").read_text() == "keep this staged\n"
    assert (
        subprocess.run(
            ["git", "-C", str(observer), "diff", "--cached", "--binary"],
            capture_output=True,
            check=True,
        ).stdout
        == index_before
    )

    _git_run(observer, "merge", "--ff-only", "origin/master")
    assert _run_preflight(observer) == 0
    assert f"def {symbol}" not in observer.joinpath("src", "example.py").read_text()
