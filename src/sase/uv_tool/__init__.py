"""Shared ``uv tool`` engine for sase self-update and plugin management.

One engine backs all three frontend commands (``sase update``, ``sase plugin
install``, ``sase plugin update``) so detection, receipt parsing, argv building,
and uv output parsing can never drift (epic decision *D1*). The package keeps a
clean seam: everything is pure logic except :mod:`sase.uv_tool.runner`, the lone
subprocess boundary.

This is frontend-specific packaging behavior and intentionally stays in Python
(decision *D6*): no ``sase-core`` (Rust) involvement.
"""

from __future__ import annotations

from sase.uv_tool.commands import (
    ColorChoice,
    build_install,
    build_upgrade_all,
    build_upgrade_packages,
)
from sase.uv_tool.detect import (
    RECEIPT_FILENAME,
    SASE_PACKAGE,
    NotUvToolInstall,
    NotUvToolReason,
    UvToolInstall,
    default_uv_tool_dir,
    detect_uv_tool_install,
    probe_uv_tool_install,
    sase_receipt_path,
)
from sase.uv_tool.errors import (
    NotAUvToolInstallError,
    ReceiptError,
    UvCommandFailedError,
    UvNotFoundError,
    UvToolError,
)
from sase.uv_tool.receipt import (
    ReconstructedRequirements,
    Requirement,
    ToolReceipt,
    load_receipt,
    parse_receipt,
)
from sase.uv_tool.runner import (
    UV_TIMEOUT_SECONDS,
    ChangeKind,
    UvChangeSet,
    UvPackageChange,
    parse_uv_output,
    run_uv,
)

__all__ = [
    "RECEIPT_FILENAME",
    "SASE_PACKAGE",
    "UV_TIMEOUT_SECONDS",
    "ChangeKind",
    "ColorChoice",
    "NotAUvToolInstallError",
    "NotUvToolInstall",
    "NotUvToolReason",
    "ReceiptError",
    "ReconstructedRequirements",
    "Requirement",
    "ToolReceipt",
    "UvChangeSet",
    "UvCommandFailedError",
    "UvNotFoundError",
    "UvPackageChange",
    "UvToolError",
    "UvToolInstall",
    "build_install",
    "build_upgrade_all",
    "build_upgrade_packages",
    "default_uv_tool_dir",
    "detect_uv_tool_install",
    "load_receipt",
    "parse_receipt",
    "parse_uv_output",
    "probe_uv_tool_install",
    "run_uv",
    "sase_receipt_path",
]
