"""Shared fixtures for ``tools/fix_tui_screenshots`` tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
import struct
import subprocess
import zlib

from tests.ace.tui.visual._visual_capture import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    VisualCaptureRoots,
    VisualCaptureSession,
    WorkerSessionRecord,
    merge_capture_dir,
    write_inventory,
)
from tests.ace.tui.visual._visual_maintenance import MaintenanceHooks


ACE_NODE = "tests/ace/tui/visual/test_a.py::test_a"
PAGER_NODE = "tests/pager/visual/test_b.py::test_b"


def make_png(
    width: int,
    height: int,
    rgba: tuple[int, int, int, int] = (255, 0, 0, 255),
    *,
    compress: int = 9,
    pixels: Sequence[tuple[int, int, int, int]] | None = None,
) -> bytes:
    """Return a minimal RGBA PNG without importing Pillow."""
    if pixels is None:
        raw = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))
    else:
        rows = []
        index = 0
        for _ in range(height):
            row = bytearray(b"\x00")
            for _col in range(width):
                row.extend(bytes(pixels[index]))
                index += 1
            rows.append(bytes(row))
        raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, compress))
        + chunk(b"IEND", b"")
    )


def encoding_pair(
    width: int = 1,
    height: int = 1,
    rgba: tuple[int, int, int, int] = (255, 0, 0, 255),
) -> tuple[bytes, bytes]:
    """Return two PNG encodings of the same pixels."""
    left = make_png(width, height, rgba, compress=0)
    right = make_png(width, height, rgba, compress=9)
    assert left != right
    return left, right


def write_golden(repo: Path, identity: str, name: str, data: bytes) -> Path:
    root = DEFAULT_ACE_ROOT if identity == "ace" else DEFAULT_PAGER_ROOT
    path = repo / root / name
    if not name.endswith(".png"):
        path = path.with_suffix(".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def init_repo(root: Path) -> Path:
    """Create a git repo with ACE and pager golden roots."""
    (root / DEFAULT_ACE_ROOT).mkdir(parents=True)
    (root / DEFAULT_PAGER_ROOT).mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "sase-test@example.invalid")
    _git(root, "config", "user.name", "SASE Test")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
    )
    return root


def commit_all(root: Path, message: str = "goldens") -> None:
    _git(root, "add", "-A")
    _git(
        root,
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        message,
    )


def git_index(root: Path) -> str:
    return _git(
        root,
        "ls-files",
        "-s",
        "--",
        DEFAULT_ACE_ROOT,
        DEFAULT_PAGER_ROOT,
    ).stdout


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


@dataclass
class ScriptedCapture:
    node_id: str
    name: str
    identity: str
    png: bytes
    svg: str | None = "<svg/>"


@dataclass
class AttemptScript:
    """One scripted pytest-pass outcome for :class:`FakeRunner`.

    Non-verify passes consume scripts in call order; when the scripts run
    out, a default all-passing script with ``exit_code`` is used. Verify
    passes keep the legacy behavior (``fail_verify``/``verify_png``).
    """

    exit_code: int = 0
    failed: tuple[str, ...] = ()
    errored: tuple[str, ...] = ()
    unexecuted: tuple[str, ...] = ()
    incomplete: bool = False
    no_inventory: bool = False
    session_exitstatus: int | None = None
    pngs: dict[str, bytes] = field(default_factory=dict)


@dataclass
class FakeRunner:
    """Write capture-protocol records without invoking the visual suite."""

    captures: list[ScriptedCapture]
    repo_root: Path
    exit_code: int = 0
    fail_verify: bool = False
    verify_png: bytes | None = None
    attempts: list[AttemptScript] = field(default_factory=list)
    calls: list[dict[str, object]] = field(default_factory=list)

    def __call__(
        self,
        *,
        repo_root: Path,
        capture_dir: Path,
        run_id: str,
        scope: str,
        pytest_args: Sequence[str],
        log_path: Path,
        ace_root: Path,
        pager_root: Path,
        workers: int | None = None,
    ) -> int:
        self.calls.append(
            {
                "run_id": run_id,
                "scope": scope,
                "pytest_args": tuple(pytest_args),
                "capture_dir": capture_dir,
                "workers": workers,
            }
        )
        if str(run_id).endswith("-verify"):
            return self._write_pass(
                AttemptScript(),
                repo_root=repo_root,
                capture_dir=capture_dir,
                run_id=str(run_id),
                scope=scope,
                pytest_args=pytest_args,
                log_path=log_path,
                ace_root=ace_root,
                pager_root=pager_root,
                verify=True,
            )
        index = (
            sum(1 for call in self.calls if not str(call["run_id"]).endswith("-verify"))
            - 1
        )
        if index < len(self.attempts):
            script = self.attempts[index]
        else:
            script = AttemptScript(exit_code=self.exit_code)
        return self._write_pass(
            script,
            repo_root=repo_root,
            capture_dir=capture_dir,
            run_id=str(run_id),
            scope=scope,
            pytest_args=pytest_args,
            log_path=log_path,
            ace_root=ace_root,
            pager_root=pager_root,
            verify=False,
        )

    def _write_pass(
        self,
        script: AttemptScript,
        *,
        repo_root: Path,
        capture_dir: Path,
        run_id: str,
        scope: str,
        pytest_args: Sequence[str],
        log_path: Path,
        ace_root: Path,
        pager_root: Path,
        verify: bool,
    ) -> int:
        if verify and self.fail_verify:
            log_path.write_text("fake visual pytest\n", encoding="utf-8")
            return 1
        lines = ["fake visual pytest"]
        for node_id in (*script.failed, *script.errored):
            outcome = "FAILED" if node_id in script.failed else "ERROR"
            lines.append(f"{outcome} {node_id} - simulated failure")
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if script.no_inventory:
            return script.exit_code
        selected = list(self.captures)
        node_ids = [arg for arg in pytest_args if "::" in arg]
        if node_ids:
            selected = [item for item in selected if item.node_id in node_ids]
        excluded = set(script.errored) | set(script.unexecuted)
        roots = VisualCaptureRoots(ace=ace_root, pager=pager_root)
        session = VisualCaptureSession(
            capture_dir=capture_dir,
            run_id=run_id,
            worker_id="controller",
            repo_root=repo_root,
            roots=roots,
        )
        executed: list[str] = []
        for item in selected:
            if item.node_id in excluded:
                continue
            png = script.pngs.get(item.node_id, item.png)
            if verify and self.verify_png is not None:
                png = self.verify_png
            snapshot_root = ace_root if item.identity == "ace" else pager_root
            session.record_capture(
                name=item.name,
                png_bytes=png,
                snapshot_root=snapshot_root,
                node_id=item.node_id,
                source_svg=item.svg,
            )
            executed.append(item.node_id)
        collected: tuple[str, ...]
        if scope == "full":
            collected = (ACE_NODE, PAGER_NODE)
            if not executed:
                executed = list(collected)
            else:
                executed = sorted(set(executed).union(collected))
        else:
            collected = tuple(sorted(set(executed))) or (ACE_NODE,)
        if script.unexecuted:
            collected = tuple(sorted(set(collected) | set(script.unexecuted)))
        exitstatus = (
            script.session_exitstatus
            if script.session_exitstatus is not None
            else script.exit_code
        )
        session.write_worker_session(
            WorkerSessionRecord(
                run_id=run_id,
                worker_id="controller",
                completed=not script.incomplete,
                collectonly=False,
                exitstatus=exitstatus,
                collected_node_ids=collected,
                executed_node_ids=tuple(executed),
                skipped_node_ids=(),
                xfailed_node_ids=(),
                xpassed_node_ids=(),
                failed_node_ids=tuple(script.failed),
                error_node_ids=tuple(script.errored),
                deselected_node_ids=(),
                capture_count=len(session.captures),
            )
        )
        inventory = merge_capture_dir(
            capture_dir,
            run_id=run_id,
            requested_scope=scope,
            expected_workers=("controller",),
            session_exitstatus=exitstatus,
        )
        write_inventory(capture_dir, inventory)
        if verify:
            return 0
        return script.exit_code


def silent_hooks(runner: FakeRunner, *, ci: bool = False) -> MaintenanceHooks:
    return MaintenanceHooks(
        preflight=lambda _update: None,
        run_pytest=runner,
        is_ci=lambda _env: ci,
        renderer_identity=lambda: {"packages": {}, "fonts": {}},
    )
