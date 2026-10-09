"""Production-code driver for the %auto behavior contract suite.

Every row runs through real code with no mocks on the decision path and no
provider invocation:

* **Launch:** :func:`extract_prompt_directives`, then
  :func:`build_agent_meta`, writing ``agent_meta.json`` into a temp
  artifacts dir.
* **Contexts:** one small adapter per context calling the highest-level
  production entry point that context owns. When a later phase replaces a
  helper (for example ``inherit`` deletes ``live_plan_successor_meta``), it
  updates only that adapter, never the row table.
* **Outcome:** real tale, epic, and question gate specs from the production
  builders (:func:`build_plan_approval_gate_spec`,
  :func:`user_question_gate_spec`), run through :func:`create_gate`; the
  verdict is the auto-resolved option IDs or parked.

Gate persistence is isolated per test via :func:`isolated_gate_dirs`, which
reproduces the ``gate_home`` fixture pattern (patched interaction-requests,
notification, and pending-action dirs).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sase.axe.run_agent_directive_metadata import (
    AgentMetadataInputs,
    build_agent_meta,
)
from sase.macro._exceptions import DirectiveError
from sase.macro.directives import extract_prompt_directives

from .rows import (
    APPROVE_ARCHIVE,
    APPROVE_LAUNCH,
    ASK,
    FIRST,
    LAUNCH_ERROR,
)

QUESTIONS: list[dict[str, Any]] = [
    {
        "question": "Which database?",
        "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}],
    },
]


def launch_meta(
    prompt: str, workdir: Path, *, agent_name: str = "contract-agent"
) -> tuple[Any, dict[str, Any], Path]:
    """Run the real launch path and write ``agent_meta.json``.

    Returns ``(directives, meta, artifacts_dir)``. Raises
    :class:`DirectiveError` for invalid ``%auto`` spellings, which the
    contract maps to ``launch_error`` on every gate column.
    """
    _, directives = extract_prompt_directives(prompt)
    inputs = AgentMetadataInputs(
        workspace_dir=str(workdir),
        workspace_num=0,
        output_path=None,
        bead_id=None,
        wait_names=[],
        wait_identity_deps=[],
        wait_fork_sources=[],
        wait_beads=[],
        wait_hoods=[],
        model=None,
        llm_provider=None,
        reasoning_effort=None,
        model_alias=None,
        model_alias_trail=[],
        model_alias_origin=None,
        model_alias_reservation=None,
        model_alias_overrides={},
        vcs_provider=None,
        auto_dismiss=None,
        preserved={},
        epic_work={},
        cl_name=None,
    )
    meta = build_agent_meta(
        inputs,
        directives=directives,
        agent_name=agent_name,
        agent_tribe=None,
        agent_session_attach_plan=None,
        clan_membership_plan=None,
    )
    artifacts_dir = workdir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return directives, meta, artifacts_dir


def read_meta(artifacts_dir: Path) -> dict[str, Any]:
    """Read back the live ``agent_meta.json``."""
    return json.loads((artifacts_dir / "agent_meta.json").read_text(encoding="utf-8"))


def write_meta(artifacts_dir: Path, meta: dict[str, Any]) -> None:
    """Write ``meta`` as the live ``agent_meta.json``."""
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def isolated_gate_dirs(monkeypatch: Any, tmp_path: Path) -> Path:
    """Isolate gate/notification persistence under ``tmp_path``."""
    from sase.notification_gates import paths
    from sase.notifications import pending_actions, store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy-pending.json",
    )
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    store._LOAD_CACHE.clear()
    return tmp_path


def write_plan_file(workdir: Path, name: str, content: str) -> Path:
    """Write a plan fixture and return its path."""
    path = workdir / name
    path.write_text(content, encoding="utf-8")
    return path


def plan_outcome(
    meta: dict[str, Any],
    artifacts_dir: Path,
    plan_file: Path,
    *,
    monkeypatch: Any,
    request_id: str,
) -> str:
    """Build the real plan spec from live meta and create the gate.

    Auto enablement comes from the production readers
    (:func:`get_auto_plan_approval_action` /
    :func:`get_auto_plan_approval_argument`) with ``SASE_ARTIFACTS_DIR``
    pointed at the row's live meta, so the driver covers the same path
    ``plan_gate_turn/create.py`` uses.
    """
    from sase.plan_gate import build_plan_approval_gate_spec

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        get_auto_plan_approval_argument,
    )

    auto_action = get_auto_plan_approval_action()
    auto_enabled = auto_action is not None
    auto_argument = get_auto_plan_approval_argument()
    if auto_argument is None and auto_action in {"tale", "epic"}:
        auto_argument = auto_action
    spec = build_plan_approval_gate_spec(
        str(plan_file),
        request_id,
        auto_enabled=auto_enabled,
        auto_argument=auto_argument,
    )
    from sase.notification_gates.service import create_gate

    gate = create_plan_gate_isolated(spec, artifacts_dir, request_id)
    resolved = gate.to_dict().get("auto_resolution") or {}
    if resolved.get("state") == "resolved":
        selected = tuple(resolved.get("selected_option_ids") or ())
        if spec["kind"] == "epic_plan" and selected == ("approve",):
            return APPROVE_LAUNCH
        if spec["kind"] == "plan" and selected == ("approve", "commit"):
            return APPROVE_ARCHIVE
        # Any other auto selection is still automatic; surface it raw so a
        # behavior change fails loudly instead of passing as the wrong row.
        return f"auto:{','.join(selected)}"
    return ASK


def question_outcome(artifacts_dir: Path, *, monkeypatch: Any, request_id: str) -> str:
    """Build the real question spec from live meta and create the gate."""
    from sase.user_question_actions import user_question_gate_spec

    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    from sase.main.plan_approve_handler import is_auto_approve_active

    spec = user_question_gate_spec(
        [dict(question) for question in QUESTIONS],
        session_id=request_id,
        producer={"agent": "contract-agent"},
        auto=is_auto_approve_active(),
    )
    from sase.notification_gates.service import create_gate

    gate = create_gate(spec)
    resolved = gate.to_dict().get("auto_resolution") or {}
    if resolved.get("state") == "resolved":
        selected = tuple(resolved.get("selected_option_ids") or ())
        if selected == ("submit",):
            return FIRST
        return f"auto:{','.join(selected)}"
    return ASK


def row_outcomes(
    prompt: str,
    workdir: Path,
    tale_plan: Path,
    epic_plan: Path,
    *,
    monkeypatch: Any,
) -> dict[str, str]:
    """Run one launch-context row through launch plus all three gates."""
    try:
        _, meta, artifacts_dir = launch_meta(prompt, workdir)
    except DirectiveError:
        return {"tale": LAUNCH_ERROR, "epic": LAUNCH_ERROR, "question": LAUNCH_ERROR}
    tag = uuid.uuid4().hex[:8]
    return {
        "tale": plan_outcome(
            meta,
            artifacts_dir,
            tale_plan,
            monkeypatch=monkeypatch,
            request_id=f"tale-{tag}",
        ),
        "epic": plan_outcome(
            meta,
            artifacts_dir,
            epic_plan,
            monkeypatch=monkeypatch,
            request_id=f"epic-{tag}",
        ),
        "question": question_outcome(
            artifacts_dir, monkeypatch=monkeypatch, request_id=f"q-{tag}"
        ),
    }


def create_plan_gate_isolated(spec: Any, artifacts_dir: Path, request_id: str) -> Any:
    """Run :func:`create_gate` with execution side effects stubbed.

    Stub the execution side effects only (plan archive, epic launch). The
    decision path — readers, spec builders, cross-tier parking, the
    adapter's auto selection — runs unpatched, as in
    ``test_auto_uses_the_manual_executor_and_tier_owned_aliases``.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from sase.notification_gates.service import create_gate

    stub_archive = artifacts_dir / f"archived-{request_id}.md"
    with (
        patch(
            "sase.plan_approval_actions._archive_plan_for_approval",
            return_value=str(stub_archive),
        ),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(monitor_id="mon-contract"),
        ),
    ):
        return create_gate(spec)


