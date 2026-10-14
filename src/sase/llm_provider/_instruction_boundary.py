"""Instruction delivery boundary around root provider invocations (E3).

Every root ``provider.invoke`` call goes through
:func:`invoke_with_instructions`. With an ``artifacts_dir``, the boundary
resolves the delivery plan, renders the root bundle (and the helper bundle
when the subagent slot is explicit), validates transport, writes v2
manifests, and exposes :func:`current_instruction_delivery` to adapters.
Failures degrade atomically to legacy native discovery. With no
``artifacts_dir``, ``provider.invoke`` runs directly.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.env_contracts import (
    SASE_ACTIVE_PROJECT_DIR_ENV,
    SASE_INSTRUCTIONS_FILE_ENV,
)

if TYPE_CHECKING:
    from sase.llm_provider.instruction_delivery import (
        ActiveInstructionDelivery,
        DeliveryPlan,
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

_BUNDLE_FILE_MODE = 0o644


@dataclass
class _PreparedDelivery:
    """Artifacts and live delivery for one invocation."""

    active: ActiveInstructionDelivery
    bundle_path: Path
    manifest_path: Path
    helper_manifest_path: Path | None
    artifacts_dir: str
    label: str
    raw_label: str
    purpose: str
    seq: int


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
    """Return the project root the render compiles against."""
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


def _is_root_manifest_name(name: str) -> bool:
    """Return whether *name* is a root ``NN-<provider>.json`` manifest."""
    return (
        name.endswith(".json")
        and not name.endswith(".error.json")
        and not name.endswith(".helper.json")
    )


def _manifest_count(instructions_dir: Path) -> int:
    """Return the number of written root ``NN-<provider>.json`` manifests."""
    try:
        names = [child.name for child in instructions_dir.iterdir()]
    except OSError:
        return 0
    return sum(1 for name in names if _is_root_manifest_name(name))


def _chmod_0644(path: Path) -> None:
    """Set *path* to mode 0644, ignoring filesystem errors."""
    try:
        os.chmod(path, _BUNDLE_FILE_MODE)
    except OSError:
        pass


def _reserve_bundle_path(instructions_dir: Path, label: str) -> tuple[int, Path]:
    """Reserve ``NN-<label>.md`` with ``O_EXCL`` and return ``(seq, path)``.

    Retries on collision so concurrent invocations in one artifacts dir get
    distinct sequence numbers. Raises the last ``OSError`` when no free
    number is found. Files are created mode 0644.
    """
    instructions_dir.mkdir(parents=True, exist_ok=True)
    seq = _next_sequence(instructions_dir)
    error: OSError | None = None
    for candidate in range(seq, seq + _MAX_SEQ_ATTEMPTS):
        path = instructions_dir / f"{candidate:02d}-{label}.md"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _BUNDLE_FILE_MODE)
        except FileExistsError as exc:
            error = exc
            continue
        try:
            os.fchmod(fd, _BUNDLE_FILE_MODE)
        except OSError:
            pass
        os.close(fd)
        return candidate, path
    assert error is not None
    raise error


def _write_text_0644(path: Path, text: str) -> None:
    """Write *text* to *path* and set mode 0644."""
    path.write_text(text, encoding="utf-8")
    _chmod_0644(path)


def _write_json_0644(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write *payload* as indented JSON with mode 0644."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        _chmod_0644(tmp)
        os.replace(tmp, path)
        _chmod_0644(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


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
            "delivery_fallback": "legacy",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc)[:2000],
            },
            "rendered_at": rendered_at or _utc_now_z(),
        }
        path = instructions_dir / f"{number:02d}-{label}.error.json"
        _write_json_0644(path, payload)
    except Exception:  # noqa: BLE001 - error reporting never breaks invoke.
        log.debug("instruction delivery error record failed", exc_info=True)


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


def _delivery_identity(
    *,
    status: str,
    seq: int,
    artifacts_dir: str,
    agent_type: str | None,
    model: str,
    invocation_id: str,
    provider_cli_version: str | None,
    channel: str | None,
    parent_invocation_id: str | None,
    session_ids: list[str],
    fallback: dict[str, str] | None,
    subagent: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the delivery mapping passed to :func:`build_manifest`."""
    payload: dict[str, Any] = {
        "status": status,
        "channel": channel,
        "invocation_id": invocation_id,
        "invocation_seq": seq,
        "attempt": _attempt_number(artifacts_dir),
        "agent_name": os.environ.get(_AGENT_NAME_ENV, ""),
        "agent_type": agent_type or "",
        "model": model,
        "parent_invocation_id": parent_invocation_id,
        "session_ids": list(session_ids),
        "provider_cli_version": provider_cli_version,
        "rendered_at": _utc_now_z(),
    }
    if fallback is not None:
        payload["fallback"] = fallback
    if subagent is not None:
        payload["subagent"] = subagent
    return payload


