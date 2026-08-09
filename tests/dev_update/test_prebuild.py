"""Tests for the Rust prebuild cache."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.dev_update import prebuild
from sase.dev_update.models import DevCommandResult
from sase.version._git import GitUpstreamStatus


COMMIT = "b" * 40


class FakeRunner:
    def __init__(self, *, core_root: Path, python: str = "/tool/bin/python") -> None:
        self.core_root = core_root
        self.python = python
        self.calls: list[
            tuple[tuple[str, ...], Path | None, dict[str, str] | None]
        ] = []
        self.rustc = "rustc 1.90.0"
        self.probe_ok = True

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> DevCommandResult:
        command = tuple(argv)
        self.calls.append((command, cwd, dict(env) if env is not None else None))
        if command[:3] == ("git", "-C", str(self.core_root)):
            return DevCommandResult(0, stdout=f"{COMMIT}\n")
        if command == ("rustc", "--version"):
            return DevCommandResult(0, stdout=f"{self.rustc}\n")
        if command[:2] == (self.python, "-c"):
            script = command[2]
            if "sysconfig.get_config_var" in script:
                return DevCommandResult(
                    0,
                    stdout=json.dumps(
                        {
                            "executable": self.python,
                            "abi": "cpython-312-x86_64-linux-gnu",
                        }
                    ),
                )
            if "import sase_core_rs" in script:
                return DevCommandResult(0 if self.probe_ok else 1, stderr="bad import")
        if (
            command[:1] == (self.python,)
            and "purge_sase_core_rs_extensions" in command[-1]
        ):
            return DevCommandResult(0)
        return DevCommandResult(0)


def _provenance(
    core_root: Path,
    runner: FakeRunner,
) -> prebuild._RustPrebuildProvenance:  # noqa: SLF001
    value = prebuild._current_provenance(  # noqa: SLF001
        core_root,
        core_commit=COMMIT,
        target_python=runner.python,
        profile="dev-update",
        run=runner,
    )
    assert value is not None
    return value


def _write_completed_set(
    root: Path,
    provenance: prebuild._RustPrebuildProvenance,  # noqa: SLF001
    *,
    key: str = "set",
    extension_bytes: bytes = b"extension",
    lsp_bytes: bytes = b"lsp",
) -> Path:
    set_dir = root / "sets" / key
    artifacts = set_dir / "artifacts"
    artifacts.mkdir(parents=True)
    extension = artifacts / prebuild.EXTENSION_FILENAME
    lsp = artifacts / prebuild.LSP_BINARY_NAME
    extension.write_bytes(extension_bytes)
    lsp.write_bytes(lsp_bytes)
    lsp.chmod(0o755)
    stamp = {
        "schema_version": prebuild.SCHEMA_VERSION,
        **provenance.__dict__,
        "artifacts": {
            "extension": {
                "path": str(extension.relative_to(set_dir)),
                "sha256": prebuild._sha256_file(extension),  # noqa: SLF001
            },
            "lsp": {
                "path": str(lsp.relative_to(set_dir)),
                "sha256": prebuild._sha256_file(lsp),  # noqa: SLF001
            },
        },
    }
    (set_dir / "stamp.json").write_text(json.dumps(stamp), encoding="utf-8")
    return set_dir


def test_schedule_rust_prebuild_launches_detached_producer() -> None:
    status = SimpleNamespace(
        components=(
            SimpleNamespace(
                role="core",
                install_type="editable",
                source_root="/repo/sase-core",
                upstream_ref="origin/main",
            ),
        )
    )
    config = SimpleNamespace(prebuild_rust=True)
    calls: list[tuple[list[str], dict[str, object]]] = []

    launched = prebuild.schedule_rust_prebuild(
        status,
        config,
        launcher=lambda argv, **kwargs: calls.append((argv, kwargs)),
        python="/tool/bin/python",
    )

    assert launched is True
    assert calls == [
        (
            [
                "/tool/bin/python",
                "-m",
                "sase.dev_update.prebuild",
                "produce",
                "--source-root",
                "/repo/sase-core",
                "--upstream-ref",
                "origin/main",
                "--python",
                "/tool/bin/python",
            ],
            {
                "stdin": prebuild.subprocess.DEVNULL,
                "stdout": prebuild.subprocess.DEVNULL,
                "stderr": prebuild.subprocess.DEVNULL,
                "start_new_session": True,
                "close_fds": True,
            },
        )
    ]


def test_schedule_rust_prebuild_skips_when_disabled_or_no_editable_core() -> None:
    calls: list[object] = []

    disabled = prebuild.schedule_rust_prebuild(
        SimpleNamespace(components=()),
        SimpleNamespace(prebuild_rust=False),
        launcher=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    no_core = prebuild.schedule_rust_prebuild(
        SimpleNamespace(components=()),
        SimpleNamespace(prebuild_rust=True),
        launcher=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert disabled is False
    assert no_core is False
    assert calls == []


def test_consume_matching_set_installs_artifacts_atomically(tmp_path: Path) -> None:
    core = tmp_path / "sase-core"
    host = tmp_path / "sase"
    core_dest = core / "crates/sase_core_py/python/sase_core_rs"
    core_dest.mkdir(parents=True)
    (core / "Cargo.lock").write_text("lock", encoding="utf-8")
    (host / "tools").mkdir(parents=True)
    python = str(tmp_path / "tool/bin/python")
    Path(python).parent.mkdir(parents=True)
    runner = FakeRunner(core_root=core, python=python)
    provenance = _provenance(core, runner)
    cache = tmp_path / "cache"
    _write_completed_set(cache, provenance)
    replacements: list[tuple[Path, Path]] = []

    def replace_file(src: Path, dest: Path) -> None:
        assert src.name.startswith(".")
        replacements.append((src, dest))
        os.replace(src, dest)

    outcome = prebuild._consume_prebuild(  # noqa: SLF001
        core_root=core,
        host_root=host,
        target_python=python,
        root=cache,
        config={"ace": {"updates": {"prebuild_rust": True}}},
        run=runner,
        replace_file=replace_file,
    )

    assert outcome.hit is True
    assert (core_dest / prebuild.EXTENSION_FILENAME).read_bytes() == b"extension"
    lsp = Path(python).parent / prebuild.LSP_BINARY_NAME
    assert lsp.read_bytes() == b"lsp"
    assert lsp.stat().st_mode & stat.S_IXUSR
    assert [dest.name for _src, dest in replacements] == [
        prebuild.EXTENSION_FILENAME,
        prebuild.LSP_BINARY_NAME,
    ]


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("core_commit", "commit-mismatch"),
        ("cargo_lock_sha256", "lockfile-mismatch"),
        ("rustc_version", "rustc-mismatch"),
        ("profile", "profile-mismatch"),
        ("target_interpreter", "interpreter-mismatch"),
        ("python_abi", "abi-mismatch"),
    ],
)
def test_consume_reports_exact_provenance_mismatch(
    tmp_path: Path,
    field: str,
    reason: str,
) -> None:
    core = tmp_path / "sase-core"
    host = tmp_path / "sase"
    core.mkdir()
    host.mkdir()
    (core / "Cargo.lock").write_text("lock", encoding="utf-8")
    python = "/tool/bin/python"
    runner = FakeRunner(core_root=core, python=python)
    provenance = _provenance(core, runner)
    changed = prebuild._RustPrebuildProvenance(  # noqa: SLF001
        **{**provenance.__dict__, field: "different"}
    )
    cache = tmp_path / "cache"
    _write_completed_set(cache, changed)

    outcome = prebuild._consume_prebuild(  # noqa: SLF001
        core_root=core,
        host_root=host,
        target_python=python,
        root=cache,
        config={"ace": {"updates": {"prebuild_rust": True}}},
        run=runner,
    )

    assert outcome.hit is False
    assert outcome.reason == reason


def test_consume_digest_mismatch_happens_before_copy(tmp_path: Path) -> None:
    core = tmp_path / "sase-core"
    host = tmp_path / "sase"
    core.mkdir()
    host.mkdir()
    (core / "Cargo.lock").write_text("lock", encoding="utf-8")
    python = "/tool/bin/python"
    runner = FakeRunner(core_root=core, python=python)
    provenance = _provenance(core, runner)
    set_dir = _write_completed_set(tmp_path / "cache", provenance)
    (set_dir / "artifacts" / prebuild.EXTENSION_FILENAME).write_bytes(b"changed")

    outcome = prebuild._consume_prebuild(  # noqa: SLF001
        core_root=core,
        host_root=host,
        target_python=python,
        root=tmp_path / "cache",
        config={"ace": {"updates": {"prebuild_rust": True}}},
        run=runner,
        replace_file=lambda _src, _dest: pytest.fail("copy must not start"),
    )

    assert outcome.hit is False
    assert outcome.reason == "digest-mismatch"


def test_consume_disabled_config_misses_without_probing(tmp_path: Path) -> None:
    core = tmp_path / "sase-core"
    core.mkdir()
    runner = FakeRunner(core_root=core)

    outcome = prebuild._consume_prebuild(  # noqa: SLF001
        core_root=core,
        host_root=tmp_path,
        target_python=runner.python,
        root=tmp_path / "cache",
        config={"ace": {"updates": {"prebuild_rust": False}}},
        run=runner,
    )

    assert outcome.reason == "disabled"
    assert runner.calls == []


def test_ensure_mirror_uses_local_live_checkout_and_observed_commit(
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    mirror = tmp_path / "mirror"
    runner = FakeRunner(core_root=live)

    assert prebuild._ensure_mirror(live, mirror, COMMIT, runner) is True  # noqa: SLF001

    commands = [call[0] for call in runner.calls]
    assert commands == [
        ("git", "clone", "--shared", "--no-checkout", str(live), str(mirror)),
        ("git", "-C", str(mirror), "fetch", "--quiet", "--no-tags", str(live), COMMIT),
        ("git", "-C", str(mirror), "checkout", "--force", "--detach", COMMIT),
    ]


def test_producer_lock_refuses_overlap(tmp_path: Path) -> None:
    lock = tmp_path / "prebuild.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner = FakeRunner(core_root=tmp_path / "live")

        outcome = prebuild._produce_prebuild(  # noqa: SLF001
            source_root=tmp_path / "live",
            upstream_ref="origin/main",
            target_python=runner.python,
            root=tmp_path,
            run=runner,
        )
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    assert outcome.hit is False
    assert runner.calls == []


def test_produce_refuses_while_update_writer_lock_held(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    (locks_dir / "code-swap.lock").write_text(
        json.dumps({"pid": 999, "op": "dev.update", "command": [], "blocking": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(prebuild, "sase_subdir", lambda name: tmp_path / name)
    runner = FakeRunner(core_root=tmp_path / "live")

    outcome = prebuild._produce_prebuild(  # noqa: SLF001
        source_root=tmp_path / "live",
        upstream_ref="origin/main",
        target_python=runner.python,
        root=tmp_path / "cache",
        run=runner,
    )

    assert outcome.hit is False
    assert runner.calls == []


def test_successful_producer_writes_stamp_last_and_prunes_to_two(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    live = tmp_path / "live"
    live.mkdir()
    mirror = tmp_path / "cache" / "sase-core"
    python = "/tool/bin/python"

    def classify(_root: Path) -> GitUpstreamStatus:
        return GitUpstreamStatus(
            root=str(live),
            upstream="origin/main",
            remote="origin",
            remote_branch="main",
            detached=False,
            dirty=False,
            ahead=0,
            behind=1,
        )

    monkeypatch.setattr(prebuild, "classify_git_upstream", classify)

    class BuildRunner(FakeRunner):
        def __call__(
            self,
            argv: Sequence[str],
            *,
            cwd: Path | None = None,
            env: Mapping[str, str] | None = None,
        ) -> DevCommandResult:
            command = tuple(argv)
            if command[:2] == ("git", "clone"):
                mirror.mkdir(parents=True)
                (mirror / ".git").mkdir()
                (mirror / "Cargo.lock").write_text("lock", encoding="utf-8")
            if "maturin" in command:
                assert cwd == mirror / "crates" / "sase_core_py"
                assert env is not None
                dist = Path(env["CARGO_TARGET_DIR"]).parents[1] / "dist"
                dist.mkdir(parents=True, exist_ok=True)
                wheel = dist / "sase_core_rs-0.0.0-cp312-abi3-linux.whl"
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr(
                        f"sase_core_rs/{prebuild.EXTENSION_FILENAME}",
                        b"extension",
                    )
            if command[:4] == ("ionice", "-c", "3", "nice") and "cargo" in command:
                assert env is not None
                target = Path(env["CARGO_TARGET_DIR"])
                lsp = target / "dev-update" / prebuild.LSP_BINARY_NAME
                lsp.parent.mkdir(parents=True)
                lsp.write_bytes(b"lsp")
            return super().__call__(argv, cwd=cwd, env=env)

    runner = BuildRunner(core_root=live, python=python)
    for idx in range(2):
        old = tmp_path / "cache" / "sets" / f"old{idx}"
        old.mkdir(parents=True)
        (old / "stamp.json").write_text(
            json.dumps({"schema_version": prebuild.SCHEMA_VERSION}),
            encoding="utf-8",
        )

    outcome = prebuild._produce_prebuild(  # noqa: SLF001
        source_root=live,
        upstream_ref="origin/main",
        target_python=python,
        root=tmp_path / "cache",
        run=runner,
        which=lambda name: f"/usr/bin/{name}",
    )

    assert outcome.hit is True
    assert outcome.set_key is not None
    completed = prebuild._completed_stamps(tmp_path / "cache")  # noqa: SLF001
    assert len(completed) == 2
    produced = tmp_path / "cache" / "sets" / outcome.set_key
    assert (produced / "stamp.json").is_file()
    assert (
        produced / "artifacts" / prebuild.EXTENSION_FILENAME
    ).read_bytes() == b"extension"


def test_run_command_bounds_builds_and_maps_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_noninteractive(
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append({"argv": tuple(argv), "cwd": cwd, "env": env, "timeout": timeout})
        raise subprocess.TimeoutExpired(list(argv), timeout or 0.0)

    monkeypatch.setattr(prebuild, "run_noninteractive", fake_run_noninteractive)

    result = prebuild._run_command(("cargo", "build"))  # noqa: SLF001

    assert result.returncode == 124
    assert result.stderr == "command timed out"
    assert calls == [
        {
            "argv": ("cargo", "build"),
            "cwd": None,
            "env": None,
            "timeout": prebuild.COMMAND_TIMEOUT_SECONDS,
        }
    ]
