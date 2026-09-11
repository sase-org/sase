"""Generate, write, and zcompile completion scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.completion.install_models import ExpectedCompletion, ZcompileFn
from sase.completion.install_targets import (
    CompletionInstallError,
    ZSH_PROBE_TIMEOUT_SECONDS,
)


@dataclass(frozen=True, slots=True)
class _ScriptPublication:
    """A staged script publication result."""

    wrote_script: bool


def completion_payload(text: str) -> str:
    """Return generated completion text with the on-disk trailing newline."""
    return text if text.endswith("\n") else f"{text}\n"


def zwc_path(script: Path) -> Path:
    """Return the ``zcompile`` output path for *script*."""
    return script.with_name(f"{script.name}.zwc")


def zwc_freshness(shell: str, script: Path) -> str:
    """Return ``fresh`` / ``stale`` / ``missing`` / ``n/a`` for *script*."""
    if shell != "zsh":
        return "n/a"
    compiled = zwc_path(script)
    try:
        if not compiled.is_file():
            return "missing"
        if not script.is_file():
            return "stale"
        if compiled.stat().st_mtime < script.stat().st_mtime:
            return "stale"
    except OSError:
        return "missing"
    return "fresh"


def emit_script_and_digest(shell: str) -> tuple[str, str]:
    """Build the live spec once and return ``(script, digest)`` for *shell*."""
    expected = expected_scripts_for_shells((shell,))[shell]
    return expected.script, expected.digest


def expected_scripts_for_shells(
    shells: Sequence[str],
) -> Mapping[str, ExpectedCompletion]:
    """Build the live spec once and emit current completion scripts for *shells*."""
    from sase.completion.build import build_spec

    spec = build_spec()
    digest = spec.structural_digest()
    return {
        shell: ExpectedCompletion(_emit_script(shell, spec), digest) for shell in shells
    }


def _emit_script(shell: str, spec: object) -> str:
    """Emit the current completion script for *shell* from *spec*."""
    from sase.completion.model import CompletionSpec

    if not isinstance(spec, CompletionSpec):
        raise CompletionInstallError("completion spec has an unexpected type")

    if shell == "bash":
        from sase.completion.emit_bash import emit_bash

        return emit_bash(spec)
    elif shell == "fish":
        from sase.completion.emit_fish import emit_fish

        return emit_fish(spec)
    elif shell == "zsh":
        from sase.completion.emit_zsh import emit_zsh

        return emit_zsh(spec)
    else:
        raise CompletionInstallError(f"unsupported shell: {shell}")


def _zcompile_script(
    path: Path,
    *,
    timeout: float = ZSH_PROBE_TIMEOUT_SECONDS,
    zsh: str | None = None,
) -> None:
    """``zcompile`` *path*. Mandatory for zsh; not an optimization."""
    binary = zsh or shutil.which("zsh")
    if binary is None:
        raise CompletionInstallError("zsh is not on PATH; cannot zcompile")
    try:
        completed = subprocess.run(
            [binary, "-c", "zcompile -U -- $1", "sase-zcompile", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CompletionInstallError(f"zcompile timed out for {path}") from exc
    except OSError as exc:
        raise CompletionInstallError(f"zcompile failed for {path}: {exc}") from exc
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "unknown error").strip()
        raise CompletionInstallError(f"zcompile failed for {path}: {err}")


def publish_script(
    script: Path,
    text: str,
    *,
    shell: str,
    zcompile_fn: ZcompileFn | None,
) -> _ScriptPublication:
    """Stage and publish generated completion bytes for one shell."""
    script.parent.mkdir(parents=True, exist_ok=True)
    payload = completion_payload(text)
    tmp = script.with_name(f".{script.name}.{os.getpid()}.tmp")
    tmp_zwc = zwc_path(tmp)
    final_zwc = zwc_path(script)
    wrote_script = False
    try:
        tmp.write_text(payload, encoding="utf-8")
        if shell == "zsh":
            try:
                (zcompile_fn or _zcompile_script)(tmp)
            except OSError as exc:
                raise CompletionInstallError(
                    f"zcompile failed for {tmp}: {exc}"
                ) from exc
            if not tmp_zwc.is_file():
                raise CompletionInstallError(f"zcompile did not create {tmp_zwc}")

        current = read_text(script)
        if current != payload:
            os.replace(tmp, script)
            wrote_script = True
        else:
            tmp.unlink(missing_ok=True)

        if shell == "zsh":
            os.replace(tmp_zwc, final_zwc)
    except Exception:
        tmp.unlink(missing_ok=True)
        tmp_zwc.unlink(missing_ok=True)
        raise
    return _ScriptPublication(wrote_script=wrote_script)


def read_text(path: Path) -> str | None:
    """Return text for *path*, or ``None`` when it is absent or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
