"""Mode resolution for daemon rollout diagnostics."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from sase.daemon.paths import daemon_disabled
from sase.daemon.rollout_registry import (
    TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
    RolloutSurfaceRecord,
)
from sase.daemon._rollout_diagnostics_utils import (
    env_bool,
    lookup,
    operation_key,
    parse_mode,
    provider_operation,
    surface_env_name,
)

_SCHEDULER_MODE_ALIASES = {
    "off": "direct",
    "false": "direct",
    "0": "direct",
    "direct": "direct",
    "shadow": "shadow",
    "daemon": "daemon_authoritative",
    "daemon_authoritative": "daemon_authoritative",
    "authoritative": "daemon_authoritative",
    "on": "daemon_authoritative",
    "true": "daemon_authoritative",
    "1": "daemon_authoritative",
}

_PROVIDER_HOST_MODE_ALIASES = {
    "0": "direct",
    "false": "direct",
    "off": "direct",
    "direct": "direct",
    "shadow": "shadow",
    "host_preferred": "host_preferred",
    "host-preferred": "host_preferred",
    "preferred": "host_preferred",
    "daemon": "host_preferred",
    "on": "host_preferred",
    "true": "host_preferred",
    "1": "host_preferred",
    "host_required": "host_required",
    "host-required": "host_required",
    "required": "host_required",
}

_LOW_RISK_PROVIDER_HOST_MODES = {
    "llm.metadata": "host_preferred",
    "xprompt.catalog": "host_preferred",
    "vcs.query": "host_preferred",
    "workspace.metadata": "host_preferred",
    "workspace.resolve_ref": "host_preferred",
}


def effective_mode(
    record: RolloutSurfaceRecord,
    *,
    args: Any | None,
    config: Mapping[str, Any],
    top_level_disabled: bool,
) -> dict[str, Any]:
    top_source = _top_level_source(args)
    if top_level_disabled and record.family in {
        "milestone",
        "process",
        "read",
        "write",
        "scheduler",
        "provider_host",
        "mobile_gateway",
        "recovery",
    }:
        return {
            "mode": "disabled",
            "source": top_source,
            "blocked_reasons": ["top-level daemon escape hatch is active"],
        }
    if record.family == "milestone":
        return _milestone_mode(record, config)
    if record.family == "read":
        return _read_mode(record, config)
    if record.family == "read_diagnostics":
        return _boolean_config_mode(
            record,
            config,
            env_name="SASE_DAEMON_FALLBACK_DIAGNOSTICS",
            config_key="daemon.reads.fallback_diagnostics",
            enabled_mode="shadow",
            disabled_mode="disabled",
        )
    if record.family == "scheduler":
        return _scheduler_mode(record, config)
    if record.family == "provider_host":
        return _provider_host_mode(record, config)
    if record.family == "write":
        return {
            "mode": "direct",
            "source": {"type": "registry", "key": record.surface_id, "value": "direct"},
            "blocked_reasons": [],
        }
    if record.family == "mobile_gateway":
        return {
            "mode": "daemon_authoritative",
            "source": {
                "type": "registry",
                "key": record.surface_id,
                "value": "contract",
            },
            "blocked_reasons": [],
        }
    return {
        "mode": "available",
        "source": {"type": "registry", "key": record.surface_id, "value": "available"},
        "blocked_reasons": [],
    }


def _read_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    m1_enabled = _milestone_enabled(
        config,
        key="daemon.rollout.milestones.m1_read_through",
        env_name="SASE_DAEMON_M1_READ_THROUGH",
        default=True,
    )
    if not bool(m1_enabled["enabled"]):
        return _mode(
            "direct",
            str(m1_enabled["source"]["type"]),
            str(m1_enabled["source"]["key"]),
            m1_enabled["source"]["value"],
            blocked_reasons=["M1 read-through milestone is disabled"],
        )
    force_direct = env_bool("SASE_DAEMON_FORCE_DIRECT")
    if force_direct is True:
        return _mode("direct", "env", "SASE_DAEMON_FORCE_DIRECT", "1")
    global_env = env_bool("SASE_DAEMON_READS")
    if global_env is False:
        return _mode("direct", "env", "SASE_DAEMON_READS", "0")
    if global_env is True and record.surface_id == "read.global":
        return _mode("read_through", "env", "SASE_DAEMON_READS", "1")

    reads_enabled = lookup(config, "daemon.reads.enabled")
    if reads_enabled is False:
        return _mode("direct", "config", "daemon.reads.enabled", reads_enabled)
    if record.surface_id == "read.global":
        return _mode(
            "read_through" if reads_enabled is not False else "direct",
            "config",
            "daemon.reads.enabled",
            reads_enabled,
        )

    group = record.surface_id.removeprefix("read.")
    env_name = surface_env_name(group)
    surface_env = env_bool(env_name)
    if surface_env is not None:
        return _mode(
            "read_through" if surface_env else "direct",
            "env",
            env_name,
            os.environ.get(env_name),
        )
    key = f"daemon.reads.surfaces.{group}"
    value = lookup(config, key)
    return _mode("read_through" if value is True else "direct", "config", key, value)


def _milestone_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if record.surface_id == "milestone.m0_shadow_indexing":
        enabled = _milestone_enabled(
            config,
            key="daemon.rollout.milestones.m0_shadow_indexing",
            env_name="SASE_DAEMON_M0_SHADOW_INDEXING",
            default=True,
        )
        mode = "shadow" if bool(enabled["enabled"]) else "disabled"
        blocked = (
            []
            if bool(enabled["enabled"])
            else ["M0 shadow indexing milestone is disabled"]
        )
        return _mode_from_source(mode, enabled["source"], blocked_reasons=blocked)
    if record.surface_id == "milestone.m1_read_through":
        enabled = _milestone_enabled(
            config,
            key="daemon.rollout.milestones.m1_read_through",
            env_name="SASE_DAEMON_M1_READ_THROUGH",
            default=True,
        )
        mode = "read_through" if bool(enabled["enabled"]) else "disabled"
        blocked = (
            []
            if bool(enabled["enabled"])
            else ["M1 read-through milestone is disabled"]
        )
        return _mode_from_source(mode, enabled["source"], blocked_reasons=blocked)
    return {
        "mode": "available",
        "source": {"type": "registry", "key": record.surface_id, "value": "available"},
        "blocked_reasons": [],
    }


class _MilestoneEnabled(dict[str, Any]):
    def __bool__(self) -> bool:
        return bool(self["enabled"])


def _milestone_enabled(
    config: Mapping[str, Any],
    *,
    key: str,
    env_name: str,
    default: bool,
) -> _MilestoneEnabled:
    env_value = env_bool(env_name)
    if env_value is not None:
        return _MilestoneEnabled(
            enabled=env_value,
            source={"type": "env", "key": env_name, "value": os.environ.get(env_name)},
        )
    value = lookup(config, key)
    enabled = value if isinstance(value, bool) else default
    return _MilestoneEnabled(
        enabled=enabled,
        source={"type": "config", "key": key, "value": value},
    )


def _scheduler_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    env_names = {
        "scheduler.launch": (
            "SASE_DAEMON_SCHEDULER_LAUNCH_MODE",
            "SASE_SCHEDULER_LAUNCH_MODE",
        ),
        "scheduler.lifecycle": (
            "SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE",
            "SASE_SCHEDULER_LIFECYCLE_MODE",
        ),
        "scheduler.axe": ("SASE_DAEMON_SCHEDULER_AXE_MODE",),
    }[record.surface_id]
    for env_name in env_names:
        parsed = parse_mode(os.environ.get(env_name), _SCHEDULER_MODE_ALIASES)
        if parsed is not None:
            return _mode(parsed, "env", env_name, os.environ.get(env_name))
    key = record.config_keys[0] if record.config_keys else "daemon.scheduler"
    parsed = parse_mode(lookup(config, key), _SCHEDULER_MODE_ALIASES) or "direct"
    if record.surface_id == "scheduler.axe" and parsed == "shadow":
        parsed = "direct"
    return _mode(parsed, "config", key, lookup(config, key))


def _provider_host_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if os.environ.get("SASE_DISABLE_PROVIDER_HOST_ROUTING"):
        return _mode("direct", "env", "SASE_DISABLE_PROVIDER_HOST_ROUTING", "1")
    operation = provider_operation(record)
    specific_env = (
        f"SASE_PROVIDER_HOST_{operation_key(operation).upper()}_MODE"
        if operation
        else None
    )
    if specific_env:
        parsed = parse_mode(os.environ.get(specific_env), _PROVIDER_HOST_MODE_ALIASES)
        if parsed is not None:
            return _mode(parsed, "env", specific_env, os.environ.get(specific_env))
    parsed = parse_mode(
        os.environ.get("SASE_PROVIDER_HOST_MODE"), _PROVIDER_HOST_MODE_ALIASES
    )
    if parsed is not None:
        return _mode(
            parsed,
            "env",
            "SASE_PROVIDER_HOST_MODE",
            os.environ.get("SASE_PROVIDER_HOST_MODE"),
        )
    legacy = env_bool("SASE_PROVIDER_HOST_QUERIES")
    if legacy is not None and operation in _LOW_RISK_PROVIDER_HOST_MODES:
        return _mode(
            "host_preferred" if legacy else "direct",
            "env",
            "SASE_PROVIDER_HOST_QUERIES",
            os.environ.get("SASE_PROVIDER_HOST_QUERIES"),
        )
    if record.surface_id == "provider_host.global":
        key = "daemon.provider_host.default_mode"
        parsed = (
            parse_mode(lookup(config, key), _PROVIDER_HOST_MODE_ALIASES) or "direct"
        )
        return _mode(parsed, "config", key, lookup(config, key))
    key = record.config_keys[0] if record.config_keys else ""
    parsed = parse_mode(lookup(config, key), _PROVIDER_HOST_MODE_ALIASES)
    if parsed is None:
        parsed = _LOW_RISK_PROVIDER_HOST_MODES.get(operation or "", "direct")
    return _mode(parsed, "config", key, lookup(config, key))


def _boolean_config_mode(
    record: RolloutSurfaceRecord,
    config: Mapping[str, Any],
    *,
    env_name: str,
    config_key: str,
    enabled_mode: str,
    disabled_mode: str,
) -> dict[str, Any]:
    env_value = env_bool(env_name)
    if env_value is not None:
        return _mode(
            enabled_mode if env_value else disabled_mode,
            "env",
            env_name,
            os.environ.get(env_name),
        )
    value = lookup(config, config_key)
    return _mode(
        enabled_mode if value is True else disabled_mode,
        "config",
        config_key or record.surface_id,
        value,
    )


def _mode(
    mode: str,
    source_type: str,
    key: str,
    value: Any,
    *,
    blocked_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "source": {"type": source_type, "key": key, "value": value},
        "blocked_reasons": blocked_reasons or [],
    }


def _mode_from_source(
    mode: str,
    source: Mapping[str, Any],
    *,
    blocked_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "source": dict(source),
        "blocked_reasons": blocked_reasons or [],
    }


def top_level_state(args: Any | None) -> dict[str, Any]:
    return {
        "disabled": daemon_disabled(args),
        "source": _top_level_source(args),
    }


def _top_level_source(args: Any | None) -> dict[str, Any]:
    if bool(getattr(args, "no_daemon", False)):
        return {"type": "arg", "key": "--no-daemon", "value": True}
    env_value = os.environ.get(TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV)
    if env_bool(TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV) is True:
        return {
            "type": "env",
            "key": TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV,
            "value": env_value,
        }
    return {"type": "default", "key": TOP_LEVEL_DAEMON_ESCAPE_HATCH_ENV, "value": False}


__all__ = [
    "effective_mode",
    "top_level_state",
]
