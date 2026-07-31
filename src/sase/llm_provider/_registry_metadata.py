"""Metadata normalization and cache fingerprints for LLM providers."""

import importlib.metadata
import os
import re
from dataclasses import asdict, is_dataclass
from typing import Any


def provider_path_env_var(provider_name: str) -> str:
    """Return the ``SASE_<PROVIDER>_PATH`` executable-override env var name.

    The provider name is upper-cased with runs of non-alphanumeric characters
    collapsed to a single underscore (e.g. ``"agy"`` -> ``"SASE_AGY_PATH"``).
    This is the single canonical derivation shared by the registry cache
    policy and the ``sase doctor`` provider checks, so registering a new
    provider never requires extending a hardcoded env-var list.
    """
    token = re.sub(r"[^A-Za-z0-9]+", "_", provider_name).strip("_").upper()
    return f"SASE_{token}_PATH"


def llm_metadata_cache_policy() -> dict[str, Any]:
    """Return cache invalidation inputs for host-routed LLM metadata."""

    entry_points = sorted(
        importlib.metadata.entry_points(group="sase_llm"),
        key=lambda item: item.name,
    )
    # Derive each provider's SASE_<PROVIDER>_PATH override from the registered
    # entry points (deduped, order-preserving) so a new provider's path env var
    # participates in cache invalidation without editing a hardcoded list.
    static_env_names = ("SASE_DISABLE_PLUGINS", "SASE_DISABLE_PLUGIN_LLM")
    provider_path_envs = dict.fromkeys(
        provider_path_env_var(ep.name) for ep in entry_points
    )
    env_names = (*static_env_names, *provider_path_envs)
    return {
        "version": 1,
        "plugin_entry_points": [
            {"name": ep.name, "value": ep.value} for ep in entry_points
        ],
        "environment": {name: os.environ.get(name) for name in env_names},
        "config": _config_fingerprint(),
    }


def provider_metadata(name: str, plugin: object) -> dict[str, Any]:
    """Return normalized metadata for one provider plugin."""
    provider_name = _call_optional(plugin, "llm_provider_name")
    short_name = _call_optional(plugin, "llm_provider_short_name") or name
    known_models = _call_optional(plugin, "llm_known_model_names") or []
    model_aliases = _call_optional(plugin, "llm_model_short_aliases") or {}
    skill_template_context = normalize_str_dict(
        _call_optional(plugin, "llm_skill_template_context") or {}
    )
    display_name = skill_template_context.get("provider_name") or provider_name or name
    retry_config = _call_optional(plugin, "llm_default_retry_config")
    auth_evidence = _auth_evidence_metadata(_call_optional(plugin, "llm_auth_evidence"))
    install_metadata = _install_metadata(_call_optional(plugin, "llm_install_metadata"))

    model_resolutions: dict[str, str] = {}
    resolve_model = getattr(plugin, "llm_resolve_model_name", None)
    if resolve_model is not None:
        for tier in ("large", "small"):
            try:
                model_resolutions[tier] = str(resolve_model(tier))
            except Exception:
                continue

    return {
        "provider_name": provider_name or name,
        "display_name": display_name,
        "short_name": short_name,
        "known_model_names": [str(model) for model in known_models],
        "model_short_aliases": normalize_str_dict(model_aliases),
        "skill_template_context": skill_template_context,
        "skill_deploy_subpath": _call_optional(plugin, "llm_skill_deploy_subpath"),
        "additional_skill_deploy_subpaths": _str_list(
            _call_optional(plugin, "llm_additional_skill_deploy_subpaths")
        ),
        "cli_status_color": _call_optional(plugin, "llm_cli_status_color"),
        "autodetect_priority": _call_optional(plugin, "llm_autodetect_priority"),
        "autodetect_cli_name": _call_optional(plugin, "llm_autodetect_cli_name"),
        "auth_evidence": auth_evidence,
        "install": install_metadata,
        "default_retry_config": _dataclass_to_dict(retry_config),
        "model_resolutions": model_resolutions,
        "hidden_from_model_pickers": (
            _call_optional(plugin, "llm_hidden_from_model_pickers") is True
        ),
    }


def _call_optional(plugin: object, method_name: str) -> Any:
    method = getattr(plugin, method_name, None)
    if method is None:
        return None
    try:
        return method()
    except Exception:
        return None


def _dataclass_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if is_dataclass(value):
        return dict(asdict(value))  # type: ignore[arg-type]
    if isinstance(value, dict):
        return dict(value)
    return None


def _auth_evidence_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "credential_paths": [],
            "api_key_env_vars": [],
            "auth_not_required": False,
        }
    return {
        "credential_paths": _str_list(value.get("credential_paths")),
        "api_key_env_vars": _str_list(value.get("api_key_env_vars")),
        "auth_not_required": value.get("auth_not_required") is True,
    }


def _install_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    metadata: dict[str, Any] = {
        "manager": _optional_str(value.get("manager")),
        "package": _optional_str(value.get("package")),
        "scope": _optional_str(value.get("scope")),
    }
    for key in (
        "display_name",
        "docs_url",
        "version_regex",
        "latest_version_package",
        "brew_package",
    ):
        if (normalized := _optional_str(value.get(key))) is not None:
            metadata[key] = normalized
    if argv := _argv_metadata(value.get("self_update_argv")):
        metadata["self_update_argv"] = argv
    if "version_argv" in value:
        metadata["version_argv"] = _argv_metadata(
            value.get("version_argv"), default=("--version",)
        )
    return metadata


def _argv_metadata(value: Any, *, default: tuple[str, ...] = ()) -> list[str]:
    if not isinstance(value, list | tuple):
        return list(default)
    argv = [str(item).strip() for item in value if str(item).strip()]
    return argv or list(default)


def normalize_str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return []


def _config_fingerprint() -> dict[str, Any]:
    from sase.content_layout import discover_project_root, resolve_project_layout

    paths = [os.path.expanduser("~/.config/sase/sase.yml")]
    project_root = discover_project_root()
    if project_root is not None:
        paths.extend(
            str(path) for path in resolve_project_layout(project_root).config.candidates
        )
    result: dict[str, Any] = {}
    for raw_path in paths:
        try:
            stat = os.stat(raw_path)
        except OSError:
            result[raw_path] = {"exists": False}
            continue
        result[raw_path] = {
            "exists": True,
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
        }
    return result
