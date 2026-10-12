"""Archive-reader: hydration, identity, titled cards, and live-path guards."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_column import archive_container_members
from sase.ace.tui.actions.agents._archive_reader import (
    _reader_runtime,
    hydrated_archive_agent_for,
)
from sase.ace.tui.actions.agents._archive_view import (
    archive_read_only_context,
    close_agents_archive_view,
    get_agents_tab_selection,
    open_agents_archive_view,
    route_archive_key,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_archive_reader import (
    ARCHIVE_LOADING_TITLE,
    ARCHIVE_MISSING_CONTEXT,
    ARCHIVE_MISSING_FILES,
    ARCHIVE_MISSING_REPLY,
    ARCHIVE_UNREADABLE_TITLE,
    archive_container_summary_text,
    archive_identity_header_from_light_row,
    mark_agent_archive_read_only,
    probe_retained_archive_content,
    resolve_archive_bundle_path,
    titled_archive_card,
)
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_INBOX,
    ARCHIVE_IDENTITY_ACCENT,
    ARCHIVE_IDENTITY_KIND,
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_CONTAINER,
    INTENT_DOWN,
    INTENT_EXPAND,
    INTENT_UP,
    agent_is_archive_read_only,
)
from sase.ace.tui.widgets._agent_detail_files import (
    _dispatch_file_view,
    load_deck_file_view,
)
from sase.ace.tui.widgets.decks.availability import probe_files_deck, probe_final_deck
from sase.ace.tui.widgets.file_panel._file_list import (
    _is_terminal_agent,
    desired_file_pages,
)
from sase.ace.tui.widgets.prompt_panel._identity_header import identity_kind_for_agent
from sase.ace.tui.widgets.prompt_panel._live_reply_follow import is_live_reply_agent
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import ColumnHarness, light_row
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _tree_fingerprint(path: Path) -> tuple[tuple[str, int, int], ...]:
    if not path.exists():
        return ()
    if path.is_file():
        fp = _fingerprint(path)
        return ((path.name, *fp),) if fp else ()
    rows: list[tuple[str, int, int]] = []
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        fp = _fingerprint(child)
        if fp is None:
            continue
        rows.append((str(child.relative_to(path)), fp[0], fp[1]))
    return tuple(rows)


def _write_bundle(path: Path, agent: Agent) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agent.to_bundle_dict()), encoding="utf-8")
    return path


class _FakeDetail:
    def __init__(self) -> None:
        self.empty = 0
        self.causes: list[tuple[str, str]] = []
        self.identities: list[Any] = []
        self.displays: list[Agent] = []
        self.updates: list[Any] = []
        self.record_subjects: list[Any] = []

    def show_empty(self) -> None:
        self.empty += 1

    def show_tab_empty_state(self, title: str, detail: str = "") -> None:
        self.causes.append((title, detail))

    def _on_identity_header(self, header: Any) -> None:
        self.identities.append(header)

    def update_display(self, agent: Agent, **kwargs: Any) -> None:
        self.displays.append(agent)

    def update(self, content: Any = "", **kwargs: Any) -> None:
        self.updates.append(content)

    def show_record_subject(self, subject: Any) -> None:
        self.record_subjects.append(subject)


class _FakeFilePanel:
    def __init__(self) -> None:
        self.live_updates = 0
        self.file_lists: list[list[str]] = []
        self.empty = 0
        self.bodies: list[Any] = []

    def update_display(self, agent: Agent, stale_threshold_seconds: int = 10) -> None:
        self.live_updates += 1

    def set_file_list(self, files: list[str], start_index: int = 0) -> None:
        self.file_lists.append(list(files))

    def show_empty(self) -> None:
        self.empty += 1

    def _update_body(self, body: Any, **kwargs: Any) -> None:
        self.bodies.append(body)


async def _opened_with_detail(
    rows: list[dict[str, Any]],
    tmp_path: Path,
) -> tuple[ColumnHarness, _FakeDetail]:
    harness = ColumnHarness(rows)
    harness.owner._archive_corpus_root = tmp_path
    detail = _FakeDetail()
    harness.owner._archive_detail_widget = detail
    unread = {("RUNNING", "live", None)}
    harness.owner._unread_completed_agent_ids = unread
    harness.owner._unread_snapshot = set(unread)
    harness.note_inbox_applied()
    open_agents_archive_view(harness.owner)
    await harness.settle()
    return harness, detail


def test_identity_kind_and_live_reply_guard_for_archive_read_only() -> None:
    running = make_agent(status="RUNNING")
    mark_agent_archive_read_only(running)
    assert agent_is_archive_read_only(running)
    assert identity_kind_for_agent(running) == (
        ARCHIVE_IDENTITY_KIND,
        ARCHIVE_IDENTITY_ACCENT,
    )
    assert is_live_reply_agent(running) is False
    live = make_agent(status="RUNNING")
    assert is_live_reply_agent(live) is True


def test_archive_read_only_is_not_serialized_into_bundles() -> None:
    agent = make_agent(status="RUNNING")
    mark_agent_archive_read_only(agent)
    payload = agent.to_bundle_dict()
    assert "_archive_read_only" not in payload
    loaded = Agent.from_bundle_dict(payload)
    assert loaded._archive_read_only is False
    assert loaded.status == "RUNNING"


def test_files_dispatch_skips_active_and_workspace_fallback() -> None:
    agent = make_agent(status="RUNNING", workspace_num=3)
    mark_agent_archive_read_only(agent)
    panel = _FakeFilePanel()
    assert _dispatch_file_view(panel, agent) is False
    assert panel.live_updates == 0
    agent.extra_files = ["/tmp/retained.diff"]
    panel = _FakeFilePanel()
    assert _dispatch_file_view(panel, agent) is True
    assert panel.live_updates == 0
    assert panel.file_lists == [["/tmp/retained.diff"]]
    assert _is_terminal_agent(agent) is True
    pages, _default = desired_file_pages(agent)
    assert "__live_diff__" not in pages and "▣" not in "".join(pages)
    probe = probe_files_deck(agent, attempt_number=None)
    assert probe.has_content is True
    missing = make_agent(status="RUNNING", workspace_num=9)
    mark_agent_archive_read_only(missing)
    empty = probe_files_deck(missing, attempt_number=None)
    assert empty.has_content is False
    final = probe_final_deck(missing, attempt_number=None)
    assert final.has_content is False
    titled = _FakeFilePanel()
    assert load_deck_file_view(titled, missing, attempt_number=None) is False
    assert titled.bodies
    assert ARCHIVE_MISSING_FILES in titled.bodies[0].plain


def test_light_row_identity_and_placeholders() -> None:
    row = light_row("run-1", status="RUNNING", outcome="interrupted")
    header = archive_identity_header_from_light_row(row, loading=True)
    assert header.kind_label == ARCHIVE_IDENTITY_KIND
    assert ARCHIVE_LOADING_TITLE in header.expanded.plain
    assert "Ended:" in header.expanded.plain or "ended" in header.expanded.plain.lower()
    unreadable = archive_identity_header_from_light_row(row, unreadable=True)
    assert ARCHIVE_UNREADABLE_TITLE in unreadable.expanded.plain
    dismissed = archive_identity_header_from_light_row(
        light_row("run-2", time_basis="dismissed")
    )
    assert "Dismissed:" in dismissed.expanded.plain
    assert "Started:" not in dismissed.expanded.plain
    card = titled_archive_card(ARCHIVE_MISSING_CONTEXT)
    assert ARCHIVE_MISSING_CONTEXT in card.plain
    members = (light_row("m1", name="one"), light_row("m2", name="two"))
    summary = archive_container_summary_text(row, members)
    assert "2 matching member" in summary.plain
    assert "one" in summary.plain and "two" in summary.plain


def test_resolve_bundle_path_prefers_explicit_then_root(tmp_path: Path) -> None:
    explicit = tmp_path / "custom.json"
    explicit.write_text("{}", encoding="utf-8")
    row = light_row("abc", bundle_path=str(explicit))
    assert resolve_archive_bundle_path(row, tmp_path) == explicit
    nested = tmp_path / "bundles" / "xyz.json"
    nested.parent.mkdir()
    nested.write_text("{}", encoding="utf-8")
    row2 = light_row("xyz")
    assert resolve_archive_bundle_path(row2, tmp_path) == nested


def test_member_jump_does_not_revive_while_archive_owns_panel() -> None:
    from sase.ace.tui.actions.navigation._member_jump import MemberJumpNavigationMixin

    revived: list[Any] = []
    dismissed = make_agent(cl_name="gone")

    class _Owner(MemberJumpNavigationMixin):
        def _reveal_agent_row(self, *args: Any, **kwargs: Any) -> None:
            return None

        def _notify_member_jump(self, message: str) -> None:
            return None

        def _do_revive_agent(self, agent: Agent) -> None:
            revived.append(agent)

        def _active_dismissed_agent_objects(self) -> list[Agent]:
            return [dismissed]

    owner = _Owner()
    owner._agents_archive_view = SimpleNamespace(active_view="archive")
    target = SimpleNamespace(role="dismissed", member_identity=dismissed.identity)
    with override_flags(agents_archive_view=True):
        owner._activate_member_jump_target(target)
    assert revived == []
    with override_flags(agents_archive_view=False):
        owner._activate_member_jump_target(target)
    assert revived == [dismissed]


async def test_hydration_paints_identity_then_agent_and_never_writes(
    tmp_path: Path,
) -> None:
    prompt = "P" * 5000
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "raw_prompt.md").write_text(prompt, encoding="utf-8")
    agent = make_agent(status="RUNNING", cl_name="archived")
    agent.artifacts_dir = str(artifacts)
    agent.agent_name = "archived-run"
    bundle = tmp_path / "bundles" / "t00.json"
    _write_bundle(bundle, agent)
    index = tmp_path / "index.sqlite"
    index.write_bytes(b"idx")
    before_bundle = _fingerprint(bundle)
    before_index = _fingerprint(index)
    before_arts = _tree_fingerprint(artifacts)
    rows = [light_row("t00", status="RUNNING", bundle_path=str(bundle))]
    with override_flags(agents_archive_view=True):
        harness, detail = await _opened_with_detail(rows, tmp_path)
        owner = harness.owner
        observer = SimpleNamespace(subscribe_calls=[])
        observer.subscribe_tail = lambda proc_id: observer.subscribe_calls.append(
            proc_id
        )
        owner._proc_observer = observer
        unread_before = set(owner._unread_completed_agent_ids)
        agents_before = owner._agents
        assert ARCHIVE_LOADING_TITLE in (detail.causes[0][0] if detail.causes else "")
        assert detail.identities
        assert detail.identities[0].kind_label == ARCHIVE_IDENTITY_KIND
        owner._agent_detail_debouncer.fire()
        await harness.settle()
        selection = get_agents_tab_selection(owner)
        assert selection.row_kind == ARCHIVE_ROW_AGENT
        assert selection.agent is not None
        assert agent_is_archive_read_only(selection.agent)
        assert selection.agent.status == "RUNNING"
        assert selection.agent not in list(owner._agents)
        assert owner._agents is agents_before
        assert is_live_reply_agent(selection.agent) is False
        context = archive_read_only_context(owner)
        assert context is not None
        assert context.hydrated_agent is selection.agent
        assert context.light_row is not None
        assert owner._unread_completed_agent_ids == unread_before
        content = selection.agent.get_raw_prompt_content()
        assert content == prompt
        assert len(content) == 5000
        retained, _missing = probe_retained_archive_content(selection.agent)
        assert "context" in retained
        assert observer.subscribe_calls == []
        assert _fingerprint(bundle) == before_bundle
        assert _fingerprint(index) == before_index
        assert _tree_fingerprint(artifacts) == before_arts
        assert hydrated_archive_agent_for(owner, "u.m@t00") is selection.agent


async def test_unreadable_bundle_paints_record_placeholder(tmp_path: Path) -> None:
    bundle = tmp_path / "bundles" / "t00.json"
    bundle.parent.mkdir()
    bundle.write_text("{not json", encoding="utf-8")
    rows = [light_row("t00", bundle_path=str(bundle))]
    with override_flags(agents_archive_view=True):
        harness, detail = await _opened_with_detail(rows, tmp_path)
        harness.owner._agent_detail_debouncer.fire()
        await harness.settle()
        runtime = _reader_runtime(harness.owner)
        assert runtime.unreadable is True
        assert runtime.hydrated_agent is None
        titles = [title for title, _ in detail.causes]
        assert ARCHIVE_UNREADABLE_TITLE in titles
        assert detail.displays == []
        assert len(detail.record_subjects) == 1
        subject = detail.record_subjects[0]
        assert subject.kind == "light_row"
        assert subject.location == "archive"
        assert subject.agent_name == "agent-t00"
        assert subject.archive is not None
        assert subject.archive.outcome == "done"
        context = archive_read_only_context(harness.owner)
        assert context is not None and context.unreadable is True


async def test_stale_hydration_after_rapid_jk_and_view_switch(
    tmp_path: Path,
) -> None:
    first = make_agent(status="DONE", cl_name="first")
    second = make_agent(status="DONE", cl_name="second")
    b1 = tmp_path / "bundles" / "t00.json"
    b2 = tmp_path / "bundles" / "t01.json"
    _write_bundle(b1, first)
    _write_bundle(b2, second)
    rows = [
        light_row("t00", hour=23, bundle_path=str(b1)),
        light_row("t01", hour=22, bundle_path=str(b2)),
    ]
    with override_flags(agents_archive_view=True):
        harness, detail = await _opened_with_detail(rows, tmp_path)
        owner = harness.owner
        owner._agent_detail_debouncer.fire()
        route_archive_key(owner, INTENT_DOWN)
        owner._agent_detail_debouncer.fire()
        await harness.settle()
        selection = get_agents_tab_selection(owner)
        assert selection.archive_key == "u.m@t01"
        assert selection.agent is not None
        assert selection.agent.cl_name == "second"
        route_archive_key(owner, INTENT_UP)
        close_agents_archive_view(owner)
        if owner._agent_detail_debouncer.callbacks:
            owner._agent_detail_debouncer.fire()
        await harness.settle()
        assert get_agents_tab_selection(owner).view == AGENTS_VIEW_INBOX
        assert hydrated_archive_agent_for(owner, "u.m@t01") is None
        assert hydrated_archive_agent_for(owner, "u.m@t00") is None


async def test_container_summary_uses_light_rows_only(tmp_path: Path) -> None:
    clan = "clan:swarm:1"
    rows = [
        light_row("m1", hour=22, name="swarm.one", container_key=clan),
        light_row("m2", hour=21, name="swarm.two", container_key=clan),
        light_row("m3", hour=20, name="swarm.three", container_key=clan),
    ]
    with override_flags(agents_archive_view=True):
        harness, detail = await _opened_with_detail(rows, tmp_path)
        selection = get_agents_tab_selection(harness.owner)
        assert selection.row_kind == ARCHIVE_ROW_CONTAINER
        assert selection.agent is None
        titles = [title for title, _ in detail.causes]
        assert "Container summary" in titles
        assert detail.displays == []
        assert detail.record_subjects
        subject = detail.record_subjects[-1]
        assert subject.kind == "container"
        assert subject.location == "archive"
        assert subject.archive is not None
        assert subject.archive.member_count == 3
        route_archive_key(harness.owner, INTENT_EXPAND)
        await harness.settle()
        members = archive_container_members(harness.owner, clan)
        harness.owner._agent_detail_debouncer.fire()
        await harness.settle()
        assert hydrated_archive_agent_for(harness.owner, selection.archive_key) is None
        assert len(members) == 3
        body = archive_container_summary_text(selection.light_row, members)
        assert "swarm.one" in body.plain
        expanded = detail.record_subjects[-1]
        assert expanded.kind == "container"
        assert "swarm.one" in expanded.member_names
        assert "swarm.two" in expanded.member_names
        assert "swarm.three" in expanded.member_names


async def test_partial_reply_is_retained_for_archived_running(tmp_path: Path) -> None:
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    (artifacts / "live_reply.md").write_text("partial hello", encoding="utf-8")
    agent = make_agent(status="RUNNING", cl_name="partial")
    agent.artifacts_dir = str(artifacts)
    bundle = tmp_path / "bundles" / "t00.json"
    _write_bundle(bundle, agent)
    rows = [light_row("t00", status="RUNNING", bundle_path=str(bundle))]
    with override_flags(agents_archive_view=True):
        harness, _detail = await _opened_with_detail(rows, tmp_path)
        harness.owner._agent_detail_debouncer.fire()
        await harness.settle()
        hydrated = get_agents_tab_selection(harness.owner).agent
        assert hydrated is not None
        assert hydrated.get_live_reply_content() == "partial hello"
        assert is_live_reply_agent(hydrated) is False
        retained, missing = probe_retained_archive_content(hydrated)
        assert "reply" in retained
        assert ARCHIVE_MISSING_REPLY not in retained


def test_titled_missing_copy() -> None:
    assert "retention" in ARCHIVE_MISSING_REPLY
    assert "Record only" in ARCHIVE_UNREADABLE_TITLE
