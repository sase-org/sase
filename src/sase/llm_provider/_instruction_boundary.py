"""Fail-open shadow instruction render around root provider invocations (E2).

Every root ``provider.invoke`` call goes through
:func:`invoke_with_instructions`. With the ``instruction_shadow_render``
sunset flag on and an ``artifacts_dir``, the boundary renders the
memory-built instruction bundle the agent *would* get, writes the bundle
and its normalized manifest under ``<artifacts>/instructions/``, updates
the ``agent_meta.json`` summary, and exports ``SASE_INSTRUCTIONS_FILE``
for the duration of the call. Nothing is delivered to the provider.

The shadow render never fails an invocation: every exception from the
shadow work is caught, logged once, recorded as ``NN-<provider>.error.json``,
and the call proceeds. ``KeyboardInterrupt`` and ``SystemExit`` propagate.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any

from sase.env_contracts import (
    SASE_ACTIVE_PROJECT_DIR_ENV,
    SASE_INSTRUCTIONS_FILE_ENV,
)

log = logging.getLogger(__name__)

#: Manifest directory under the artifacts dir (decision 13).
INSTRUCTIONS_DIR_NAME = "instructions"

#: ``agent_meta.json`` summary key (decision 13).
AGENT_META_KEY = "instructions"

#: Manifest schema version recorded in the agent_meta summary and error files.
MANIFEST_SCHEMA_VERSION = 1

#: ``SASE_AGENT_NAME`` carries the agent identity for delivery records.
_AGENT_NAME_ENV = "SASE_AGENT_NAME"

_VALID_PURPOSES = ("ordinary", "declaration_recovery", "conflict_repair")

_MAX_SEQ_ATTEMPTS = 25

_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _instruction_shadow_render_enabled() -> bool:
    """Return whether the shadow-render sunset flag is on.

    Falls back to the registry default (on for a sunset flag) when the flag
    cannot be resolved, so a broken flag snapshot fails toward recording
    rather than silently dropping coverage. The render itself stays
    fail-open either way.
    """
    try:
        from sase.feature_flags import FeatureFlag, current_flags
        from sase.feature_flags.models import FeatureFlagError

        return current_flags().enabled(FeatureFlag.instruction_shadow_render)
    except FeatureFlagError:
        return True
    except Exception:  # noqa: BLE001 - never let flag resolution break invoke.
        log.debug("instruction shadow flag lookup failed", exc_info=True)
        return True


def _utc_now_z() -> str:
    """Return the current UTC time as RFC 3339 with a ``Z`` suffix."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sanitize_label(label: Any) -> str:
    """Return *label* as a filename-safe provider slug."""
    text = label if isinstance(label, str) else ""
    slug = _SAFE_LABEL_RE.sub("-", text).strip("-")
    return slug or "unknown"


def _read_agent_meta(artifacts_dir: str) -> dict[str, Any]:
    """Return the parsed ``agent_meta.json`` mapping, or ``{}``."""
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as handle:
            meta = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _resolve_provider_label(
    provider: Any, artifacts_dir: str | None, fallback: str | None
) -> str:
    """Return the execution provider name, best-effort, never raising."""
    try:
        name = provider.provider_name()
    except Exception:  # noqa: BLE001 - label resolution fails open.
        name = None
    if isinstance(name, str) and name:
        return name
    if artifacts_dir:
        meta = _read_agent_meta(artifacts_dir)
        for key in ("exec_llm_provider", "llm_provider"):
            value = meta.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(fallback, str) and fallback:
        return fallback
    return "unknown"


def _resolve_project_root() -> Path:
    """Return the project root the shadow render compiles against."""
    configured = os.environ.get(SASE_ACTIVE_PROJECT_DIR_ENV, "").strip()
    if configured and Path(configured).is_dir():
        return Path(configured)
    return Path.cwd()


