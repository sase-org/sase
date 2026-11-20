"""Update-overlap reproducer: native code mapped across a file replacement.

Loading a real extension is impractical here (uv-managed Pythons build most
stdlib extensions in statically), so each child maps a plain data file the
way the dynamic loader maps ``sase_core_rs.abi3.so``. Every replacement runs
under the real code-swap writer lock on a sandbox lock file.

How the real install paths replace files (read-only survey, 2026-11-20):

* ``uv tool install --force --reinstall`` (``just install`` and
  ``just install-dev``) deletes and recreates the whole tool environment:
  every file is a new inode, and scripts and modules are briefly missing.
* Plain ``uv tool install`` (``sase dev update``) uninstalls, then installs,
  each changed distribution: new inodes, a shorter missing window.
* ``maturin develop`` (``rust-dev-install*``) removes the previously built
  module, then copies the new one into a new inode at the final path.
* The prebuild consumer and the LSP install write a temp file and rename it.
* ``git`` fast-forwards (``sase dev update``) unlink and recreate files.

None of them rewrites a live inode in place, which is the one mode below
that SIGBUSes a process that already mapped the file.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from sase.dev_update import prebuild_consumer
from tests.dev_update._swap_harness import (
    HARNESS_TIMEOUT_SECONDS,
    SwapSandbox,
    make_sandbox,
    mapped_payload,
    write_file,
)

_PAGE = 4096


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SwapSandbox:
    return make_sandbox(tmp_path, monkeypatch)


@pytest.fixture
def mapped(sandbox: SwapSandbox) -> Path:
    path = sandbox.root / "native" / "sase_core_rs.abi3.so"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(mapped_payload("v1"))
    return path


def _finish(sandbox: SwapSandbox, proc: subprocess.Popen[str]) -> tuple[int, str]:
    sandbox.release()
    stdout, _ = proc.communicate(timeout=HARNESS_TIMEOUT_SECONDS)
    return proc.returncode, stdout.strip()


# -- (e) in place versus by rename -------------------------------------------


def test_in_place_truncation_sigbuses_a_process_that_mapped_the_file(
    sandbox: SwapSandbox, mapped: Path
) -> None:
    """``cp new.so live.so`` opens with O_TRUNC: the mapping loses its pages."""
    reader = sandbox.start_mapped_reader(mapped)
    with sandbox.writer():
        os.truncate(mapped, 0)
        returncode, _ = _finish(sandbox, reader)

    assert returncode == -signal.SIGBUS


def test_completed_in_place_rewrite_changes_bytes_under_a_live_mapping(
    sandbox: SwapSandbox, mapped: Path
) -> None:
    """Even a finished in-place rewrite swaps the code under a live process."""
    reader = sandbox.start_mapped_reader(mapped)
    with sandbox.writer():
        write_file(mapped, mapped_payload("v2"), mode="in_place")
    returncode, stdout = _finish(sandbox, reader)

    assert returncode == 0
    assert stdout.startswith("mapped v2 ")


@pytest.mark.parametrize("mode", ["rename", "unlink_copy"])
def test_replacing_with_a_new_inode_preserves_a_live_mapping(
    sandbox: SwapSandbox, mapped: Path, mode: str
) -> None:
    """Rename (prebuild consumer) and unlink-then-copy (maturin, uv) are safe."""
    reader = sandbox.start_mapped_reader(mapped)
    with sandbox.writer():
        write_file(mapped, mapped_payload("v2"), mode=mode)
    returncode, stdout = _finish(sandbox, reader)

    assert returncode == 0
    assert stdout.startswith("mapped v1 ")
    assert mapped.read_bytes()[:2] == b"v2"


def test_prebuild_consumer_copy_preserves_a_live_mapping(
    sandbox: SwapSandbox, mapped: Path
) -> None:
    """The real prebuild install helper replaces the extension atomically."""
    prebuilt = sandbox.root / "prebuild" / mapped.name
    prebuilt.parent.mkdir(parents=True)
    prebuilt.write_bytes(mapped_payload("v2"))
    reader = sandbox.start_mapped_reader(mapped)
    with sandbox.writer():
        prebuild_consumer._copy_atomic(prebuilt, mapped)
    returncode, stdout = _finish(sandbox, reader)

    assert returncode == 0
    assert stdout.startswith("mapped v1 ")
    assert mapped.read_bytes()[:2] == b"v2"


@pytest.mark.skipif(sys.platform != "linux", reason="models the glibc loader")
def test_mapping_a_partially_copied_file_sigbuses_past_its_end(
    sandbox: SwapSandbox,
) -> None:
    """Models a process that loads the binding while it is still being copied.

    ``maturin develop`` removes the old module, then copies the new one into
    place, so a process that starts mid-copy finds either no module
    (``ModuleNotFoundError``) or a short file. The loader maps segments by the
    sizes in the ELF headers, not the file's current size; touching a page
    past the end of the short file raises SIGBUS. ``mmap.mmap`` refuses to
    map past EOF, so the child calls libc ``mmap`` directly.
    """
    partial = sandbox.root / "native" / "partial.abi3.so"
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(mapped_payload("v2")[:_PAGE])
    child = sandbox.root / "map_partial.py"
    child.write_text(
        "import ctypes, mmap, os\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mmap.restype = ctypes.c_void_p\n"
        "libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,"
        " ctypes.c_int, ctypes.c_int, ctypes.c_long]\n"
        f"fd = os.open({str(partial)!r}, os.O_RDONLY)\n"
        f"addr = libc.mmap(None, {4 * _PAGE}, mmap.PROT_READ, mmap.MAP_PRIVATE,"
        " fd, 0)\n"
        "assert addr not in (None, ctypes.c_void_p(-1).value)\n"
        "print('first page', ctypes.string_at(addr, 2).decode(), flush=True)\n"
        f"ctypes.string_at(addr + {3 * _PAGE}, 1)\n"
        "print('read past the end', flush=True)\n",
        encoding="utf-8",
    )
    with sandbox.writer():
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(child)],
            capture_output=True,
            text=True,
            timeout=HARNESS_TIMEOUT_SECONDS,
            check=False,
        )

    assert completed.stdout.strip() == "first page v2", completed.stderr
    assert completed.returncode == -signal.SIGBUS