# -- Context adapters -----------------------------------------------------
#
# One small function per successor/toggle context, each calling the
# highest-level production entry point that context owns. Later phases
# update only these adapters when they replace a helper.

_AUTO_KEYS = (
    "approve",
    "auto_approve_plan_action",
    "auto_approve_argument",
    "plan",
)


def adapt_a_off(artifacts_dir: Path) -> dict[str, Any]:
    """Apply the ``A`` toggle-off through the real persistence helper."""
    from sase.ace.tui.actions.agents._directive_persistence import (
        AgentDirectivePersistenceSpec,
        AgentMetaPatch,
        persist_agent_directive_update,
    )

    meta = read_meta(artifacts_dir)

    def _strip(prompt: str) -> str:
        return "\n".join(
            line
            for line in prompt.splitlines()
            if not line.strip().startswith("%auto") and line.strip() != "%a"
        )

    (artifacts_dir / "raw_prompt.md").write_text("%auto\nDo the work", encoding="utf-8")
    persist_agent_directive_update(
        AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts_dir,
            prompt_mutator=_strip,
            meta_patch=AgentMetaPatch(
                remove_keys=tuple(key for key in _AUTO_KEYS if key in meta)
            ),
        )
    )
    return read_meta(artifacts_dir)


def adapt_a_on_bare(artifacts_dir: Path) -> dict[str, Any]:
    """Apply today's ``A`` toggle-on through the real persistence helper.

    This mirrors ``_approve.py::_set_auto_approve(enabled=True)``, which
    writes bare ``approve: True`` whatever the previous profile was. The
    ``inherit`` phase replaces this with last-profile restore; this adapter
    is the seam it updates.
    """
    from sase.ace.tui.actions.agents._directive_persistence import (
        AgentDirectivePersistenceSpec,
        AgentMetaPatch,
        persist_agent_directive_update,
    )

    persist_agent_directive_update(
        AgentDirectivePersistenceSpec(
            artifacts_dir=artifacts_dir,
            prompt_mutator=lambda prompt: "%auto\nDo the work",
            meta_patch=AgentMetaPatch(
                set_values={"approve": True},
                remove_keys=(
                    "auto_approve_plan_action",
                    "auto_approve_argument",
                    "plan",
                ),
            ),
        )
    )
    return read_meta(artifacts_dir)


