"""Runner provider protocol, discovery, and registry.

Runner providers manage workspace lifecycle for VCS-based agent runs.
They are discovered via ``sase_runner_provider`` entry points and invoked
through ``%``-prefix directives (e.g. ``%git:sase``, ``%gh:org/repo``).
"""

import importlib.metadata
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RunnerContext:
    """Carries workspace state between pre/post agent phases.

    Attributes:
        project_name: Name of the project being worked on.
        project_file: Path to the project configuration file.
        workspace_dir: Path to the workspace directory for the agent.
        workspace_num: Numeric identifier for the workspace slot.
        checkout_target: The ref/branch/CL to check out.
        primary_workspace_dir: Path to the primary (non-ephemeral) workspace.
        should_release: Whether the workspace should be released after the run.
        head_before: Git HEAD (or equivalent) before the agent run.
        extra: Arbitrary provider-specific data.
    """

    project_name: str = ""
    project_file: str = ""
    workspace_dir: str = ""
    workspace_num: int = 0
    checkout_target: str = ""
    primary_workspace_dir: str = ""
    should_release: bool = True
    head_before: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostAgentResult:
    """Return type from the post-agent phase.

    Attributes:
        diff_path: Path to the generated diff file, if any.
        meta: Arbitrary metadata from the post-agent phase.
    """

    diff_path: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class RunnerProvider(ABC):
    """Abstract base class for runner providers.

    Runner providers manage the workspace lifecycle around agent runs:
    ``pre_agent`` sets up the workspace, and ``post_agent`` tears it down
    and collects results.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this provider (e.g. ``"git"``, ``"gh"``)."""

    @abstractmethod
    def pre_agent(
        self,
        ref: str,
        *,
        n: int | None = None,
        release: bool = True,
    ) -> RunnerContext:
        """Set up the workspace before the agent runs.

        Args:
            ref: The reference to check out (branch, CL, repo slug, etc.).
            n: Optional workspace number override.
            release: Whether the workspace should be released after the run.

        Returns:
            A RunnerContext carrying state for the post-agent phase.
        """

    @abstractmethod
    def post_agent(self, ctx: RunnerContext) -> PostAgentResult:
        """Tear down the workspace and collect results after the agent runs.

        Args:
            ctx: The RunnerContext returned by ``pre_agent``.

        Returns:
            A PostAgentResult with diff path and metadata.
        """


def get_runner_providers() -> dict[str, RunnerProvider]:
    """Discover runner providers via ``sase_runner_provider`` entry points.

    Follows the same pattern as
    :func:`sase.vcs_provider._registry._build_classification_pm`.

    Returns:
        A dict mapping provider name to provider instance.
    """
    providers: dict[str, RunnerProvider] = {}
    for ep in importlib.metadata.entry_points(group="sase_runner_provider"):
        try:
            cls = ep.load()
            instance = cls()
            providers[instance.name] = instance
        except Exception:
            logger.debug("Failed to load runner provider entry point %s", ep.name)
    return providers


def get_runner_provider_names() -> frozenset[str]:
    """Return the set of registered runner provider names.

    Lightweight wrapper around :func:`get_runner_providers` that returns
    only the name keys.
    """
    return frozenset(get_runner_providers())
