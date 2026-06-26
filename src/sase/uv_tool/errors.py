"""Typed errors for the ``uv tool`` engine, each carrying a renderable message.

The engine never prints; it raises these. Phase 2/3 CLI handlers catch them and
render ``str(err)`` (already an actionable, user-facing sentence) before exiting
non-zero. Keeping the message *on the exception* is the "crash with a good error
message" requirement from the epic.
"""

from __future__ import annotations

from collections.abc import Sequence

from sase.uv_tool.detect import NotUvToolInstall, NotUvToolReason

#: Where to point users who need to (re)install via uv.
_UV_INSTALL_HINT = "See https://docs.astral.sh/uv/ to install uv."

#: The canonical, supported install command.
_SASE_INSTALL_HINT = "Install sase with `uv tool install sase`."


class UvToolError(Exception):
    """Base class for all ``uv tool`` engine failures."""


class UvNotFoundError(UvToolError):
    """The ``uv`` binary is not available on ``PATH``."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or f"the `uv` command was not found on PATH. {_SASE_INSTALL_HINT} "
            f"{_UV_INSTALL_HINT}"
        )


class NotAUvToolInstallError(UvToolError):
    """``sase`` is not running from a managed ``uv tool install sase`` env.

    Built from a :class:`~sase.uv_tool.detect.NotUvToolInstall` so the rendered
    message is precise to the detected reason.
    """

    def __init__(self, result: NotUvToolInstall) -> None:
        self.result = result
        self.reason = result.reason
        super().__init__(_render_not_uv_tool(result))


class UvCommandFailedError(UvToolError):
    """A ``uv`` command ran but failed (non-zero exit, timeout, or OS error)."""

    def __init__(
        self,
        *,
        argv: Sequence[str],
        returncode: int | None = None,
        stderr: str | None = None,
        stdout: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.argv = tuple(argv)
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        self.timeout = timeout
        super().__init__(_render_command_failed(self))


class ReceiptError(UvToolError):
    """A ``uv-receipt.toml`` exists but could not be parsed into a model."""


def _render_not_uv_tool(result: NotUvToolInstall) -> str:
    if result.reason is NotUvToolReason.UV_MISSING:
        return (
            "sase cannot manage itself: the `uv` command was not found on PATH. "
            f"These commands require an install via `uv tool install sase`. "
            f"{_UV_INSTALL_HINT}"
        )
    if result.reason is NotUvToolReason.WRONG_PREFIX:
        return (
            "sase is not running from a `uv tool` install "
            f"(it is running from {result.sys_prefix}). "
            "`sase update` and `sase plugin install/update` only work when sase "
            f"was installed with `uv tool install sase`. {_SASE_INSTALL_HINT}"
        )
    return (
        f"sase's uv tool receipt was not found at {result.receipt_path}; the "
        "install looks incomplete. Try `uv tool install --force sase`."
    )


def _render_command_failed(error: UvCommandFailedError) -> str:
    command = " ".join(error.argv)
    if error.timeout is not None:
        return (
            f"`{command}` timed out after {error.timeout:g}s. "
            "Run it manually to see the full output."
        )
    detail = _first_nonempty_line(error.stderr, error.stdout)
    suffix = f": {detail}" if detail else ""
    code = "?" if error.returncode is None else str(error.returncode)
    return (
        f"`{command}` failed (exit {code}){suffix}. "
        "Run it manually to see the full output."
    )


def _first_nonempty_line(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


__all__ = [
    "NotAUvToolInstallError",
    "ReceiptError",
    "UvCommandFailedError",
    "UvNotFoundError",
    "UvToolError",
]
