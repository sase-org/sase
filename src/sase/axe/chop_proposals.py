"""Scaffold and launch validated agent proposals from chop results."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.core.axe_chop_facade import (
    derive_chop_agent_name,
    validate_chop_proposal,
)

from .chop_agents import build_chop_launch_env


@dataclass(frozen=True)
class _PreparedChopProposal:
    index: int
    proposal_id: str | None
    prompt: str
    workspace: str
    agent_name: str
    tribe: str
    model: str | None
    effort: str | None
    env: dict[str, str]
    dedupe_key: str | None
    wait_on: int | str | None


def _workspace_directive(workspace: str) -> str:
    return workspace if workspace.startswith("#") else f"#{workspace}"


def _scaffolded_prompt(proposal: _PreparedChopProposal, wait_name: str | None) -> str:
    lines = [
        _workspace_directive(proposal.workspace),
        f"%name:{proposal.agent_name}",
        f"%tribe:{proposal.tribe}",
    ]
    if proposal.model:
        lines.append(f"%model:{proposal.model}")
    if proposal.effort:
        lines.append(f"%effort:{proposal.effort}")
    if wait_name:
        lines.append(f"%wait:{wait_name}")
    lines.append(proposal.prompt.strip())
    return "\n".join(lines) + "\n"


def prepare_chop_proposals(
    chop_name: str,
    result: Mapping[str, Any],
    *,
    target_key: str | None = None,
    run_id: str | None = None,
) -> list[_PreparedChopProposal]:
    """Normalize, validate, and scaffold all proposals in result order."""
    prepared: list[_PreparedChopProposal] = []
    prior_ids: list[str] = []
    raw_proposals = result.get("proposed_launches", [])
    if not isinstance(raw_proposals, list):
        raise ValueError("proposed_launches must be a list")
    for index, raw in enumerate(raw_proposals):
        if not isinstance(raw, dict):
            raise ValueError(f"proposed_launches[{index}] must be an object")
        normalized = validate_chop_proposal(
            raw,
            index=index,
            prior_ids=prior_ids,
        )
        proposal_id_value = normalized.get("id")
        proposal_id = str(proposal_id_value) if proposal_id_value is not None else None
        if proposal_id is not None:
            prior_ids.append(proposal_id)
        configured_name = normalized.get("agent_name")
        agent_name = (
            str(configured_name)
            if configured_name
            else derive_chop_agent_name(
                chop_name,
                target_key=target_key,
                proposal_index=index,
                run_token=run_id,
            )
        )
        prepared.append(
            _PreparedChopProposal(
                index=index,
                proposal_id=proposal_id,
                prompt=str(normalized["prompt"]),
                workspace=str(normalized["workspace"]),
                agent_name=agent_name,
                tribe=str(normalized.get("tribe") or "chop"),
                model=str(normalized["model"]) if normalized.get("model") else None,
                effort=str(normalized["effort"]) if normalized.get("effort") else None,
                env={str(k): str(v) for k, v in dict(normalized["env"]).items()},
                dedupe_key=(
                    str(normalized["dedupe_key"])
                    if normalized.get("dedupe_key")
                    else None
                ),
                wait_on=normalized.get("wait_on"),
            )
        )
    return prepared


def proposal_previews(
    proposals: list[_PreparedChopProposal],
    *,
    once_per_decisions: Mapping[int, Mapping[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Return JSON-safe launch previews with planned wait dependencies."""
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    previews: list[dict[str, Any]] = []
    for proposal in proposals:
        wait_name = _resolve_wait_name(proposal.wait_on, names_by_index, names_by_id)
        once_per = (once_per_decisions or {}).get(proposal.index, {})
        validation = "duplicate" if once_per.get("outcome") == "duplicate" else "valid"
        previews.append(
            {
                "index": proposal.index,
                "id": proposal.proposal_id,
                "agent_name": proposal.agent_name,
                "tribe": proposal.tribe,
                "workspace": proposal.workspace,
                "model": proposal.model,
                "effort": proposal.effort,
                "wait_on": proposal.wait_on,
                "wait_name": wait_name,
                "env_names": sorted(proposal.env),
                "dedupe_key": once_per.get("key") or proposal.dedupe_key,
                "dedupe_reason": once_per.get("reason"),
                "prompt": _scaffolded_prompt(proposal, wait_name),
                "validation": validation,
            }
        )
        names_by_index[proposal.index] = proposal.agent_name
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = proposal.agent_name
    return previews


def _resolve_wait_name(
    wait_on: int | str | None,
    names_by_index: Mapping[int, str],
    names_by_id: Mapping[str, str],
) -> str | None:
    if wait_on is None:
        return None
    if isinstance(wait_on, int):
        return names_by_index[wait_on]
    return names_by_id[wait_on]


def launch_chop_proposals(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    proposals: list[_PreparedChopProposal],
    launch_agent_from_cwd_fn: Callable[..., Any],
) -> list[dict[str, Any]]:
    """Launch proposals in order and return durable launch descriptors."""
    names_by_index: dict[int, str] = {}
    names_by_id: dict[str, str] = {}
    launches: list[dict[str, Any]] = []
    for proposal in proposals:
        wait_name = _resolve_wait_name(proposal.wait_on, names_by_index, names_by_id)
        prompt = _scaffolded_prompt(proposal, wait_name)
        extra_env = dict(proposal.env)
        extra_env.update(
            build_chop_launch_env(
                lumberjack_name=lumberjack_name,
                chop_name=chop_name,
                prompt=prompt,
                run_id=run_id,
            )
        )
        result = launch_agent_from_cwd_fn(prompt, extra_env=extra_env)
        actual_name = str(getattr(result, "agent_name", "") or proposal.agent_name)
        names_by_index[proposal.index] = actual_name
        if proposal.proposal_id is not None:
            names_by_id[proposal.proposal_id] = actual_name
        launches.append(
            {
                "index": proposal.index,
                "id": proposal.proposal_id,
                "agent_name": actual_name,
                "pid": int(result.pid),
                "workspace": proposal.workspace,
                "workspace_num": int(getattr(result, "workspace_num", 0) or 0),
                "workspace_dir": str(getattr(result, "workspace_dir", "") or ""),
                "project_name": str(getattr(result, "project_name", "") or ""),
                "workflow_name": str(getattr(result, "workflow_name", "") or ""),
                "cl_name": str(getattr(result, "cl_name", "") or ""),
                "timestamp": str(getattr(result, "timestamp", "") or ""),
                "artifacts_dir": str(getattr(result, "artifacts_dir", "") or ""),
                "wait_on": proposal.wait_on,
                "wait_name": wait_name,
            }
        )
    return launches


__all__ = [
    "launch_chop_proposals",
    "prepare_chop_proposals",
    "proposal_previews",
]