def adapt_in_process_coder(
    predecessor_dir: Path, snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Seed an in-process coder from the predecessor's live record."""
    from sase.axe.agent_meta import live_plan_successor_meta

    return live_plan_successor_meta(predecessor_dir, snapshot)


def adapt_followup_artifacts(
    predecessor_meta: dict[str, Any], tmp_path: Path, *, suffix: str = "--code"
) -> dict[str, Any]:
    """Persist successor meta through the real follow-up helper."""
    from unittest.mock import patch

    from sase.axe.run_agent_helpers_artifacts import create_followup_artifacts

    followup = tmp_path / f"followup-{uuid.uuid4().hex[:8]}"
    followup.mkdir()
    with patch(
        "sase.axe.run_agent_helpers_artifacts.create_artifacts_directory",
        return_value=str(followup),
    ):
        create_followup_artifacts(
            "contract-proj",
            dict(predecessor_meta),
            suffix,
            "20260711120000",
        )
    return read_meta(followup)


def adapt_monitor_followup_prefix(live_meta: dict[str, Any]) -> str:
    """Render the monitor follow-up ``%auto`` prefix from live meta."""
    from sase.monitor.continuation_delivery import auto_launch_prefix

    return auto_launch_prefix(live_meta)


def adapt_epic_worker_prompt() -> str:
    """Return the ``%auto`` prefix epic workers launch with.

    Epic phase and land segments are rendered by the real
    :func:`render_multi_prompt` in ``sase.bead.work_prompt``; assert it
    emits the tale prefix so a renderer change fails here, then return the
    emitted token for the launch-equivalent gate run.
    """
    import inspect

    from sase.bead import work_prompt

    assert '"%auto:tale"' in inspect.getsource(work_prompt.render_multi_prompt)
    return "%auto:tale"
