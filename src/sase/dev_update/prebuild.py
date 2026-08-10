"""Best-effort Rust artifact prebuild cache for editable dev updates."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.dev_update.models import DevCommandResult, DevCommandRunner
from sase.dev_update.prebuild_cache import (
    EXTENSION_FILENAME,
    LSP_BINARY_NAME,
    SCHEMA_VERSION,
    RustPrebuildConsumeOutcome as _RustPrebuildConsumeOutcome,
    RustPrebuildProvenance as _RustPrebuildProvenance,
    completed_stamps as _completed_stamps,
    current_provenance as _current_provenance,
    outcome_marker as _outcome_marker,
    parse_outcome_marker,
    sha256_file as _sha256_file,
)
from sase.dev_update.prebuild_consumer import (
    consume_prebuild as _consume_prebuild_impl,
)
from sase.dev_update.prebuild_producer import (
    ensure_mirror as _ensure_mirror,
    produce_prebuild as _produce_prebuild_impl,
)
from sase.noninteractive_subprocess import run_noninteractive
from sase.version._git import classify_git_upstream

log = logging.getLogger(__name__)

# A background cargo build is the longest command here, and a wedged one would
# otherwise hold the producer lock forever and silently disable the cache.
COMMAND_TIMEOUT_SECONDS = 3600.0

CommandRunner = DevCommandRunner
Launcher = Callable[..., object]


def _cache_root() -> Path:
    """Return the production Rust prebuild cache root."""
    return sase_subdir("cache") / "rust-prebuild"


def schedule_rust_prebuild(
    status: Any,
    config: Any,
    *,
    launcher: Launcher | None = None,
    python: str | None = None,
) -> bool:
    """Launch one detached producer for the editable core update, if eligible."""
    if not getattr(config, "prebuild_rust", True):
        return False
    component = _editable_core_component(status)
    if component is None:
        return False
    source_root = getattr(component, "source_root", None)
    upstream_ref = getattr(component, "upstream_ref", None)
    if not source_root or not upstream_ref:
        return False
    executable = python or sys.executable
    argv = [
        executable,
        "-m",
        "sase.dev_update.prebuild",
        "produce",
        "--source-root",
        source_root,
        "--upstream-ref",
        upstream_ref,
        "--python",
        executable,
    ]
    launch = launcher or subprocess.Popen
    try:
        launch(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        log.debug("Failed to launch Rust prebuild producer", exc_info=True)
        return False
    return True


def _editable_core_component(status: Any) -> Any | None:
    """Return the editable core component from an update snapshot, if present."""
    for component in getattr(status, "components", ()):
        if (
            getattr(component, "role", None) == "core"
            and getattr(component, "install_type", None) == "editable"
            and getattr(component, "source_root", None)
            and getattr(component, "upstream_ref", None)
        ):
            return component
    return None


def _produce_prebuild(
    *,
    source_root: Path,
    upstream_ref: str,
    target_python: str,
    profile: str | None = None,
    root: Path | None = None,
    run: CommandRunner | None = None,
    which: Callable[[str], str | None] = shutil.which,
    now: Callable[[], float] = time.time,
) -> _RustPrebuildConsumeOutcome:
    """Build and stamp a cache set for the observed upstream commit."""
    return _produce_prebuild_impl(
        source_root=source_root,
        upstream_ref=upstream_ref,
        target_python=target_python,
        profile=profile,
        root=root,
        run=run or _run_command,
        which=which,
        now=now,
        cache_root=_cache_root,
        code_swap_writer_active=_code_swap_writer_active,
        classify_upstream=classify_git_upstream,
    )


def _consume_prebuild(
    *,
    core_root: Path,
    host_root: Path,
    target_python: str,
    profile: str | None = None,
    root: Path | None = None,
    config: Mapping[str, Any] | None = None,
    run: CommandRunner | None = None,
    replace_file: Callable[[Path, Path], None] = os.replace,
) -> _RustPrebuildConsumeOutcome:
    """Install a matching prebuilt set, or return a precise miss reason."""
    return _consume_prebuild_impl(
        core_root=core_root,
        host_root=host_root,
        target_python=target_python,
        profile=profile,
        root=root or _cache_root(),
        config=config,
        run=run or _run_command,
        replace_file=replace_file,
    )


def _code_swap_writer_active() -> bool:
    """Best-effort non-blocking probe for the active update writer holder."""
    lock_path = sase_subdir("locks") / "code-swap.lock"
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not raw:
        return False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return True
    return isinstance(payload, dict) and payload.get("op") == "dev.update"


def _run_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> DevCommandResult:
    command_env = None if env is None else {**os.environ, **dict(env)}
    try:
        completed = run_noninteractive(
            list(argv),
            cwd=cwd,
            env=command_env,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        return DevCommandResult(127, stderr=str(exc))
    except subprocess.TimeoutExpired:
        return DevCommandResult(124, stderr="command timed out")
    except OSError as exc:
        return DevCommandResult(1, stderr=str(exc))
    return DevCommandResult(
        completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    produce = subparsers.add_parser("produce")
    produce.add_argument("--source-root", required=True)
    produce.add_argument("--upstream-ref", required=True)
    produce.add_argument("--python", required=True)
    produce.add_argument("--profile")
    consume = subparsers.add_parser("consume")
    consume.add_argument("--core-root", required=True)
    consume.add_argument("--host-root", required=True)
    consume.add_argument("--python", required=True)
    consume.add_argument("--profile")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "produce":
        _produce_prebuild(
            source_root=Path(args.source_root),
            upstream_ref=args.upstream_ref,
            target_python=args.python,
            profile=args.profile,
        )
        return 0
    outcome = _consume_prebuild(
        core_root=Path(args.core_root),
        host_root=Path(args.host_root),
        target_python=args.python,
        profile=args.profile,
    )
    print(_outcome_marker(outcome))
    return 0 if outcome.hit else 1


if __name__ == "__main__":
    raise SystemExit(main())