def _drop_helper_explicit(active: ActiveInstructionDelivery, reason: str) -> None:
    """Send helpers back to the E1 template without substituting the root."""
    from sase.llm_provider.instruction_delivery import SlotPlan

    if active.subagent.plan.status != "explicit":
        return
    active.subagent.plan = SlotPlan(status="inherits_native", reason=reason)
    active.subagent.text = None
    active.subagent.sha256 = None
    if active.subagent.fallback is None:
        active.subagent.fallback = {"reason": reason}


def _prepare_delivery(
    provider: Any,
    *,
    purpose: str,
    artifacts_dir: str,
    provider_name: str | None,
    agent_type: str | None,
    invoke_kwargs: dict[str, Any],
) -> _PreparedDelivery:
    """Resolve, render, validate, and record delivery; raise on hard failure."""
    from sase.instructions.compile import compile_bundle
    from sase.instructions.facts import default_facts, parse_facts
    from sase.instructions.manifest import build_manifest
    from sase.llm_provider.instruction_delivery import (
        ActiveInstructionDelivery,
        ActiveSlot,
        delivered_text,
        fallback_wire,
        helper_bundle_is_valid,
        probe_provider_cli_version,
        resolve_delivery_plan,
        root_bundle_is_valid,
        subagent_wire,
    )

    instructions_dir = Path(artifacts_dir) / INSTRUCTIONS_DIR_NAME
    raw_label = _resolve_provider_label(provider, artifacts_dir, provider_name)
    label = _sanitize_label(raw_label)
    plan: DeliveryPlan = resolve_delivery_plan(provider)
    seq, bundle_path = _reserve_bundle_path(instructions_dir, label)
    helper_compiled = None
    helper_facts = None
    try:
        project_root = _resolve_project_root()
        facts = default_facts(project_root, provider=raw_label, purpose=purpose)
        compiled = compile_bundle(
            facts, project_root=project_root, home_root=Path.home()
        )
        invocation_id = str(uuid.uuid4())
        cli_version = probe_provider_cli_version(provider)
        model = _resolve_model(provider, invoke_kwargs)
        root_text = delivered_text(compiled.text, compiled.sha256, invocation_id)
        active = ActiveInstructionDelivery(
            invocation_id=invocation_id,
            provider=raw_label,
            root=ActiveSlot(
                plan=plan.root,
                text=root_text,
                sha256=compiled.sha256,
                fallback=fallback_wire(plan.root),
            ),
            subagent=ActiveSlot(
                plan=plan.subagent,
                fallback=fallback_wire(plan.subagent),
            ),
        )
        if plan.subagent.status == "explicit":
            try:
                helper_facts = parse_facts(
                    {**facts.to_dict(), "actor": "native_helper"}
                )
                helper_compiled = compile_bundle(
                    helper_facts,
                    project_root=project_root,
                    home_root=Path.home(),
                )
            except Exception as exc:  # noqa: BLE001 - helper never fails the root.
                active.report_fallback("subagent", "render_failed", str(exc)[:2000])
            else:
                if not helper_bundle_is_valid(helper_compiled.text):
                    helper_compiled = None
                    active.report_fallback("subagent", "invalid_bundle")
                else:
                    active.subagent.text = delivered_text(
                        helper_compiled.text,
                        helper_compiled.sha256,
                        invocation_id,
                    )
                    active.subagent.sha256 = helper_compiled.sha256
        if plan.root.status == "explicit":
            if not root_bundle_is_valid(
                compiled.text, provider=facts.provider, sections=compiled.sections
            ):
                active.report_fallback("root", "invalid_bundle")
            elif (
                plan.root.max_bytes is not None
                and len(root_text.encode("utf-8")) > plan.root.max_bytes
            ):
                active.report_fallback("root", "oversize")
        if active.root.plan.status != "explicit":
            _drop_helper_explicit(active, active.root.plan.reason or "provider_legacy")
        _write_text_0644(bundle_path, compiled.text)
        helper_manifest_path: Path | None = None
        write_helper = (
            active.subagent.plan.status == "explicit" and helper_compiled is not None
        )
        root_status = active.root.plan.status
        root_channel = active.root.plan.channel if root_status == "explicit" else None
        root_fallback = (
            None if root_status == "explicit" else fallback_wire(active.root)
        )
        manifest = build_manifest(
            compiled,
            facts,
            _delivery_identity(
                status=root_status,
                seq=seq,
                artifacts_dir=artifacts_dir,
                agent_type=agent_type,
                model=model,
                invocation_id=invocation_id,
                provider_cli_version=cli_version,
                channel=root_channel,
                parent_invocation_id=None,
                session_ids=[],
                fallback=root_fallback,
                subagent=subagent_wire(active.subagent),
            ),
        )
        manifest_path = bundle_path.with_suffix(".json")
        _write_json_0644(manifest_path, manifest)
        if write_helper and helper_compiled is not None and helper_facts is not None:
            helper_bundle_path = instructions_dir / f"{seq:02d}-{label}.helper.md"
            helper_manifest_path = instructions_dir / f"{seq:02d}-{label}.helper.json"
            _write_text_0644(helper_bundle_path, helper_compiled.text)
            helper_manifest = build_manifest(
                helper_compiled,
                helper_facts,
                _delivery_identity(
                    status="explicit",
                    seq=seq,
                    artifacts_dir=artifacts_dir,
                    agent_type=agent_type,
                    model=model,
                    invocation_id=str(uuid.uuid4()),
                    provider_cli_version=cli_version,
                    channel=active.subagent.plan.channel,
                    parent_invocation_id=invocation_id,
                    session_ids=[],
                    fallback=None,
                    subagent=None,
                ),
            )
            _write_json_0644(helper_manifest_path, helper_manifest)
        bundle = manifest["bundle"]
        latest: dict[str, Any] = {
            "seq": seq,
            "provider": raw_label,
            "purpose": purpose,
            "sha256": bundle["sha256"],
            "common_digest": bundle["common_digest"],
            "manifest": f"{INSTRUCTIONS_DIR_NAME}/{manifest_path.name}",
            "delivery_status": root_status,
        }
        if helper_manifest_path is not None:
            latest["helper_manifest"] = (
                f"{INSTRUCTIONS_DIR_NAME}/{helper_manifest_path.name}"
            )
        summary = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "count": _manifest_count(instructions_dir),
            "latest": latest,
        }
        from sase.axe.run_agent_helpers import update_meta_field

        update_meta_field(artifacts_dir, AGENT_META_KEY, summary)
        os.environ[SASE_INSTRUCTIONS_FILE_ENV] = str(bundle_path)
        return _PreparedDelivery(
            active=active,
            bundle_path=bundle_path,
            manifest_path=manifest_path,
            helper_manifest_path=helper_manifest_path,
            artifacts_dir=artifacts_dir,
            label=label,
            raw_label=raw_label,
            purpose=purpose,
            seq=seq,
        )
    except Exception:
        try:
            if bundle_path.is_file() and bundle_path.stat().st_size == 0:
                bundle_path.unlink()
        except OSError:
            pass
        raise


