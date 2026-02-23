"""Shared command-runner mixin for VCS plugin implementations."""

import subprocess
import sys
from typing import TextIO

from ._types import CommandOutput


class CommandRunner:
    """Mixin providing subprocess helpers used by VCS plugins.

    Extracted from the identical ``_run`` / ``_run_shell`` / ``_to_result``
    helpers shared by :class:`_GitProvider` and :class:`_HgProvider`.
    """

    def _run(
        self,
        cmd: list[str],
        cwd: str,
        *,
        timeout: int = 300,
        capture_output: bool = True,
    ) -> CommandOutput:
        """Run a subprocess command and return a :class:`CommandOutput`."""
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=capture_output,
                text=True,
                check=False,
                timeout=timeout,
            )
            return CommandOutput(result.returncode, result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            return CommandOutput(1, "", f"{cmd[0]} timed out")
        except FileNotFoundError:
            return CommandOutput(1, "", f"{cmd[0]} command not found")
        except Exception as e:
            return CommandOutput(1, "", f"Error running {cmd[0]}: {e}")

    def _run_shell(self, cmd: str, cwd: str, *, timeout: int = 300) -> CommandOutput:
        """Run a shell command string and return a :class:`CommandOutput`."""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            return CommandOutput(result.returncode, result.stdout, result.stderr)
        except subprocess.TimeoutExpired:
            return CommandOutput(1, "", "Command timed out")
        except Exception as e:
            return CommandOutput(1, "", f"Error: {e}")

    def _run_streaming(
        self,
        cmd: list[str],
        cwd: str,
        *,
        timeout: int = 300,
        stream_to: TextIO | None = None,
    ) -> CommandOutput:
        """Run a command, streaming combined output in real-time.

        The output is tee'd: each line is written to *stream_to* so the caller
        can see progress, and also collected so it can be returned in the
        :class:`CommandOutput` for error checking.

        *stream_to* defaults to ``sys.stderr`` (preserving existing sync
        behaviour).
        """
        dest = stream_to if stream_to is not None else sys.stderr
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert proc.stdout is not None  # for mypy
            collected: list[str] = []
            for line in proc.stdout:
                dest.write(line)
                dest.flush()
                collected.append(line)
            proc.wait(timeout=timeout)
            return CommandOutput(proc.returncode, "".join(collected), "")
        except subprocess.TimeoutExpired:
            proc.kill()  # type: ignore[possibly-undefined]
            return CommandOutput(1, "", f"{cmd[0]} timed out")
        except FileNotFoundError:
            return CommandOutput(1, "", f"{cmd[0]} command not found")
        except Exception as e:
            return CommandOutput(1, "", f"Error running {cmd[0]}: {e}")

    def _to_result(self, out: CommandOutput, op_name: str) -> tuple[bool, str | None]:
        """Convert a :class:`CommandOutput` to ``(success, error_or_none)``."""
        if out.success:
            return (True, None)
        error_msg = out.stderr.strip() or out.stdout.strip()
        return (
            False,
            f"{op_name} failed: {error_msg}" if error_msg else f"{op_name} failed",
        )
