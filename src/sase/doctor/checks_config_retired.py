"""Retired xprompt authored-surface report for ``sase doctor``.

Check id ``config.retired_xprompt_names`` intentionally keeps the retired
spelling: the parent design (plan ``202610/macro_syntax_cutover.md``)
requires this exact id so retirement findings stay greppable under the old
name. Do not rename it to a macro id.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.legacy_xprompt_syntax import (
    CANONICAL_FRONTMATTER_KEY,
    CANONICAL_PLUGIN_GROUP,
    RETIRED_CONFIG_KEYS,
    RETIRED_ENV_VARS,
    RETIRED_FRONTMATTER_KEY,
    RETIRED_PLUGIN_GROUP,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

#: This intentional legacy id is required by the parent design.
RETIRED_XPROMPT_NAMES_CHECK_ID = "config.retired_xprompt_names"

#: TUI-owned keymap actions whose rename belongs to ``sase-1eq.5``. The
#: check reports user-authored overrides of these actions; the shipped
#: defaults are not findings.
RETIRED_KEYMAP_ACTIONS: tuple[tuple[str, str], ...] = (
    ("focus_xprompt", "focus_macro"),
    ("clear_xprompt_focus", "clear_macro_focus"),
    ("start_last_vcs_xprompt_in_editor", "start_last_vcs_macro_in_editor"),
)

_KEYMAP_REPLACEMENT = dict(RETIRED_KEYMAP_ACTIONS)


def check_config_retired_xprompt_names(context: DoctorContext) -> DiagnosticCheck:
    """List every retired xprompt authored surface in either flag state.

    Inspects raw authored inputs independently of the loader's acceptance
    policy, so legacy input is reported even when ordinary loading would
    reject it (flag off) or silently accept it (flag on). Never expands
    templates and never exposes environment values: only names, keys, and
    paths are reported. Durable files and permanent ``%xprompts_enabled``
    regions are not retirement findings and are never reported here.
    """
    findings: list[dict[str, str]] = []
    findings.extend(_scan_config_layers())
    findings.extend(_scan_definition_directories(context))
    findings.extend(_scan_frontmatter(context))
    findings.extend(_scan_env_vars(context))
    findings.extend(_scan_plugin_groups())

    status: CheckStatus = "WARN" if findings else "OK"
    details = tuple(
        f"{finding['location']}: {finding['surface']} — {finding['replacement']}"
        for finding in findings[:MAX_DETAIL_ROWS]
    )
    summary = (
        f"{len(findings)} retired xprompt authored surface(s) found"
        if findings
        else "No retired xprompt authored surfaces found"
    )
    next_steps = (
        (
            "Rename each listed surface to its macro replacement, then rerun "
            "`sase doctor -C config.retired_xprompt_names`. "
            "Keymap actions land with the TUI phase.",
        )
        if findings
        else ()
    )
    return DiagnosticCheck(
        id=RETIRED_XPROMPT_NAMES_CHECK_ID,
        group="config",
        status=status,
        title="Retired xprompt names",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={"count": len(findings), "findings": findings},
    )


def _finding(location: str, surface: str, replacement: str) -> dict[str, str]:
    return {"location": location, "surface": surface, "replacement": replacement}


def _scan_config_layers() -> list[dict[str, str]]:
    """Report retired keys in raw config layers via core diagnostics."""
    findings: list[dict[str, str]] = []
    try:
        from sase.config.core import load_config_layers
    except Exception:  # noqa: BLE001 - doctor checks must be best-effort.
        return findings
    try:
        layers = load_config_layers()
    except Exception:  # noqa: BLE001 - retain raw metadata even if load failed.
        return findings
    for layer in layers:
        if getattr(layer, "name", "") == "default":
            # Shipped canonical defaults are product, not authored legacy
            # input; the TUI phase owns their remaining keymap spellings.
            continue
        data = getattr(layer, "data", None)
        if not isinstance(data, dict):
            # Retain the layer identity even when its content failed to load.
            error = getattr(layer, "error", None)
            if error:
                findings.append(
                    _finding(
                        f"config layer {getattr(layer, 'name', '?')}",
                        "unreadable layer (retained for inspection)",
                        "fix the layer so retirement scanning can run",
                    )
                )
            continue
        try:
            _extend_with_core_diagnostics(findings, layer, data)
        except Exception:  # noqa: BLE001 - one bad layer must not hide others.
            continue
        findings.extend(_scan_keymap_overrides(layer, data))
    return findings


def _extend_with_core_diagnostics(
    findings: list[dict[str, str]], layer: Any, data: dict[str, Any]
) -> None:
    """Reuse the Rust config normalization diagnostics for one raw layer."""
    from sase.core.rust import require_rust_binding

    binding = require_rust_binding("normalize_macro_config_layer")
    result = binding(
        {
            "layer": dict(data),
            "accept_legacy_xprompt_names": True,
            "source": str(getattr(layer, "name", "")),
        }
    )
    diagnostics = result.get("diagnostics", [])
    if not isinstance(diagnostics, list):
        return
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        message = str(diagnostic.get("message", ""))
        if "xprompt" not in message.lower():
            continue
        findings.append(
            _finding(
                f"config layer {getattr(layer, 'name', '?')}",
                message,
                _replacement_for(message),
            )
        )


def _replacement_for(message: str) -> str:
    lowered = message.lower()
    for old, new in RETIRED_CONFIG_KEYS:
        if old in lowered:
            return f"use {new}"
    return "rename to the macro spelling"


def _scan_keymap_overrides(layer: Any, data: Any) -> list[dict[str, str]]:
    """Report user-authored overrides of retired TUI keymap actions."""
    findings: list[dict[str, str]] = []
    for old, new in RETIRED_KEYMAP_ACTIONS:
        if _contains_key(data, old):
            findings.append(
                _finding(
                    f"config layer {getattr(layer, 'name', '?')}",
                    f"keymap action {old} (owned by the TUI phase)",
                    f"use {new}",
                )
            )
    return findings


def _contains_key(data: Any, key: str) -> bool:
    if isinstance(data, dict):
        if key in data:
            return True
        return any(_contains_key(value, key) for value in data.values())
    if isinstance(data, list):
        return any(_contains_key(value, key) for value in data)
    return False


def _scan_definition_directories(context: DoctorContext) -> list[dict[str, str]]:
    """Report retired macro definition directories present on disk."""
    findings: list[dict[str, str]] = []
    try:
        from sase.content_layout import resolve_macro_file_sources
    except Exception:  # noqa: BLE001 - doctor checks must be best-effort.
        return findings
    try:
        sources = resolve_macro_file_sources(
            project=context.project,
            accept_legacy=True,
        )
    except Exception:  # noqa: BLE001 - keep the check accessible on bad trees.
        return findings
    seen: set[str] = set()
    for source in sources:
        try:
            if source.role != "legacy":
                continue
            path = source.path
            if path is None or str(path) in seen:
                continue
            seen.add(str(path))
            if not path.is_dir():
                continue
            try:
                entries = list(path.iterdir())
            except OSError:
                continue
            if not entries:
                continue
            findings.append(
                _finding(
                    str(path),
                    f"retired definition directory ({source.scope} "
                    f"{source.locator}); skipped while the sunset flag is off",
                    "move definitions to the canonical macros directory",
                )
            )
        except Exception:  # noqa: BLE001 - one bad source must not hide others.
            continue
    return findings


def _scan_frontmatter(context: DoctorContext) -> list[dict[str, str]]:
    """Report retired frontmatter keys in raw macro source files."""
    findings: list[dict[str, str]] = []
    try:
        from sase.content_layout import resolve_macro_file_sources
        from sase.macro.loader_parsing import parse_yaml_front_matter
    except Exception:  # noqa: BLE001 - doctor checks must be best-effort.
        return findings
    try:
        sources = resolve_macro_file_sources(
            project=context.project,
            accept_legacy=True,
        )
    except Exception:  # noqa: BLE001 - keep the check accessible on bad trees.
        return findings
    for source in sources:
        path = getattr(source, "path", None)
        if path is None:
            continue
        try:
            if not path.is_dir():
                continue
            files = sorted(path.rglob("*.md")) + sorted(path.rglob("*.yml"))
        except OSError:
            continue
        for file in files[:500]:
            try:
                if not file.is_file():
                    continue
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if RETIRED_FRONTMATTER_KEY not in text:
                continue
            try:
                mapping, _body = parse_yaml_front_matter(text)
            except Exception:  # noqa: BLE001 - malformed files are other checks.
                continue
            if isinstance(mapping, dict) and RETIRED_FRONTMATTER_KEY in mapping:
                findings.append(
                    _finding(
                        str(file),
                        f"frontmatter key {RETIRED_FRONTMATTER_KEY!r}",
                        f"use {CANONICAL_FRONTMATTER_KEY!r}",
                    )
                )
    return findings


def _scan_env_vars(context: DoctorContext) -> list[dict[str, str]]:
    """Report ambient retired public env variables without exposing values."""
    findings: list[dict[str, str]] = []
    env = context.env if isinstance(context.env, dict) else os.environ
    for old, new in RETIRED_ENV_VARS:
        try:
            present = old in env
        except Exception:  # noqa: BLE001 - degraded env mapping.
            continue
        if present:
            findings.append(
                _finding(
                    "process environment",
                    f"${old} is set",
                    f"use ${new}",
                )
            )
    return findings


def _scan_plugin_groups() -> list[dict[str, str]]:
    """Report distributions still registered under the retired plugin group."""
    findings: list[dict[str, str]] = []
    try:
        from importlib import metadata as importlib_metadata
    except Exception:  # noqa: BLE001 - no importlib on this host.
        return findings
    try:
        entry_points = importlib_metadata.entry_points()
        if hasattr(entry_points, "select"):
            retired = entry_points.select(group=RETIRED_PLUGIN_GROUP)
        else:  # pragma: no cover - legacy importlib API.
            retired = entry_points.get(RETIRED_PLUGIN_GROUP, ())
    except Exception:  # noqa: BLE001 - entry-point scan must not traceback.
        return findings
    seen: set[str] = set()
    for entry_point in retired:
        try:
            dist_name = getattr(getattr(entry_point, "dist", None), "metadata", {})[
                "Name"
            ]
        except Exception:  # noqa: BLE001 - unnamed entry point.
            dist_name = getattr(entry_point, "name", "?")
        if dist_name in seen:
            continue
        seen.add(str(dist_name))
        findings.append(
            _finding(
                f"plugin distribution {dist_name}",
                f"entry-point group {RETIRED_PLUGIN_GROUP!r}",
                f"ship macros under {CANONICAL_PLUGIN_GROUP!r}",
            )
        )
    return findings


__all__ = [
    "RETIRED_KEYMAP_ACTIONS",
    "RETIRED_XPROMPT_NAMES_CHECK_ID",
    "check_config_retired_xprompt_names",
]
