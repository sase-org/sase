"""Agent reference resolution helpers for the run agent runner."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class _ResolvedWaitDependency:
    """One waited dependency resolved for runtime prompt context."""

    wait_name: str
    agent_name: str | None
    agent_artifacts_dirs: tuple[str, ...] = ()
    chat_path: str | None = None


@dataclass(frozen=True)
class WaitDependencyResolution:
    """Shared waited dependency data for chat and artifact context."""

    requested_names: tuple[str, ...] = ()
    entries: tuple[_ResolvedWaitDependency, ...] = ()
    chats: list[str] = field(default_factory=list)

    @classmethod
    def from_chats(
        cls,
        chats: list[str],
        *,
        wait_names: list[str] | tuple[str, ...] = (),
    ) -> WaitDependencyResolution:
        return cls(requested_names=tuple(wait_names), chats=list(chats))

    @property
    def wait_names(self) -> tuple[str, ...]:
        return self.requested_names

    def artifact_context_producer_groups(self) -> list[Any]:
        """Return facade producer groups without importing the facade eagerly."""
        from sase.core.artifact_context_query_facade import (
            ArtifactContextProducerGroup,
        )

        return [
            ArtifactContextProducerGroup(entry.wait_name, entry.agent_artifacts_dirs)
            for entry in self.entries
            if entry.agent_artifacts_dirs
        ]


class WaitRuntimeNamespace:
    """Runtime ``wait`` namespace exposed to Jinja prompt rendering."""

    def __init__(self, resolution: WaitDependencyResolution) -> None:
        self._resolution = resolution
        self._artifacts: list[dict[str, Any]] | None = None

    @property
    def chats(self) -> list[str]:
        return self._resolution.chats

    @property
    def artifacts(self) -> list[dict[str, Any]]:
        if self._artifacts is None:
            groups = self._resolution.artifact_context_producer_groups()
            if groups:
                from sase.core.artifact_context_query_facade import (
                    query_artifact_context,
                )

                self._artifacts = query_artifact_context(groups)
            else:
                self._artifacts = []
        return self._artifacts


_LAST_WAIT_RESOLUTION: WaitDependencyResolution | None = None


def resolve_wait_context(wait_names: list[str]) -> WaitDependencyResolution:
    """Resolve waited names once for ``wait_chats`` and ``wait`` runtime data.

    Called after :func:`wait_for_dependencies` returns, so each completed
    agent should have a ``done.json`` with a ``response_path`` field. Names
    that can't be resolved or whose agent has no ``response_path`` are skipped from
    ``wait_chats`` with a warning; order of the remaining names is preserved,
    including duplicates. Artifact producer groups retain resolved successful
    producers even when the chat transcript is missing.
    """
    from sase.output import print_status

    entries: list[_ResolvedWaitDependency] = []
    chats: list[str] = []
    for name in wait_names:
        resolved = _resolve_wait_dependency_entry(name)
        if resolved is None:
            print_status(
                f"wait_chats: no done agent found for '{name}' — skipping",
                "warning",
            )
            continue
        entry, done_path = resolved
        try:
            with open(done_path, encoding="utf-8") as f:
                done_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            print_status(
                f"wait_chats: cannot read done.json for '{name}' ({exc}) — skipping",
                "warning",
            )
            entries.append(entry)
            continue
        response_path = done_data.get("response_path")
        if not response_path:
            print_status(
                f"wait_chats: agent '{name}' has no response_path — skipping",
                "warning",
            )
            entries.append(entry)
            continue
        response = str(response_path)
        chats.append(response)
        entries.append(
            _ResolvedWaitDependency(
                wait_name=entry.wait_name,
                agent_name=entry.agent_name,
                agent_artifacts_dirs=entry.agent_artifacts_dirs,
                chat_path=response,
            )
        )
    return WaitDependencyResolution(
        requested_names=tuple(wait_names),
        entries=tuple(entries),
        chats=chats,
    )


def resolve_wait_chat_paths(wait_names: list[str]) -> list[str]:
    """Resolve waited-for agent names to ``~/.sase/chats/`` transcript paths."""
    global _LAST_WAIT_RESOLUTION
    _LAST_WAIT_RESOLUTION = resolve_wait_context(wait_names)
    return _LAST_WAIT_RESOLUTION.chats


def last_wait_resolution_or_chats(
    wait_names: list[str],
    wait_chats: list[str],
) -> WaitDependencyResolution:
    """Return the latest full resolution when it matches compatibility output."""
    if (
        _LAST_WAIT_RESOLUTION is not None
        and _LAST_WAIT_RESOLUTION.wait_names == tuple(wait_names)
        and _LAST_WAIT_RESOLUTION.chats == wait_chats
    ):
        return _LAST_WAIT_RESOLUTION
    return WaitDependencyResolution.from_chats(wait_chats, wait_names=wait_names)


def _resolve_wait_dependency_entry(
    wait_name: str,
) -> tuple[_ResolvedWaitDependency, str] | None:
    from sase.agent.names import (
        AgentNameTemplateError,
        NamedAgent,
        find_agent_clan,
        find_agent_family,
        is_agent_name_template,
        resolve_resume_agent_name,
        resolve_agent_name_template_reference,
    )
    from sase.agent.names._lookup_artifacts import is_success_outcome
    from sase.plan_chain import is_agent_family_member

    try:
        resume_agent = resolve_resume_agent_name(wait_name)
    except AgentNameTemplateError:
        resume_agent = None

    try:
        name = resolve_agent_name_template_reference(wait_name)
    except AgentNameTemplateError:
        if resume_agent is None:
            return None
        name = wait_name

    selected: NamedAgent | None = None
    producer_dirs: tuple[str, ...] = ()

    if not is_agent_name_template(wait_name):
        clan = find_agent_clan(name)
        if clan is not None and clan.is_complete:
            producers = _matching_group_members(
                [
                    member
                    for member in clan.members
                    if is_success_outcome(member.outcome)
                ],
                resume_agent,
            )
            if producers:
                selected_member = max(producers, key=lambda member: member.timestamp)
                selected = NamedAgent(
                    name=selected_member.name,
                    artifacts_dir=str(selected_member.artifacts_dir),
                    is_done=True,
                    outcome=selected_member.outcome,
                )
                producer_dirs = tuple(str(member.artifacts_dir) for member in producers)

        if selected is None and not is_agent_family_member(name):
            family = find_agent_family(name)
            if family is not None:
                producers = _matching_group_members(
                    [
                        member
                        for member in family.members
                        if is_success_outcome(member.outcome)
                    ],
                    resume_agent,
                )
                if producers:
                    selected_member = max(
                        producers,
                        key=lambda member: member.timestamp,
                    )
                    selected = NamedAgent(
                        name=selected_member.name,
                        artifacts_dir=str(selected_member.artifacts_dir),
                        is_done=True,
                        outcome=selected_member.outcome,
                    )
                    producer_dirs = tuple(
                        str(member.artifacts_dir) for member in producers
                    )

    if selected is None:
        selected = resume_agent
        if selected is None:
            return None
        if is_success_outcome(selected.outcome):
            producer_dirs = (selected.artifacts_dir,)

    entry = _ResolvedWaitDependency(
        wait_name=wait_name,
        agent_name=selected.name,
        agent_artifacts_dirs=_stable_existing_dirs(producer_dirs),
    )
    return entry, os.path.join(selected.artifacts_dir, "done.json")


def _matching_group_members(
    members: list[Any],
    selected_agent: Any,
) -> list[Any]:
    if selected_agent is None:
        return members
    selected_dir = str(
        Path(selected_agent.artifacts_dir).expanduser().resolve(strict=False)
    )
    if not any(
        str(member.artifacts_dir.expanduser().resolve(strict=False)) == selected_dir
        for member in members
    ):
        return []
    return members


def _stable_existing_dirs(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        str(Path(path).expanduser().resolve(strict=False)) for path in paths if path
    )


def resolve_agent_refs_in_prompt(prompt: str) -> tuple[str, str | None]:
    """Resolve @name agent references in VCS tags.

    Normalizes underscore VCS refs, extracts the VCS tag, checks for
    @name in the ref portion, and replaces it with the agent's patch.

    Returns (resolved_prompt, resolved_vcs_tag).
    """
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
        normalize_vcs_underscore_refs,
    )

    # Normalize #gh_@a -> #gh:@a so downstream only sees colon form.
    prompt = normalize_vcs_underscore_refs(prompt)

    # Extract the VCS tag (handles leading %directives).
    vcs_tag = extract_vcs_workflow_tag(prompt)
    if not vcs_tag:
        return prompt, None

    # Check if the ref portion is an @name reference.
    ref = extract_project_from_vcs_tag(vcs_tag)
    if not ref or not ref.startswith("@"):
        return prompt, vcs_tag

    agent_name = ref[1:]  # strip leading @
    if not agent_name:
        return prompt, vcs_tag

    # Resolve the agent reference.
    from sase.agent.names import resolve_agent_patch

    patch = resolve_agent_patch(agent_name)

    # Replace @name with the patch in the VCS tag portion.
    new_tag = vcs_tag.replace(f"@{agent_name}", patch)
    resolved_prompt = prompt.replace(vcs_tag, new_tag, 1)

    # Re-extract vcs_tag from the resolved prompt.
    resolved_vcs_tag = extract_vcs_workflow_tag(resolved_prompt)
    return resolved_prompt, resolved_vcs_tag