def _rewrite_root_manifest(prepared: _PreparedDelivery) -> None:
    """Atomically rewrite the root manifest with session ids and fallbacks."""
    from sase.core.instruction_manifest import normalize_instruction_manifest
    from sase.llm_provider.instruction_delivery import fallback_wire, subagent_wire

    with open(prepared.manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        return
    delivery = manifest.get("delivery")
    if not isinstance(delivery, dict):
        return
    active = prepared.active
    root = active.root
    delivery["session_ids"] = list(active.session_ids)
    delivery["status"] = root.plan.status
    if root.plan.status == "explicit":
        delivery["channel"] = root.plan.channel
        delivery.pop("fallback", None)
    else:
        delivery["channel"] = None
        fallback = fallback_wire(root)
        if fallback is not None:
            delivery["fallback"] = fallback
        else:
            delivery.pop("fallback", None)
    delivery["subagent"] = subagent_wire(active.subagent)
    _write_json_0644(prepared.manifest_path, normalize_instruction_manifest(manifest))


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
    """Invoke *provider* with instruction delivery around the call.

    This is the only place that calls ``provider.invoke`` for a root
    invocation. With an ``artifacts_dir``, the bundle and v2 manifest are
    recorded, ``SASE_INSTRUCTIONS_FILE`` holds the bundle path during the
    call, and adapters may read :func:`current_instruction_delivery`.
    Afterwards the previous env value is restored. With no
    ``artifacts_dir``, ``provider.invoke`` runs directly.
    """
    if purpose not in _VALID_PURPOSES:
        raise ValueError(
            f"invalid instruction purpose {purpose!r}; "
            f"valid purposes: {', '.join(_VALID_PURPOSES)}"
        )
    if not artifacts_dir:
        return provider.invoke(prompt, **invoke_kwargs)
    from sase.llm_provider.instruction_delivery import (
        bind_instruction_delivery,
        notify_instruction_fallback,
        reset_instruction_delivery,
    )

    label = _sanitize_label(
        _resolve_provider_label(provider, artifacts_dir, provider_name)
    )
    previous_env = os.environ.get(SASE_INSTRUCTIONS_FILE_ENV)
    prepared: _PreparedDelivery | None = None
    token = None
    try:
        try:
            prepared = _prepare_delivery(
                provider,
                purpose=purpose,
                artifacts_dir=artifacts_dir,
                provider_name=provider_name,
                agent_type=agent_type,
                invoke_kwargs=invoke_kwargs,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:  # noqa: BLE001 - delivery never fails invoke.
            log.warning("instruction delivery render failed: %s", exc)
            _write_error_json(
                Path(artifacts_dir) / INSTRUCTIONS_DIR_NAME, label, purpose, exc
            )
            notify_instruction_fallback(
                _resolve_provider_label(provider, artifacts_dir, provider_name),
                "render_failed",
                detail=str(exc)[:2000],
            )
        if prepared is not None:
            token = bind_instruction_delivery(prepared.active)
        return provider.invoke(prompt, **invoke_kwargs)
    finally:
        if token is not None:
            reset_instruction_delivery(token)
        try:
            if prepared is not None:
                _rewrite_root_manifest(prepared)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:  # noqa: BLE001 - rewrite never fails invoke.
            log.warning("instruction manifest rewrite failed", exc_info=True)
        if previous_env is None:
            os.environ.pop(SASE_INSTRUCTIONS_FILE_ENV, None)
        else:
            os.environ[SASE_INSTRUCTIONS_FILE_ENV] = previous_env


__all__ = [
    "AGENT_META_KEY",
    "INSTRUCTIONS_DIR_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "invoke_with_instructions",
]
