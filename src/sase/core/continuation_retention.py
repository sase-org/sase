"""I/O adapter for Rust-owned continuation ancestry retention decisions."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import plan_continuation_retention
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.agent_artifact_paths import parse_agent_artifact_path


CONTINUATION_PORTABLE_LABEL_PREFIX = "continuation-portable:"
_RECOVERABLE_DELIVERY = frozenset(
    {"pending", "reserved", "dispatching", "needs_attention"}
)
_CAPTURE_NEEDS_RECOVERY = "needs_recovery"


def _collect_continuation_retention_runs(
    artifact_dirs: Sequence[Path | str],
    *,
    projects_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Read bounded continuation identity from each ACE-run directory."""

    runs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_dir in artifact_dirs:
        artifact_dir = Path(raw_dir).expanduser()
        key = _normalized_path(artifact_dir)
        if not key or key in seen:
            continue
        seen.add(key)
        runs.append(_collect_one_run(artifact_dir, key, projects_root=projects_root))
    return runs


def plan_continuation_run_retention(
    artifact_dirs: Sequence[Path | str],
    *,
    projects_root: Path | str | None = None,
) -> dict[str, Any]:
    """Return the Rust retention closure for the supplied run directories."""

    runs = _collect_continuation_retention_runs(
        artifact_dirs, projects_root=projects_root
    )
    return plan_continuation_retention(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "runs": runs,
        }
    )


def continuation_unavailable_sources(plan: Mapping[str, Any]) -> tuple[str, ...]:
    """Return continuation metadata gaps that block retention apply."""

    unavailable: list[str] = []
    for source in plan.get("sources_unavailable") or ():
        text = str(source).strip()
        if text:
            unavailable.append(text)
    return tuple(dict.fromkeys(unavailable))


def continuation_reasons_by_dir(
    plan: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    """Normalize Rust `reasons_by_dir` to resolved-path keys."""

    raw = plan.get("reasons_by_dir")
    if not isinstance(raw, Mapping):
        return {}
    reasons: dict[str, tuple[str, ...]] = {}
    for raw_dir, values in raw.items():
        key = _normalized_path(str(raw_dir))
        if not key:
            continue
        if isinstance(values, Sequence) and not isinstance(values, str | bytes):
            items = tuple(str(item) for item in values if str(item))
        else:
            items = ("continuation_ancestry",)
        reasons[key] = items or ("continuation_ancestry",)
    return reasons


def _collect_one_run(
    artifact_dir: Path,
    normalized_dir: str,
    *,
    projects_root: Path | str | None,
) -> dict[str, Any]:
    parsed = parse_agent_artifact_path(artifact_dir, projects_root=projects_root)
    timestamp = parsed.timestamp if parsed is not None else artifact_dir.name
    run: dict[str, Any] = {
        "artifact_dir": normalized_dir,
        "timestamp": timestamp,
        "parent_node_ids": [],
        "live": _is_live(artifact_dir),
        "recoverable": False,
        "portable_refs": [],
        "required_ref_failures": [],
    }
    try:
        meta = _read_json(artifact_dir / "agent_meta.json")
        locators = _read_json(artifact_dir / "continuation" / "portable_locators.json")
        delivery_state = _delivery_state(artifact_dir)
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        run["recoverable"] = True
        run["metadata_unavailable"] = str(exc)
        return run

    node_id = _first_str(
        meta.get("continuation_node_id"),
        meta.get("continuation_monitor_result_node_id"),
    )
    if node_id:
        run["node_id"] = node_id
    parent_ids = _unique_strings(
        [
            meta.get("continuation_parent_node_id"),
            *(_string_list(meta.get("continuation_parent_node_ids"))),
            meta.get("continuation_parent"),
        ]
    )
    if parent_ids:
        run["parent_node_ids"] = parent_ids
    starter = _first_str(meta.get("monitor_starter_artifacts_dir"))
    if starter:
        run["starter_artifact_dir"] = _normalized_path(starter)
    capture_error = meta.get("continuation_capture_error")
    capture_needs_recovery = (
        meta.get("continuation_capture_disposition") == _CAPTURE_NEEDS_RECOVERY
    )
    run["recoverable"] = bool(capture_needs_recovery or delivery_state is True)
    if capture_needs_recovery and isinstance(capture_error, str) and capture_error:
        run["required_ref_failures"] = [capture_error]
    if isinstance(delivery_state, str):
        run["metadata_unavailable"] = delivery_state
        run["recoverable"] = True
    run["portable_refs"] = _portable_refs(meta, locators)
    return run


def _is_live(artifact_dir: Path) -> bool:
    if (artifact_dir / "running.json").exists():
        return True
    if (artifact_dir / "waiting.json").exists():
        return True
    if (artifact_dir / "pending_question.json").exists():
        return True
    return not (artifact_dir / "done.json").exists()


def _delivery_state(artifact_dir: Path) -> bool | str:
    root = artifact_dir / "continuation" / "delivery"
    if not root.is_dir():
        return False
    try:
        children = tuple(root.iterdir())
    except OSError as exc:
        return str(exc)
    for child in children:
        if child.suffix.lower() != ".json" or child.is_symlink():
            continue
        try:
            payload = json.loads(child.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return True
        if not isinstance(payload, dict):
            return True
        disposition = payload.get("disposition")
        if isinstance(disposition, str) and disposition in _RECOVERABLE_DELIVERY:
            return True
    return False


def _portable_refs(
    meta: Mapping[str, Any],
    locators: Mapping[str, Any],
) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()

    def _add(value: Any) -> None:
        if not isinstance(value, str) or not value.startswith("file:"):
            return
        if value in seen:
            return
        seen.add(value)
        refs.append(value)

    locator_map = locators.get("locators")
    if isinstance(locator_map, Mapping):
        for value in locator_map.values():
            _add(value)
    for key in (
        "continuation_portable_content_ref",
        "continuation_node_portable_ref",
        "continuation_checkpoint_portable_ref",
        "continuation_intent_portable_ref",
        "continuation_monitor_result_portable_ref",
    ):
        _add(meta.get(key))
    parent_map = meta.get("continuation_parent_portable_refs")
    if isinstance(parent_map, Mapping):
        for value in parent_map.values():
            _add(value)
    return refs


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, UnicodeError):
        raise
    return payload if isinstance(payload, dict) else {}


def _first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _string_list(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        return (item for item in value if isinstance(item, str) and item)
    return ()


def _unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _normalized_path(path: Path | str) -> str:
    if not path:
        return ""
    return str(Path(path).expanduser().resolve(strict=False))


__all__ = [
    "CONTINUATION_PORTABLE_LABEL_PREFIX",
    "continuation_reasons_by_dir",
    "continuation_unavailable_sources",
    "plan_continuation_run_retention",
]