def _attempt_number(artifacts_dir: str) -> int:
    """Return ``1 + count(attempts/*)`` for the manifest, best-effort."""
    try:
        attempts = Path(artifacts_dir) / "attempts"
        count = sum(1 for child in attempts.iterdir() if child.is_dir())
    except OSError:
        count = 0
    return count + 1


def _next_sequence(instructions_dir: Path) -> int:
    """Return one past the highest ``NN`` prefix present, best-effort."""
    highest = -1
    try:
        names = [child.name for child in instructions_dir.iterdir()]
    except OSError:
        return 0
    for name in names:
        prefix, _, _ = name.partition("-")
        if len(prefix) == 2 and prefix.isdigit():
            highest = max(highest, int(prefix))
    return highest + 1


def _manifest_count(instructions_dir: Path) -> int:
    """Return the number of written ``NN-<provider>.json`` manifests."""
    try:
        names = [child.name for child in instructions_dir.iterdir()]
    except OSError:
        return 0
    return sum(
        1
        for name in names
        if name.endswith(".json") and not name.endswith(".error.json")
    )


def _reserve_bundle_path(instructions_dir: Path, label: str) -> tuple[int, Path]:
    """Reserve ``NN-<label>.md`` with ``O_EXCL`` and return ``(seq, path)``.

    Retries on collision so concurrent invocations in one artifacts dir get
    distinct sequence numbers. Raises the last ``OSError`` when no free
    number is found.
    """
    instructions_dir.mkdir(parents=True, exist_ok=True)
    seq = _next_sequence(instructions_dir)
    error: OSError | None = None
    for candidate in range(seq, seq + _MAX_SEQ_ATTEMPTS):
        path = instructions_dir / f"{candidate:02d}-{label}.md"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            error = exc
            continue
        os.close(fd)
        return candidate, path
    assert error is not None
    raise error


def _write_error_json(
    instructions_dir: Path,
    label: str,
    purpose: str,
    exc: BaseException,
    *,
    seq: int | None = None,
    rendered_at: str | None = None,
) -> None:
    """Write ``NN-<provider>.error.json`` best-effort; never raises."""
    try:
        instructions_dir.mkdir(parents=True, exist_ok=True)
        number = seq if seq is not None else _next_sequence(instructions_dir)
        payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "provider": label,
            "purpose": purpose,
            "invocation_seq": number,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc)[:2000],
            },
            "rendered_at": rendered_at or _utc_now_z(),
        }
        path = instructions_dir / f"{number:02d}-{label}.error.json"
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:  # noqa: BLE001 - error reporting never breaks invoke.
        log.debug("instruction shadow error record failed", exc_info=True)


def _resolve_model(provider: Any, invoke_kwargs: dict[str, Any]) -> str:
    """Return the delivery model name best-effort, or ``""``."""
    override = invoke_kwargs.get("model_override")
    if isinstance(override, str) and override:
        return override
    try:
        model_tier = invoke_kwargs.get("model_tier", "large")
        model = provider.resolve_model_name(model_tier)
    except Exception:  # noqa: BLE001 - model resolution fails open.
        return ""
    return model if isinstance(model, str) else ""


