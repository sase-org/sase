"""Persist Rust-derived bead event manifest repairs after integration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess

from sase.sdd._repository_health import format_git_error, safe_git_error_text


GitRunner = Callable[..., subprocess.CompletedProcess[str]]
EventLogger = Callable[..., None]


def repair_event_manifest_after_integration(
    repo_root: Path,
    *,
    beads_dir: Path | None,
    runner: GitRunner,
    op_prefix: str,
    event_logger: EventLogger | None,
) -> tuple[bool, tuple[str, ...], str | None]:
    from sase.bead.conflict_resolver import resolve_beads_dir

    resolved_beads_dir = resolve_beads_dir(repo_root, beads_dir)
    if resolved_beads_dir is None:
        return (False, (), None)

    manifest_path = resolved_beads_dir / "events" / "manifest.json"
    try:
        relative_path = (
            manifest_path.resolve().relative_to(repo_root.resolve()).as_posix()
        )
    except ValueError:
        return (
            False,
            (),
            "bead event manifest is outside the SDD repository",
        )
    if manifest_path.exists():
        tracked = runner(
            repo_root,
            ["ls-files", "--error-unmatch", "--", relative_path],
            op=f"{op_prefix}.manifest_tracked",
        )
        if tracked.returncode == 1:
            return (
                False,
                (),
                f"refusing to repair untracked bead event manifest {relative_path}",
            )
        if tracked.returncode != 0:
            return (
                False,
                (),
                format_git_error(
                    "could not inspect bead event manifest tracking", tracked
                ),
            )

    try:
        from sase.core.bead_conflict_facade import repair_event_store_manifest

        repair = repair_event_store_manifest(resolved_beads_dir)
    except Exception as exc:  # noqa: BLE001 - caller owns transactional rollback
        error = f"bead event manifest recount failed: {safe_git_error_text(exc)}"
        _emit_manifest_repair(
            event_logger,
            status="invalid_stream",
            beads_dir=resolved_beads_dir,
            stream_count=None,
            repaired_files=(),
            error=error,
        )
        return (False, (), error)

    status = str(repair.get("status", ""))
    stream_count_value = repair.get("stream_count")
    stream_count = stream_count_value if isinstance(stream_count_value, int) else None
    error_value = repair.get("error")
    repair_error = str(error_value) if error_value else None
    if status == "invalid_stream":
        error = repair_error or "bead event manifest recount found invalid streams"
        _emit_manifest_repair(
            event_logger,
            status=status,
            beads_dir=resolved_beads_dir,
            stream_count=stream_count,
            repaired_files=(),
            error=error,
        )
        return (False, (), error)
    if status == "noop":
        _emit_manifest_repair(
            event_logger,
            status=status,
            beads_dir=resolved_beads_dir,
            stream_count=stream_count,
            repaired_files=(),
            error=None,
        )
        return (False, (), None)
    if status != "repaired":
        error = f"unknown bead event manifest recount status: {status or '<missing>'}"
        _emit_manifest_repair(
            event_logger,
            status=status or "unknown",
            beads_dir=resolved_beads_dir,
            stream_count=stream_count,
            repaired_files=(),
            error=error,
        )
        return (False, (), error)

    reported_path = Path(str(repair.get("manifest_path", manifest_path))).resolve()
    if reported_path != manifest_path.resolve():
        error = "bead event manifest recount returned a path outside its store"
        _emit_manifest_repair(
            event_logger,
            status="invalid_stream",
            beads_dir=resolved_beads_dir,
            stream_count=stream_count,
            repaired_files=(),
            error=error,
        )
        return (False, (), error)
    added = runner(
        repo_root,
        ["add", "--", relative_path],
        op=f"{op_prefix}.manifest_add",
    )
    if added.returncode != 0:
        error = format_git_error("could not stage repaired bead event manifest", added)
        return (False, (), error)
    changed = runner(
        repo_root,
        ["diff", "--cached", "--quiet", "--", relative_path],
        op=f"{op_prefix}.manifest_diff_cached",
    )
    if changed.returncode != 1:
        error = (
            "repaired bead event manifest produced no staged change"
            if changed.returncode == 0
            else format_git_error(
                "could not inspect repaired bead event manifest", changed
            )
        )
        return (False, (), error)
    committed = runner(
        repo_root,
        [
            "-c",
            "user.email=sase@localhost",
            "-c",
            "user.name=sase",
            "commit",
            "-m",
            "chore(beads): repair event manifest",
            "--",
            relative_path,
        ],
        op=f"{op_prefix}.manifest_commit",
    )
    if committed.returncode != 0:
        error = format_git_error(
            "could not commit repaired bead event manifest", committed
        )
        return (False, (), error)

    repaired_files = (relative_path,)
    _emit_manifest_repair(
        event_logger,
        status=status,
        beads_dir=resolved_beads_dir,
        stream_count=stream_count,
        repaired_files=repaired_files,
        error=None,
    )
    return (True, repaired_files, None)


def _emit_manifest_repair(
    logger: EventLogger | None,
    *,
    status: str,
    beads_dir: Path,
    stream_count: int | None,
    repaired_files: tuple[str, ...],
    error: str | None,
) -> None:
    if logger is not None:
        logger(
            "manifest_repair",
            status=status,
            beads_dir=str(beads_dir),
            stream_count=stream_count,
            repaired_files=list(repaired_files),
            error=error,
        )
