"""Persisted continuation records used by monitor follow-up launches."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from pathlib import Path
from typing import Any

from sase.continuation_capture._storage import sha_json
from sase.shells.followup import vcs_ref_from_meta

from .followup_persistence import clean_str


def load_frozen_monitor_result(
    artifacts_dir: str,
    meta: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the persisted frozen monitor result, verifying its digest."""

    del artifacts_dir
    raw_path = clean_str(meta.get("continuation_monitor_result_path"))
    if not raw_path:
        return None
    path = Path(raw_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"could not read frozen monitor result at {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"frozen monitor result at {path} is not an object")
    expected = clean_str(meta.get("continuation_monitor_result_sha256"))
    if expected and sha_json(payload) != expected:
        raise ValueError(
            f"frozen monitor result digest mismatch for {path}: "
            f"expected {expected}, got {sha_json(payload)}"
        )
    if not payload.get("result_id"):
        raise ValueError(f"frozen monitor result at {path} has no result_id")
    return payload


def load_frozen_monitor_intent(
    artifacts_dir: str,
    meta: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the persisted monitor intent, if this run has one."""

    ref = clean_str(meta.get("continuation_intent_ref"))
    if not ref:
        return None
    payload = _read_continuation_json_ref(artifacts_dir, ref)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError(f"frozen monitor intent {ref} is not an object")
    return payload


def _read_continuation_json_ref(
    artifacts_dir: str,
    ref: str,
) -> dict[str, Any] | None:
    path = continuation_ref_path(artifacts_dir, ref)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read continuation ref {ref}: {exc}") from exc
    return payload if isinstance(payload, dict) else None


def continuation_ref_path(artifacts_dir: str, ref: str) -> Path | None:
    prefix = "local:continuation/"
    if not ref.startswith(prefix):
        return None
    root = (Path(artifacts_dir) / "continuation").resolve(strict=False)
    path = (root / ref.removeprefix(prefix)).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def next_action_from_intent(intent: Mapping[str, Any] | None) -> str | None:
    if not intent:
        return None
    value = intent.get("next_action")
    return value if isinstance(value, str) and value else None


def next_model_from_intent(intent: Mapping[str, Any] | None) -> str | None:
    if not intent:
        return None
    route = intent.get("route")
    if not isinstance(route, Mapping):
        return None
    return clean_str(route.get("model"))


def load_checkpoint_body(
    artifacts_dir: str,
    checkpoint_ref: str | None,
) -> Mapping[str, Any] | None:
    if not checkpoint_ref:
        return None
    try:
        return _read_continuation_json_ref(artifacts_dir, checkpoint_ref)
    except ValueError:
        return None


def frozen_intent_vcs_prefix(
    meta: Mapping[str, Any],
    *,
    frozen_next_action: str,
) -> str:
    recorded = vcs_ref_from_meta(meta)
    if recorded is None:
        return ""
    mutable_next_action = clean_str(meta.get("monitor_next_action")) or ""
    if not mutable_next_action or mutable_next_action == frozen_next_action:
        return ""
    canonical_ref = f"#{recorded[0]}:{recorded[1]}"
    if canonical_ref not in mutable_next_action:
        # A resolved tag token naming the recorded project counts as
        # already prefixed. Prose mentions and substrings of longer tags
        # do not: only a real ``+<project>`` token counts (D1).
        try:
            from sase.project_tags import project_tag_for

            tag = project_tag_for(recorded[1])
        except Exception:  # noqa: BLE001 - fall back to the canonical ref.
            tag = canonical_ref
        if not tag.startswith("+"):
            return ""
        if not _mutable_has_project_tag_token(mutable_next_action, tag):
            return ""
    return f"#{recorded[0]}:{recorded[1]}\n"


def _mutable_has_project_tag_token(mutable_next_action: str, tag: str) -> bool:
    """Return whether *tag* (``+<name>``) occurs as a real tag token.

    Uses the tag scanner so ``+bob`` does not match inside ``+bobby``.
    Falls back to D1 boundary matching when the scanner is unavailable.
    """

    try:
        from sase.project_tags import find_project_tags

        scanned = find_project_tags(mutable_next_action)
    except Exception:  # noqa: BLE001 - fall back to boundary matching.
        scanned = []
        fallback = True
    else:
        fallback = False
    if not fallback:
        folded = tag.casefold()
        for found in scanned:
            if not isinstance(found, dict):
                continue
            name = found.get("name")
            if isinstance(name, str) and f"+{name}".casefold() == folded:
                return True
        return False
    pattern = r"(?:^|(?<=[\s{|(\[]))" + re.escape(tag) + r"(?![A-Za-z0-9_.-])"
    return re.search(pattern, mutable_next_action) is not None


def has_frozen_monitor_result_pointer(meta: Mapping[str, Any]) -> bool:
    return any(
        clean_str(meta.get(key))
        for key in (
            "continuation_monitor_result_id",
            "continuation_monitor_result_ref",
            "continuation_monitor_result_path",
            "continuation_monitor_result_node_ref",
            "continuation_monitor_result_manifest_ref",
        )
    )


__all__ = [
    "continuation_ref_path",
    "frozen_intent_vcs_prefix",
    "has_frozen_monitor_result_pointer",
    "load_checkpoint_body",
    "load_frozen_monitor_intent",
    "load_frozen_monitor_result",
    "next_action_from_intent",
    "next_model_from_intent",
]