def _render_shadow(
    provider: Any,
    *,
    purpose: str,
    artifacts_dir: str,
    provider_name: str | None,
    agent_type: str | None,
    invoke_kwargs: dict[str, Any],
) -> str:
    """Render and record the shadow bundle; return the bundle file path.

    Raises on any shadow failure; the caller records the error and proceeds
    with the invocation.
    """
    from sase.instructions.compile import compile_bundle
    from sase.instructions.facts import default_facts
    from sase.instructions.manifest import build_manifest

    instructions_dir = Path(artifacts_dir) / INSTRUCTIONS_DIR_NAME
    raw_label = _resolve_provider_label(provider, artifacts_dir, provider_name)
    label = _sanitize_label(raw_label)
    seq, bundle_path = _reserve_bundle_path(instructions_dir, label)
    try:
        project_root = _resolve_project_root()
        facts = default_facts(project_root, provider=raw_label, purpose=purpose)
        compiled = compile_bundle(
            facts, project_root=project_root, home_root=Path.home()
        )
        delivery: dict[str, Any] = {
            "status": "shadow",
            "channel": None,
            "invocation_id": str(uuid.uuid4()),
            "invocation_seq": seq,
            "attempt": _attempt_number(artifacts_dir),
            "agent_name": os.environ.get(_AGENT_NAME_ENV, ""),
            "agent_type": agent_type or "",
            "model": _resolve_model(provider, invoke_kwargs),
            "parent_invocation_id": None,
            "session_ids": [],
            "provider_cli_version": None,
            "rendered_at": _utc_now_z(),
        }
        manifest = build_manifest(compiled, facts, delivery)
        bundle_path.write_text(compiled.text, encoding="utf-8")
        manifest_path = bundle_path.with_suffix(".json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
        bundle = manifest["bundle"]
        summary = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "count": _manifest_count(instructions_dir),
            "latest": {
                "seq": seq,
                "provider": raw_label,
                "purpose": purpose,
                "sha256": bundle["sha256"],
                "common_digest": bundle["common_digest"],
                "manifest": f"{INSTRUCTIONS_DIR_NAME}/{manifest_path.name}",
            },
        }
        from sase.axe.run_agent_helpers import update_meta_field

        update_meta_field(artifacts_dir, AGENT_META_KEY, summary)
        os.environ[SASE_INSTRUCTIONS_FILE_ENV] = str(bundle_path)
        return str(bundle_path)
    except Exception:
        try:
            if bundle_path.is_file() and bundle_path.stat().st_size == 0:
                bundle_path.unlink()
        except OSError:
            pass
        raise


def invoke_with_instructions(
    provider: Any,
    prompt: str,
    *,
    purpose: str,
    artifacts_dir: str | None,
    provider_name: str | None = None,
    agent_type: str | None = None,
    **invoke_kwargs: Any,
) -> Any:
    """Invoke *provider* with a shadow instruction render around the call.

    This is the only place that calls ``provider.invoke`` for a root
    invocation. With the flag on and an ``artifacts_dir``, the bundle and
    manifest are recorded and ``SASE_INSTRUCTIONS_FILE`` holds the bundle
    path during the call; afterwards the previous value is restored. With
    the flag off or no ``artifacts_dir``, ``provider.invoke`` runs
    directly.
    """
    if purpose not in _VALID_PURPOSES:
        raise ValueError(
            f"invalid shadow purpose {purpose!r}; "
            f"valid purposes: {', '.join(_VALID_PURPOSES)}"
        )
    if not artifacts_dir or not _instruction_shadow_render_enabled():
        return provider.invoke(prompt, **invoke_kwargs)
    label = _sanitize_label(
        _resolve_provider_label(provider, artifacts_dir, provider_name)
    )
    previous_env = os.environ.get(SASE_INSTRUCTIONS_FILE_ENV)
    try:
        _render_shadow(
            provider,
            purpose=purpose,
            artifacts_dir=artifacts_dir,
            provider_name=provider_name,
            agent_type=agent_type,
            invoke_kwargs=invoke_kwargs,
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 - the shadow never fails invoke.
        log.warning("instruction shadow render failed: %s", exc)
        _write_error_json(
            Path(artifacts_dir) / INSTRUCTIONS_DIR_NAME, label, purpose, exc
        )
    try:
        return provider.invoke(prompt, **invoke_kwargs)
    finally:
        if previous_env is None:
            os.environ.pop(SASE_INSTRUCTIONS_FILE_ENV, None)
        else:
            os.environ[SASE_INSTRUCTIONS_FILE_ENV] = previous_env


__all__ = [
    "AGENT_META_KEY",
    "INSTRUCTIONS_DIR_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "_instruction_shadow_render_enabled",
    "invoke_with_instructions",
]
