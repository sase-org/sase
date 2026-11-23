"""Pure tests for ACE surface-token probes."""

from __future__ import annotations

import os
from pathlib import Path

from sase.ace.tui.actions.event_refresh._surface_tokens import (
    SurfaceToken,
    SurfaceTokenRoots,
    agents_token_reload_kind,
    axe_token_changed_kinds,
    axe_token_consumer_drifted,
    probe_procs_token,
    probe_surface_tokens,
    surface_token_changed_kinds,
    surface_token_drifted,
)
from sase.ace.tui.actions.event_refresh._surface_tokens._compare import (
    _surface_token_changed_entries,
)

_PULSE = ".ace_refresh_pulse"


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def test_unchanged_metadata_is_stable(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    project = projects / "demo"
    _touch(project / "artifacts" / _PULSE)
    first = _agents_token(projects)
    second = _agents_token(projects)
    assert first == second
    assert not first.indeterminate
    assert not surface_token_drifted(second, first)


def test_surface_tokens_are_isolated(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    _touch(roots.projects_root / "demo" / "artifacts" / _PULSE)
    _write(roots.axe_root / "status.json", "{}")
    _write(roots.notifications_path, "n\n")
    _write(roots.projects_root / "demo" / "demo.sase", "NAME: demo\n")
    _write(roots.beads_dir / "issues.jsonl", "{}\n")
    _write(roots.procs_path, "{}\n")
    baseline = probe_surface_tokens(roots)

    _write(roots.axe_root / "lumberjacks" / "hooks" / "status.json", '{"ok":true}')
    after_axe = probe_surface_tokens(roots)
    assert after_axe.axe != baseline.axe
    assert after_axe.agents == baseline.agents
    assert after_axe.notifications == baseline.notifications
    assert after_axe.patches == baseline.patches
    assert after_axe.procs == baseline.procs

    _write(roots.notifications_path, "n\nmore\n")
    after_notes = probe_surface_tokens(roots)
    assert after_notes.notifications != after_axe.notifications
    assert after_notes.axe == after_axe.axe


def test_creation_and_removal_are_visible(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    missing = _agents_token(projects)
    project = projects / "demo"
    pulse = project / "artifacts" / _PULSE
    _touch(pulse)
    created = _agents_token(projects)
    assert created != missing
    pulse.unlink()
    removed = _agents_token(projects)
    assert removed != created
    (project / "artifacts").rmdir()
    project.rmdir()
    gone = _agents_token(projects)
    assert gone != created


def test_refresh_pulse_updates_agents_token(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    pulse = projects / "demo" / "artifacts" / _PULSE
    _write(pulse, "1")
    first = _agents_token(projects)
    _write(pulse, "22")
    os.utime(pulse, ns=(1, 2))
    second = _agents_token(projects)
    assert first != second


def test_agent_artifact_index_updates_agents_token(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    index_path = tmp_path / "agent_artifact_index.sqlite"
    _touch(projects / "demo" / "artifacts" / _PULSE)
    _write(index_path, "before")
    first = probe_surface_tokens(
        SurfaceTokenRoots(
            projects_root=projects,
            axe_root=projects / ".unused-axe",
            notifications_path=projects / ".unused-notifications.jsonl",
            procs_path=projects / ".unused-procs.jsonl",
            agent_index_path=index_path,
        )
    ).agents
    _write(index_path, "after")
    os.utime(index_path, ns=(1, 2))
    second = probe_surface_tokens(
        SurfaceTokenRoots(
            projects_root=projects,
            axe_root=projects / ".unused-axe",
            notifications_path=projects / ".unused-notifications.jsonl",
            procs_path=projects / ".unused-procs.jsonl",
            agent_index_path=index_path,
        )
    ).agents
    assert first != second


def test_runner_limit_updates_capacity_token_without_dirtying_agents(
    tmp_path: Path,
) -> None:
    roots = _roots(tmp_path)
    first_snapshot = probe_surface_tokens(roots)
    limit_path = roots.runner_limit_override_path
    hold_path = roots.agent_hold_store_path
    assert limit_path is not None
    assert hold_path is not None

    _write(limit_path, '{"limit":2}')
    os.utime(limit_path, ns=(1, 2))
    after_limit = probe_surface_tokens(roots)
    assert after_limit.runner_capacity != first_snapshot.runner_capacity
    assert after_limit.agents == first_snapshot.agents

    _write(hold_path, '{"holds":[]}')
    os.utime(hold_path, ns=(3, 4))
    after_holds = probe_surface_tokens(roots)
    assert after_holds.runner_capacity != after_limit.runner_capacity
    assert after_holds.agents == after_limit.agents


def test_runner_slot_token_updates_capacity_token_without_dirtying_agents(
    tmp_path: Path,
) -> None:
    roots = _roots(tmp_path)
    token_path = roots.runner_slot_token_path
    assert token_path is not None
    first = probe_surface_tokens(roots)
    _write(token_path, "1")
    os.utime(token_path, ns=(1, 2))
    second = probe_surface_tokens(roots)
    assert second.runner_capacity != first.runner_capacity
    assert second.agents == first.agents


def test_nested_agent_archive_is_ignored(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    artifacts = projects / "demo" / "artifacts"
    nested = artifacts / "ace-run" / "202609" / "agent" / "agent_meta.json"
    _touch(artifacts / _PULSE)
    _write(nested, '{"status":"RUNNING"}')
    first = _agents_token(projects)
    _write(nested, '{"status":"DONE"}')
    second = _agents_token(projects)
    assert first == second


def test_chop_history_is_not_walked(tmp_path: Path) -> None:
    axe = tmp_path / "axe"
    history = axe / "lumberjacks" / "hooks" / "chops" / "lint" / "history.json"
    _write(axe / "lumberjacks" / "hooks" / "status.json", "{}")
    _write(history, '{"runs":[]}')
    first = _axe_token(axe)
    _write(history, '{"runs":[{"id":1}]}')
    second = _axe_token(axe)
    assert first == second


def test_root_scheduler_status_json_is_not_an_axe_token_part(tmp_path: Path) -> None:
    """The collector reads service/lumberjack state, not leftover root status."""
    axe = tmp_path / "axe"
    _write(axe / "pid", "1")
    _write(axe / "status.json", '{"uptime_seconds":1}')
    _write(axe / "metrics.json", '{"cycles_run":1}')
    first = _axe_token(axe)
    _write(axe / "status.json", '{"uptime_seconds":2}')
    os.utime(axe / "status.json", ns=(1, 2))
    _write(axe / "metrics.json", '{"cycles_run":2}')
    os.utime(axe / "metrics.json", ns=(3, 4))
    second = _axe_token(axe)
    assert first == second
    assert not surface_token_drifted(second, first)
    paths = {part[0] for part in first.parts}
    assert str(axe / "status.json") not in paths
    assert str(axe / "metrics.json") not in paths


def test_axe_output_log_change_is_visible(tmp_path: Path) -> None:
    axe = tmp_path / "axe"
    log = axe / "logs" / "output.log"
    _write(log, "a\n")
    first = _axe_token(axe)
    _write(log, "a\nb\n")
    os.utime(log, ns=(1, 2))
    second = _axe_token(axe)
    assert first != second
    assert axe_token_consumer_drifted(second, first, consume_details=False) is False
    assert axe_token_consumer_drifted(second, first, consume_details=True) is True


def test_lumberjack_status_is_hidden_off_services_tab(tmp_path: Path) -> None:
    axe = tmp_path / "axe"
    status = axe / "lumberjacks" / "hooks" / "status.json"
    _write(status, '{"status":"running","uptime_seconds":1}')
    first = _axe_token(axe)
    _write(status, '{"status":"running","uptime_seconds":2}')
    os.utime(status, ns=(1, 2))
    second = _axe_token(axe)
    assert first != second
    assert axe_token_consumer_drifted(second, first, consume_details=False) is False
    assert axe_token_consumer_drifted(second, first, consume_details=True) is True
    assert axe_token_changed_kinds(second, first, consume_details=False) == ()
    assert axe_token_changed_kinds(second, first, consume_details=True) == ("status",)


def test_surface_token_equality_ignores_part_kinds() -> None:
    first = SurfaceToken(
        surface="axe",
        parts=(("/axe/pid", True, 1, 1),),
        part_kinds=("pid",),
    )
    second = SurfaceToken(
        surface="axe",
        parts=(("/axe/pid", True, 1, 1),),
        part_kinds=("log",),
    )
    assert first == second
    assert hash(first) == hash(second)


def test_surface_token_change_kinds_avoid_dynamic_path_labels() -> None:
    first = SurfaceToken(
        surface="agents",
        parts=(("/projects/demo/artifacts/123", True, 1, 1),),
        part_kinds=("artifacts",),
    )
    second = SurfaceToken(
        surface="agents",
        parts=(("/projects/demo/artifacts/123", True, 2, 1),),
        part_kinds=("artifacts",),
    )

    assert surface_token_changed_kinds(second, first) == ("artifacts",)
    assert surface_token_changed_kinds(second, None) == ("unknown",)


def test_axe_pid_change_is_consumed_off_services_tab(tmp_path: Path) -> None:
    axe = tmp_path / "axe"
    pid = axe / "pid"
    _write(pid, "1")
    first = _axe_token(axe)
    _write(pid, "2")
    os.utime(pid, ns=(1, 2))
    second = _axe_token(axe)
    assert axe_token_consumer_drifted(second, first, consume_details=False) is True


def test_agents_index_only_reload_kind_depends_on_watcher(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    index_path = tmp_path / "agent_artifact_index.sqlite"
    _touch(projects / "demo" / "artifacts" / _PULSE)
    _write(index_path, "before")
    roots = SurfaceTokenRoots(
        projects_root=projects,
        axe_root=projects / ".unused-axe",
        notifications_path=projects / ".unused-notifications.jsonl",
        procs_path=projects / ".unused-procs.jsonl",
        agent_index_path=index_path,
    )
    first = probe_surface_tokens(roots).agents
    _write(index_path, "after")
    os.utime(index_path, ns=(1, 2))
    second = probe_surface_tokens(roots).agents
    assert first != second
    assert agents_token_reload_kind(second, first, watcher_active=True) == "skip"
    assert agents_token_reload_kind(second, first, watcher_active=False) == "load"
    kinds = {kind for _path, kind in _surface_token_changed_entries(second, first)}
    assert kinds <= {"index"}


def test_lumberjack_status_change_is_visible(tmp_path: Path) -> None:
    axe = tmp_path / "axe"
    status = axe / "lumberjacks" / "hooks" / "status.json"
    _write(status, '{"status":"running"}')
    first = _axe_token(axe)
    _write(status, '{"status":"stopped","extra":true}')
    os.utime(status, ns=(1, 2))
    second = _axe_token(axe)
    assert first != second


def test_project_spec_and_bead_manifest_invalidate_patches(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    beads = tmp_path / "beads"
    spec = projects / "demo" / "demo.sase"
    manifest = beads / "events" / "manifest.json"
    _write(spec, "NAME: demo\n")
    _write(manifest, "{}")
    first = _patches_token(projects, beads)
    _write(spec, "NAME: demo\nSTATUS: Ready\n")
    os.utime(spec, ns=(1, 2))
    after_spec = _patches_token(projects, beads)
    assert after_spec != first
    _write(manifest, '{"count":1}')
    os.utime(manifest, ns=(3, 4))
    after_manifest = _patches_token(projects, beads)
    assert after_manifest != after_spec


def test_bead_projection_rewrite_does_not_drift_patches(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    beads = tmp_path / "beads"
    _write(projects / "demo" / "demo.sase", "NAME: demo\n")
    _write(beads / "config.json", "{}\n")
    _write(beads / "events" / "manifest.json", "{}")
    _write(beads / "events" / "streams" / "demo-1.jsonl", "{}\n")
    _write(beads / "issues.jsonl", "{}\n")
    first = _patches_token(projects, beads)
    assert not first.indeterminate

    _write(beads / "issues.jsonl", "{}\n{}\n")
    assert _patches_token(projects, beads) == first

    _write(beads / "events" / "streams" / "demo-1.jsonl", "{}\n{}\n")
    assert _patches_token(projects, beads) != first


def test_absent_paths_are_stable(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    first = _notifications_token(missing)
    second = _notifications_token(missing)
    assert first == second
    assert first.parts[0][1] is False
    assert not first.indeterminate


def test_stat_permission_error_is_indeterminate(
    tmp_path: Path, monkeypatch: object
) -> None:
    path = tmp_path / "notifications.jsonl"
    _write(path, "n\n")
    real_stat = Path.stat

    def fake_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self == path:
            raise PermissionError("denied")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)
    token = _notifications_token(path)
    assert token.indeterminate is True
    assert surface_token_drifted(token, None)


def test_scandir_permission_error_is_indeterminate(
    tmp_path: Path, monkeypatch: object
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    real_scandir = os.scandir

    def fake_scandir(path: str | os.PathLike[str] | int | None = None) -> object:
        if path is not None and not isinstance(path, int) and Path(path) == projects:
            raise PermissionError("denied")
        if path is None:
            return real_scandir()
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    token = _agents_token(projects)
    assert token.indeterminate is True


def test_probe_snapshot_includes_every_surface(tmp_path: Path) -> None:
    snapshot = probe_surface_tokens(_roots(tmp_path))
    assert snapshot.token_for("agents").surface == "agents"
    assert snapshot.token_for("axe").surface == "axe"
    assert snapshot.token_for("notifications").surface == "notifications"
    assert snapshot.token_for("patches").surface == "patches"
    assert snapshot.token_for("procs").surface == "procs"


def test_proc_token_tracks_store_file(tmp_path: Path) -> None:
    store = tmp_path / "procs.jsonl"
    first = probe_procs_token(store)
    _write(store, "{}\n")
    second = probe_procs_token(store)
    assert first != second
    _write(store, "{}\n{}\n")
    third = probe_procs_token(store)
    assert third != second


def _agents_token(projects: Path) -> SurfaceToken:
    return probe_surface_tokens(
        SurfaceTokenRoots(
            projects_root=projects,
            axe_root=projects / ".unused-axe",
            notifications_path=projects / ".unused-notifications.jsonl",
            procs_path=projects / ".unused-procs.jsonl",
        )
    ).agents


def _axe_token(axe_root: Path) -> SurfaceToken:
    return probe_surface_tokens(
        SurfaceTokenRoots(
            projects_root=axe_root / ".unused-projects",
            axe_root=axe_root,
            notifications_path=axe_root / ".unused-notifications.jsonl",
            procs_path=axe_root / ".unused-procs.jsonl",
        )
    ).axe


def _notifications_token(path: Path) -> SurfaceToken:
    return probe_surface_tokens(
        SurfaceTokenRoots(
            projects_root=path.parent / ".unused-projects",
            axe_root=path.parent / ".unused-axe",
            notifications_path=path,
            procs_path=path.parent / ".unused-procs.jsonl",
        )
    ).notifications


def _patches_token(projects: Path, beads_dir: Path) -> SurfaceToken:
    return probe_surface_tokens(
        SurfaceTokenRoots(
            projects_root=projects,
            axe_root=projects / ".unused-axe",
            notifications_path=projects / ".unused-notifications.jsonl",
            procs_path=projects / ".unused-procs.jsonl",
            beads_dir=beads_dir,
        )
    ).patches


def _roots(tmp_path: Path) -> SurfaceTokenRoots:
    return SurfaceTokenRoots(
        projects_root=tmp_path / "projects",
        axe_root=tmp_path / "axe",
        notifications_path=tmp_path / "notifications.jsonl",
        procs_path=tmp_path / "procs.jsonl",
        beads_dir=tmp_path / "beads",
        runner_limit_override_path=tmp_path / "max_running_agents_override.json",
        runner_slot_token_path=tmp_path / "runner_slots.token",
        agent_hold_store_path=tmp_path / "agent_holds.json",
    )
