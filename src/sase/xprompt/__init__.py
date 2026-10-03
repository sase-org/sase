"""Temporary ``sase.xprompt`` import shim over the renamed ``sase.macro`` tree.

# TEMP(xprompt->macro shim): removed in audit-deploy.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
import types
from typing import Any

# TEMP(xprompt->macro shim): removed in audit-deploy.
_SUCCESSOR_SUBMODULES = {
    "models": "sase.macro.models",
    "directives": "sase.macro.directives",
    "workflow_validator_extract": "sase.macro.workflow_validator_extract",
    "catalog": "sase.macro.catalog",
    "loader_sources": "sase.macro.loader_sources",
    "processor": "sase.macro.processor",
    "loader_parsing": "sase.macro.loader_parsing",
    "runtime_context": "sase.macro.runtime_context",
    "workflow_executor_utils": "sase.macro.workflow_executor_utils",
}

# TEMP(xprompt->macro shim): removed in audit-deploy.
_NAME_TO_SUCCESSOR = {
    "InputType": "sase.macro.models",
    "XPromptValidationError": "sase.macro.models",
    "UNSET": "sase.macro.models",
    "replace_ref_in_vcs_tag": "sase.macro._parsing",
    "extract_vcs_workflow_tag": "sase.macro._parsing",
    "extract_xprompt_calls": "sase.macro.workflow_validator_extract",
    "process_xprompt_references": "sase.macro.processor",
    "extract_prompt_directives": "sase.macro.directives",
    "plan_prompt_fanout_variants": "sase.macro.directives",
    "NoXpromptsFound": "sase.macro.catalog",
    "PdfEngineUnavailable": "sase.macro.catalog",
    "build_xprompts_catalog": "sase.macro.catalog",
    "CatalogArtifact": "sase.macro.catalog",
    "CatalogStats": "sase.macro.catalog",
    "load_xprompts_from_plugins": "sase.macro.loader_sources",
    "expand_single_xprompt": "sase.macro.processor",
    "parse_yaml_front_matter": "sase.macro.loader_parsing",
    "bind_runtime_template_vars": "sase.macro.runtime_context",
    "render_template": "sase.macro.workflow_executor_utils",
    "render_toplevel_jinja2": "sase.macro.processor",
    "expand_xprompt_swarms_with_metadata": "sase.agent.macro_swarm",
    "list_patch_xprompt_tags": "sase.integrations.patch_tags",
}

# TEMP(xprompt->macro shim): removed in audit-deploy.
_SUBMODULE_NAMES = {
    "models": ("InputType", "XPromptValidationError", "UNSET"),
    "directives": ("extract_prompt_directives", "plan_prompt_fanout_variants"),
    "workflow_validator_extract": ("extract_xprompt_calls",),
    "catalog": (
        "build_xprompts_catalog",
        "CatalogArtifact",
        "CatalogStats",
        "NoXpromptsFound",
        "PdfEngineUnavailable",
    ),
    "loader_sources": ("load_xprompts_from_plugins",),
    "processor": (
        "process_xprompt_references",
        "expand_single_xprompt",
        "render_toplevel_jinja2",
    ),
    "loader_parsing": ("parse_yaml_front_matter",),
    "runtime_context": ("bind_runtime_template_vars",),
    "workflow_executor_utils": ("render_template",),
}


def _build_synthetic_submodule(short: str) -> types.ModuleType:
    """Build the synthetic ``sase.xprompt.<short>`` module. # TEMP(xprompt->macro shim): removed in audit-deploy."""
    real = importlib.import_module(
        _SUCCESSOR_SUBMODULES[short]
    )  # TEMP(xprompt->macro shim): removed in audit-deploy.
    synthetic = types.ModuleType(
        f"sase.xprompt.{short}"
    )  # TEMP(xprompt->macro shim): removed in audit-deploy.
    synthetic.__package__ = (
        "sase.xprompt"  # TEMP(xprompt->macro shim): removed in audit-deploy.
    )
    for name in _SUBMODULE_NAMES[
        short
    ]:  # TEMP(xprompt->macro shim): removed in audit-deploy.
        setattr(
            synthetic, name, getattr(real, name)
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.
    return synthetic  # TEMP(xprompt->macro shim): removed in audit-deploy.


class _XpromptSubmoduleLoader(importlib.abc.Loader):
    """Populate one synthetic ``sase.xprompt.<sub>`` module. # TEMP(xprompt->macro shim): removed in audit-deploy."""

    def __init__(
        self, short: str
    ) -> None:  # TEMP(xprompt->macro shim): removed in audit-deploy.
        self._short = short  # TEMP(xprompt->macro shim): removed in audit-deploy.

    def create_module(
        self, spec: importlib.machinery.ModuleSpec
    ) -> types.ModuleType | None:  # TEMP(xprompt->macro shim): removed in audit-deploy.
        return None  # TEMP(xprompt->macro shim): removed in audit-deploy.

    def exec_module(
        self, module: types.ModuleType
    ) -> None:  # TEMP(xprompt->macro shim): removed in audit-deploy.
        built = _build_synthetic_submodule(
            self._short
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.
        module.__dict__.update(
            built.__dict__
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.


class _XpromptShimFinder(importlib.abc.MetaPathFinder):
    """Serve synthetic ``sase.xprompt.<sub>`` modules without aliasing the real ones. # TEMP(xprompt->macro shim): removed in audit-deploy."""

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> (
        importlib.machinery.ModuleSpec | None
    ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
        if not fullname.startswith(
            "sase.xprompt."
        ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
            return None  # TEMP(xprompt->macro shim): removed in audit-deploy.
        short = fullname[
            len("sase.xprompt.") :
        ]  # TEMP(xprompt->macro shim): removed in audit-deploy.
        if (
            short not in _SUCCESSOR_SUBMODULES
        ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
            return None  # TEMP(xprompt->macro shim): removed in audit-deploy.
        return importlib.machinery.ModuleSpec(
            fullname, _XpromptSubmoduleLoader(short)
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.


class _XpromptSwarmFinder(importlib.abc.MetaPathFinder):
    """Resolve only ``sase.agent.xprompt_swarm`` onto the renamed swarm module. # TEMP(xprompt->macro shim): removed in audit-deploy."""

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> (
        importlib.machinery.ModuleSpec | None
    ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
        if (
            fullname != "sase.agent.xprompt_swarm"
        ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
            return None  # TEMP(xprompt->macro shim): removed in audit-deploy.
        return importlib.machinery.ModuleSpec(
            fullname, _XpromptSwarmLoader()
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.


class _XpromptSwarmLoader(importlib.abc.Loader):
    """Populate a synthetic swarm module from ``sase.agent.macro_swarm``. # TEMP(xprompt->macro shim): removed in audit-deploy."""

    def create_module(
        self, spec: importlib.machinery.ModuleSpec
    ) -> types.ModuleType | None:  # TEMP(xprompt->macro shim): removed in audit-deploy.
        return None  # TEMP(xprompt->macro shim): removed in audit-deploy.

    def exec_module(
        self, module: types.ModuleType
    ) -> None:  # TEMP(xprompt->macro shim): removed in audit-deploy.
        from sase.agent import (
            macro_swarm as real,
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.

        for key in dir(real):  # TEMP(xprompt->macro shim): removed in audit-deploy.
            if key.startswith(
                "__"
            ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
                continue  # TEMP(xprompt->macro shim): removed in audit-deploy.
            setattr(
                module, key, getattr(real, key)
            )  # TEMP(xprompt->macro shim): removed in audit-deploy.


def __getattr__(
    name: str,
) -> Any:  # TEMP(xprompt->macro shim): removed in audit-deploy.
    if (
        name in _NAME_TO_SUCCESSOR
    ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
        real = importlib.import_module(
            _NAME_TO_SUCCESSOR[name]
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.
        value = getattr(
            real, name
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.
        globals()[name] = value  # TEMP(xprompt->macro shim): removed in audit-deploy.
        return value  # TEMP(xprompt->macro shim): removed in audit-deploy.
    if (
        name in _SUCCESSOR_SUBMODULES
    ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
        module = importlib.import_module(
            f"sase.xprompt.{name}"
        )  # TEMP(xprompt->macro shim): removed in audit-deploy.
        globals()[name] = module  # TEMP(xprompt->macro shim): removed in audit-deploy.
        return module  # TEMP(xprompt->macro shim): removed in audit-deploy.
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}"
    )  # TEMP(xprompt->macro shim): removed in audit-deploy.


def _install_shim_finders() -> None:
    """Register the shim finders. # TEMP(xprompt->macro shim): removed in audit-deploy."""
    for finder_type in (
        _XpromptShimFinder,
        _XpromptSwarmFinder,
    ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
        if not any(
            isinstance(finder, finder_type) for finder in sys.meta_path
        ):  # TEMP(xprompt->macro shim): removed in audit-deploy.
            sys.meta_path.append(
                finder_type()
            )  # TEMP(xprompt->macro shim): removed in audit-deploy.


_install_shim_finders()  # TEMP(xprompt->macro shim): removed in audit-deploy.

__all__ = sorted(
    _NAME_TO_SUCCESSOR
)  # TEMP(xprompt->macro shim): removed in audit-deploy.
