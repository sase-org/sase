"""Hidden mobile helper bridge operations."""

# ruff: noqa: F401

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from . import _mobile_helper_beads as _beads
from . import _mobile_helper_catalog as _catalog
from . import _mobile_helper_updates as _updates
from ._mobile_helper_beads import (
    beads_list_response,
    beads_show_response,
    get_all_project_beads_dirs,
    get_project_beads_dirs_for_project,
)
from ._mobile_helper_catalog import (
    build_structured_xprompts_catalog,
    changespec_tags_response,
    xprompt_catalog_response,
)
from ._mobile_helper_common import (
    GATEWAY_WIRE_SCHEMA_VERSION,
    MobileHelperBridgeError as _MobileHelperBridgeError,
    MobileHelperNotFoundError as _MobileHelperNotFoundError,
    MobileUpdateAlreadyRunning as _MobileUpdateAlreadyRunning,
    MobileUpdateJobNotFound as _MobileUpdateJobNotFound,
    read_request as _read_request,
)
from ._mobile_helper_updates import (
    read_chat_install_status,
    start_chat_install_worker,
    update_start_response,
    update_status_response,
)

__all__ = [
    "GATEWAY_WIRE_SCHEMA_VERSION",
    "handle_mobile_helper_bridge",
]


def handle_mobile_helper_bridge(
    args: argparse.Namespace,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one fixed mobile helper bridge operation over JSON stdin/stdout."""
    try:
        _sync_mobile_helper_dependency_overrides()
        request = _read_request(stdin)
        operation = getattr(args, "mobile_helper_bridge_subcommand", None)
        if operation == "changespec-tags":
            response = changespec_tags_response(request)
        elif operation == "xprompt-catalog":
            response = xprompt_catalog_response(request)
        elif operation == "beads-list":
            response = beads_list_response(request)
        elif operation == "beads-show":
            response = beads_show_response(request)
        elif operation == "update-start":
            response = update_start_response(request)
        elif operation == "update-status":
            response = update_status_response(request)
        else:
            raise _MobileHelperBridgeError("unknown mobile helper bridge operation")
    except (
        _MobileHelperNotFoundError,
        _MobileUpdateAlreadyRunning,
        _MobileUpdateJobNotFound,
    ) as exc:
        print(f"mobile helper bridge error: {exc}", file=stderr)
        return 4
    except (_MobileHelperBridgeError, ValueError, TypeError) as exc:
        print(f"mobile helper bridge error: {exc}", file=stderr)
        return 2

    json.dump(response, stdout, separators=(",", ":"))
    stdout.write("\n")
    return 0


def _sync_mobile_helper_dependency_overrides() -> None:
    """Preserve legacy monkeypatch targets on this facade module."""
    _catalog.build_structured_xprompts_catalog = build_structured_xprompts_catalog
    _beads.get_all_project_beads_dirs = get_all_project_beads_dirs
    _beads.get_project_beads_dirs_for_project = get_project_beads_dirs_for_project
    _updates.read_chat_install_status = read_chat_install_status
    _updates.start_chat_install_worker = start_chat_install_worker
