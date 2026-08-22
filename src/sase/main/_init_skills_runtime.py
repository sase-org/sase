"""Typed boundary between the init-skills facade and workflow modules."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sase.main._init_skills_rendering import (
    RenderedSkillDeploymentTarget,
    RenderedSkillTarget,
)
from sase.main.init_plan import InitAction, InitOperation, InitPlan
from sase.xprompt.models import XPrompt


class _SkillManifestWrite(Protocol):
    """Manifest write fields consumed by the apply workflow."""

    @property
    def path(self) -> Path: ...

    @property
    def content(self) -> str | None: ...

    @property
    def source_commit(self) -> str: ...


@dataclass(frozen=True)
class InitSkillsRuntime:
    """Callbacks and configuration supplied by the public handler facade."""

    chezmoi_home: Path
    command_label: str
    prettier_warning: str
    delete_warning: str
    get_use_chezmoi: Callable[[], bool]
    provider_validation_error: Callable[[str | None], str | None]
    load_skill_sources: Callable[[], tuple[list[XPrompt], tuple[str, ...]]]
    prettier_available: Callable[[], bool]
    render_skill_deployment_targets: Callable[..., list[RenderedSkillDeploymentTarget]]
    render_skill_targets: Callable[..., list[RenderedSkillTarget]]
    registered_provider_names: Callable[[], tuple[str, ...]]
    planned_skill_operation: Callable[
        [RenderedSkillTarget], tuple[InitOperation, str] | None
    ]
    summarize_skill_actions: Callable[[tuple[InitAction, ...]], str]
    retired_delete_action: Callable[..., InitAction]
    prompt_overwrite: Callable[[Path, str], bool]
    prompt_delete_retired: Callable[..., bool]
    delete_retired_source: Callable[..., bool]
    skill_deploy_commit_tags: Callable[[str | None], dict[str, object]]
    deploy_to_chezmoi: Callable[..., int]
    deferred_skill_deploy_warnings: Callable[[int, str | None], tuple[str, ...]]
    skill_source_integrity_error: Callable[[], str | None]
    prepare_skill_manifest: Callable[..., tuple[_SkillManifestWrite | None, str | None]]
    plan_init_skills: Callable[[argparse.Namespace], InitPlan]
    run_init_skills: Callable[[argparse.Namespace], int]


__all__ = ["InitSkillsRuntime"]
