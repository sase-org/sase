"""TUI provenance: history_text and generated origins (phase tui-provenance)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agent_workflow._pending_launch import (
    PendingLaunch,
    PendingLaunchStage,
    begin_pending_launch,
)
from sase.ace.tui.actions.agent_workflow._types import (
    PromptContext,
    begin_prompt_session,
    current_prompt_session,
)
from sase.ace.tui.models.agent import is_generated_relaunch_source


def _context() -> PromptContext:
    return PromptContext(
        project_name="home",
        cl_name=None,
        project_file="/tmp/home/home.sase",
        workspace_dir="/tmp",
        workspace_num=0,
        workflow_name="ace(run)-1",
        timestamp="1",
        history_sort_key="home",
        display_name="home",
        update_target="",
        is_home_mode=True,
    )


def _agent(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "agent_clan": None,
        "epic_bead_id": None,
        "phase_bead_id": None,
        "agent_name": "standalone",
        "tribe": None,
        "clan_tribe": None,
        "clan_tribes": (),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_member_predicate_matrix() -> None:
    assert not is_generated_relaunch_source(_agent())
    assert is_generated_relaunch_source(_agent(agent_clan="clan-1"))
    assert is_generated_relaunch_source(_agent(epic_bead_id="sase-1d8"))
    assert is_generated_relaunch_source(_agent(phase_bead_id="sase-1d8.1"))
    assert is_generated_relaunch_source(_agent(agent_name="sase-1d8.3"))
    assert is_generated_relaunch_source(_agent(tribe="chop"))
    assert is_generated_relaunch_source(_agent(tribe="job"))
    assert is_generated_relaunch_source(_agent(clan_tribe="chop"))
    assert is_generated_relaunch_source(_agent(clan_tribes=("job",)))
    # Hand-assigned non-routine tribe stays typed.
    assert not is_generated_relaunch_source(_agent(tribe="review"))
    assert not is_generated_relaunch_source(_agent(agent_name="standalone"))


def test_prompt_session_origin_defaults_typed_and_copies_to_pending() -> None:
    app = SimpleNamespace()
    session = begin_prompt_session(app, _context())
    assert session.prompt_origin == "typed"
    launch = begin_pending_launch(
        app,
        prompt="hello world this is typed",
        context=session.context,
        keep_bar=False,
        extra_payload=None,
        bulk_patches=(),
        relaunch_operation=session.relaunch_operation,
        stage=PendingLaunchStage.SUBMITTING,
        prompt_origin=session.prompt_origin,
    )
    assert launch.prompt_origin == "typed"
    assert launch.history_prompt is None


def test_generated_session_copies_to_pending() -> None:
    app = SimpleNamespace()
    session = begin_prompt_session(app, _context(), prompt_origin="generated")
    assert session.prompt_origin == "generated"
    assert current_prompt_session(app) is session
    launch = begin_pending_launch(
        app,
        prompt="member prompt text here",
        context=session.context,
        keep_bar=False,
        extra_payload=None,
        bulk_patches=(),
        relaunch_operation=session.relaunch_operation,
        stage=PendingLaunchStage.SUBMITTING,
        prompt_origin=session.prompt_origin,
    )
    assert launch.prompt_origin == "generated"


def test_provider_guard_finish_records_history_prompt_before_remodel() -> None:
    from sase.ace.tui.actions.agent_workflow._launch_provider_guard import (
        _GuardUnitState,
        _ProviderGuardSession,
    )

    class GuardHost:
        def __init__(self) -> None:
            self.continued: list[PendingLaunch] = []

        def _continue_pending_launch(self, launch: PendingLaunch) -> None:
            self.continued.append(launch)

        def _provider_guard_session(self, launch: PendingLaunch | None):
            session = launch.provider_guard_session if launch is not None else None
            return session if isinstance(session, _ProviderGuardSession) else None

    from sase.ace.tui.actions.agent_workflow._launch_provider_guard import (
        LaunchProviderGuardMixin,
    )

    host = GuardHost()
    launch = PendingLaunch(
        launch_id="launch-1",
        prompt="#research_swarm(topic=hi) run this now please",
        context=_context(),
        keep_bar=False,
        extra_payload=None,
        bulk_patches=(),
        relaunch_operation=None,
        stage=PendingLaunchStage.PROVIDER_CHECK,
    )
    launch.provider_guard_session = _ProviderGuardSession(
        original_total=1,
        units=[
            _GuardUnitState(
                index=1,
                prompt="expanded member prompt text here",
                template_group=None,
                swarm_xprompts=(),
                remodeled=True,
            )
        ],
    )
    LaunchProviderGuardMixin._finish_provider_guard_launch(host, launch)  # type: ignore[arg-type]
    assert launch.history_prompt == "#research_swarm(topic=hi) run this now please"
    assert launch.prompt == "expanded member prompt text here"
    assert host.continued == [launch]


def test_submit_single_payload_carries_history_text_and_origin() -> None:
    from sase.ace.tui.actions.agent_workflow._launch_submission import (
        LaunchSubmissionMixin,
    )

    captured: dict[str, Any] = {}

    class SubmitHost(LaunchSubmissionMixin):
        def _submit_launch_proc(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return SimpleNamespace(proc_id="proc-1")

    host = SubmitHost()
    host._prompt_context = None  # type: ignore[attr-defined]
    launch = PendingLaunch(
        launch_id="launch-2",
        prompt="expanded member prompt text here",
        context=_context(),
        keep_bar=False,
        extra_payload=None,
        bulk_patches=(),
        relaunch_operation=None,
        stage=PendingLaunchStage.SUBMITTING,
        history_prompt="#research_swarm(topic=hi) run this now please",
        prompt_origin="generated",
    )
    # Bypass the proc observer / record machinery used by finish_pending_launch.
    import sase.ace.tui.actions.agent_workflow._launch_submission as submission_mod

    orig_finish = submission_mod.finish_pending_launch
    orig_schedule = submission_mod.schedule_submit_time_vcs_replay
    submission_mod.finish_pending_launch = lambda *a, **k: None  # type: ignore[assignment]
    submission_mod.schedule_submit_time_vcs_replay = lambda *a, **k: None  # type: ignore[assignment]
    try:
        LaunchSubmissionMixin._submit_single_pending_launch(host, launch)  # type: ignore[arg-type]
    finally:
        submission_mod.finish_pending_launch = orig_finish  # type: ignore[assignment]
        submission_mod.schedule_submit_time_vcs_replay = orig_schedule  # type: ignore[assignment]
    payload = captured["extra_payload"]
    assert payload["history_text"] == "#research_swarm(topic=hi) run this now please"
    assert payload["history_origin"] == "generated"
    assert (
        captured["submitted_prompt"] == "#research_swarm(topic=hi) run this now please"
    )


def test_save_text_as_cancelled_skips_generated_but_keeps_file_refs() -> None:
    from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import (
        PromptBarMountMixin,
    )

    recorded: list[dict[str, Any]] = []
    refs_recorded: list[Any] = []

    class CancelHost(PromptBarMountMixin):
        pass

    host = CancelHost()
    host._prompt_context = None  # type: ignore[attr-defined]
    host._prompt_session = None  # type: ignore[attr-defined]
    begin_prompt_session(host, _context(), prompt_origin="generated")

    import sase.history.prompt as prompt_mod
    import sase.history.file_references as refs_mod

    orig_add = prompt_mod.add_or_update_prompt
    orig_refs = refs_mod.record_file_references
    orig_extract = refs_mod.extract_recordable_file_refs
    prompt_mod.add_or_update_prompt = lambda *a, **k: recorded.append({"a": a, "k": k})  # type: ignore[assignment]
    refs_mod.record_file_references = lambda refs: refs_recorded.append(refs)  # type: ignore[assignment]
    refs_mod.extract_recordable_file_refs = lambda text: ["some/file.py"]  # type: ignore[assignment]
    try:
        stored = host._save_text_as_cancelled("please review some/file.py now please")
    finally:
        prompt_mod.add_or_update_prompt = orig_add  # type: ignore[assignment]
        refs_mod.record_file_references = orig_refs  # type: ignore[assignment]
        refs_mod.extract_recordable_file_refs = orig_extract  # type: ignore[assignment]
    assert recorded == []
    assert refs_recorded == [["some/file.py"]]
    assert stored == ""


def test_save_text_as_cancelled_records_typed() -> None:
    from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import (
        PromptBarMountMixin,
    )

    recorded: list[dict[str, Any]] = []

    class CancelHost(PromptBarMountMixin):
        pass

    host = CancelHost()
    host._prompt_context = None  # type: ignore[attr-defined]
    host._prompt_session = None  # type: ignore[attr-defined]
    begin_prompt_session(host, _context(), prompt_origin="typed")

    import sase.history.prompt as prompt_mod
    import sase.history.file_references as refs_mod

    orig_add = prompt_mod.add_or_update_prompt
    orig_extract = refs_mod.extract_recordable_file_refs
    prompt_mod.add_or_update_prompt = lambda *a, **k: recorded.append({"a": a, "k": k})  # type: ignore[assignment]
    refs_mod.extract_recordable_file_refs = lambda text: []  # type: ignore[assignment]
    try:
        stored = host._save_text_as_cancelled("a typed prompt worth keeping here")
    finally:
        prompt_mod.add_or_update_prompt = orig_add  # type: ignore[assignment]
        refs_mod.extract_recordable_file_refs = orig_extract  # type: ignore[assignment]
    assert len(recorded) == 1
    assert stored != ""


def test_retry_edit_marks_member_generated_and_standalone_typed() -> None:
    from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin

    captured: list[dict[str, Any]] = []

    class RetryHost(EntryRelaunchMixin):
        def __init__(self, agent: SimpleNamespace) -> None:
            self._agent = agent
            self.notifications: list[tuple[str, str]] = []

        def _get_selected_agent(self) -> Any:
            return self._agent

        def notify(self, message: str, **kwargs: Any) -> None:
            self.notifications.append((message, str(kwargs.get("severity"))))

        def _rewrite_retry_prompt_name(
            self, raw_prompt: str, retry_name: str, **kwargs: Any
        ) -> str:
            return raw_prompt

        def _edit_and_relaunch_agent(self, *args: Any, **kwargs: Any) -> None:
            captured.append({"args": args, "kwargs": kwargs})

    member = _agent(agent_clan="clan-1")
    member.get_raw_xprompt_content = lambda: "member prompt text here"  # type: ignore[attr-defined]
    member.agent_name = None
    member.project_file = "/tmp/home/home.sase"
    member.cl_name = "home"
    member.is_project_agent = False
    RetryHost(member)._retry_edit_agent()
    assert captured[-1]["kwargs"].get("prompt_origin") == "generated"

    captured.clear()
    standalone = _agent()
    standalone.get_raw_xprompt_content = lambda: "standalone prompt here"  # type: ignore[attr-defined]
    standalone.agent_name = None
    standalone.project_file = "/tmp/home/home.sase"
    standalone.cl_name = "home"
    standalone.is_project_agent = False
    RetryHost(standalone)._retry_edit_agent()
    assert captured[-1]["kwargs"].get("prompt_origin", "typed") == "typed"


def test_flush_stash_uses_history_prompt_and_origin() -> None:
    import asyncio

    from sase.ace.tui.actions.agent_workflow import _pending_launch as pending_mod

    calls: list[dict[str, Any]] = []

    def fake_record(text: str, **kwargs: Any) -> None:
        calls.append({"text": text, **kwargs})

    # flush imports record_failed_launch_prompt inside the function from
    # sase.history.prompt, so patch there.
    import sase.history.prompt as prompt_mod

    orig_prompt_record = prompt_mod.record_failed_launch_prompt
    prompt_mod.record_failed_launch_prompt = fake_record  # type: ignore[assignment]
    app = SimpleNamespace()
    launch = begin_pending_launch(
        app,
        prompt="expanded member prompt",
        context=_context(),
        keep_bar=False,
        extra_payload=None,
        bulk_patches=(),
        relaunch_operation=None,
        stage=PendingLaunchStage.SUBMITTING,
        prompt_origin="generated",
    )
    launch.history_prompt = "original swarm invocation text here"
    try:
        asyncio.run(pending_mod.flush_pending_launch_stashes(app))
    finally:
        prompt_mod.record_failed_launch_prompt = orig_prompt_record  # type: ignore[assignment]
    assert len(calls) == 1
    assert calls[0]["text"] == "original swarm invocation text here"
    assert calls[0]["origin"] == "generated"
