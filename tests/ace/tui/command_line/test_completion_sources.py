"""Completion-source tests for the ``:`` Command Line (sase-17x.13.10.4).

Covers fresh caches (the provider disk cache is bypassed after a block
finishes and stale in-flight fetches are dropped), ``cd +<label>`` and
``+home`` resolution, project slots merging the provider behind in-memory
rows, ``cd -`` and dotfile candidates, the key-receipt perf probe, and the
source test gaps: the marked-agent row on a mounted screen, path scans in the
debounced worker, ``cd`` directories, and provider fetches for empty proc and
project state.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch as mock_patch

import pytest

from sase.ace.tui.command_line.builtins import resolve_cd
from sase.ace.tui.command_line.cd_completion import (
    cd_completion_context,
    complete_cd,
)
from sase.ace.tui.command_line.sources import (
    ProviderCache,
    _in_memory_candidates,
    collect_dynamic_candidates,
    needs_provider_fetch,
    path_candidates,
    path_completion_request,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.history import command_line as history_store


@pytest.fixture
def history_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the history store to a temp file."""
    path = tmp_path / "command_line_history.json"
    monkeypatch.setattr(history_store, "_history_file_override", path)
    return path


@pytest.fixture(scope="module")
def grammar_handle() -> Any:
    """Return an in-process ``CommandLineGrammar`` (no spec subprocess)."""
    try:
        from sase.completion.build import build_spec
        from sase.completion.command_line_grammar import CommandLineGrammar

        return CommandLineGrammar.from_spec_json(json.dumps(build_spec().to_json()))
    except AttributeError:
        pytest.skip("installed sase_core_rs wheel predates CommandLineGrammar")


# -- provider cache: invalidation, generations, the disk cache -----------------


def test_invalidate_retires_in_flight_fetches_and_distrusts_the_disk_cache() -> None:
    """A finished command voids in-flight results and the providers' disk cache."""
    cache = ProviderCache(ttl_seconds=60.0)
    assert cache.bypass_disk_cache("pending_plan", None) is False

    in_flight = cache.next_generation()
    cache.invalidate()
    assert cache.commit(in_flight, "pending_plan", None, [{"value": "stale"}]) is False
    assert cache.cached("pending_plan", None) is None
    assert cache.bypass_disk_cache("pending_plan", None) is True
    assert cache.bypass_disk_cache("bead", None) is True

    refetch = cache.next_generation()
    assert cache.commit(refetch, "pending_plan", None, [{"value": "fresh"}]) is True
    # One fresh fetch per slot is enough: the disk file was rewritten by it.
    assert cache.bypass_disk_cache("pending_plan", None) is False
    assert cache.bypass_disk_cache("bead", None) is True
    cache.invalidate()
    assert cache.bypass_disk_cache("pending_plan", None) is True


@asynccontextmanager
async def _panel(grammar: Any) -> AsyncGenerator[tuple[Any, Any]]:
    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.screen import CommandLineScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app._command_line_grammar = grammar
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            screen.transcript.stop_tail_task()
            await page.pause()
            yield page, screen


async def _type(page: Any, screen: Any, line: str) -> Any:
    from sase.ace.tui.command_line.input import CommandLineInput

    widget = screen.query_one(CommandLineInput)
    widget.set_line(line)
    await page.pause()
    return widget


async def _await_provider_task(screen: Any) -> None:
    task = screen._provider_task
    assert task is not None
    await asyncio.wait_for(task, timeout=5)


def _project(screen: Any) -> str | None:
    return screen._working_context.project if screen._working_context else None


def _shown(screen: Any) -> list[str]:
    """The popup rows' display text, in order."""
    return [
        str(item.get("display") or item.get("insert_text") or "").strip()
        for item in screen._popup_state.items
    ]


def _finish_command(page: Any, line: str) -> None:
    """Deliver an exit completion for a running block of *line*."""
    from sase.ace.tui.command_line.exits import deliver_command_line_exit
    from sase.ace.tui.command_line.session import (
        CommandLineBlock,
        command_line_session_for,
    )

    command_line_session_for(page.app).blocks.append(
        CommandLineBlock(
            block_id="b-finish", line=line, status="running", proc_id="proc-finish"
        )
    )
    completion = SimpleNamespace(proc_id="proc-finish", exit_code=0, status="done")
    assert deliver_command_line_exit(page.app, completion) is True


def _stub_provider(monkeypatch: pytest.MonkeyPatch, fetch: Any) -> list[bool]:
    """Route ``candidates_for`` to *fetch*, recording each ``use_disk_cache``."""
    import sase.completion.candidates.providers as providers

    uses_disk_cache: list[bool] = []

    def _candidates_for(
        kind: str,
        prefix: str,
        *,
        project: str | None,
        limit: int,
        use_disk_cache: bool = True,
    ) -> Any:
        uses_disk_cache.append(use_disk_cache)
        return fetch(kind)

    monkeypatch.setattr(providers, "candidates_for", _candidates_for)
    return uses_disk_cache


async def test_finishing_a_command_refetches_past_the_disk_cache(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``plan approve X`` then ``plan approve <Tab>`` must not offer ``X`` again."""
    from sase.completion.candidates.protocol import Candidate

    pending = [Candidate("alpha-plan", "a plan")]
    uses_disk_cache = _stub_provider(monkeypatch, lambda kind: list(pending))
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "plan approve ")
        await _await_provider_task(screen)
        assert uses_disk_cache == [True]
        assert "alpha-plan" in _shown(screen)

        pending.clear()
        _finish_command(page, "plan approve alpha-plan")
        await _await_provider_task(screen)
        assert uses_disk_cache == [True, False]
        assert "alpha-plan" not in _shown(screen)
        # The fresh fetch rewrote the disk file, so later fetches trust it again.
        assert not screen._provider_cache.bypass_disk_cache(
            "pending_plan", _project(screen)
        )


async def test_finishing_a_command_drops_the_stale_in_flight_fetch(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch started before the finish cannot put its rows back in the cache."""
    from sase.completion.candidates.protocol import Candidate

    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def _fetch(kind: str) -> list[Candidate]:
        calls.append(kind)
        if len(calls) == 1:
            started.set()
            release.wait(timeout=5)
            return [Candidate("stale-plan", "")]
        return [Candidate("fresh-plan", "")]

    uses_disk_cache = _stub_provider(monkeypatch, _fetch)
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "plan approve ")
        first = screen._provider_task
        assert first is not None
        await page.wait_for(lambda _state: started.is_set())

        _finish_command(page, "plan approve stale-plan")
        release.set()
        await _await_provider_task(screen)
        await asyncio.gather(first, return_exceptions=True)

        cached = screen._provider_cache.cached("pending_plan", _project(screen))
        assert [row["value"] for row in cached or []] == ["fresh-plan"]
        assert uses_disk_cache == [True, False]


async def test_finishing_a_command_under_an_active_menu_refetches_on_next_render(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The menu keeps its rows, but the very next render fetches fresh ones."""
    from sase.completion.candidates.protocol import Candidate

    uses_disk_cache = _stub_provider(
        monkeypatch,
        lambda kind: [Candidate("alpha-plan", ""), Candidate("beta-plan", "")],
    )
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "plan approve ")
        await _await_provider_task(screen)
        await page.press("tab")
        assert screen._popup_state.menu_active

        _finish_command(page, "plan approve gamma-plan")
        assert screen._popup_state.menu_active
        assert screen._provider_task is None  # nothing repainted under the menu
        assert uses_disk_cache == [True]

        screen._refresh_completion()  # the next render
        await _await_provider_task(screen)
        assert uses_disk_cache == [True, False]


# -- ``cd`` resolution and candidates ------------------------------------------


def _record(
    name: str,
    *,
    display_name: str | None = None,
    state: str = "enabled",
    workspace_dir: str | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=name,
        project_dir=f"/projects/{name}",
        project_file=f"/projects/{name}/{name}.sase",
        archive_file=None,
        workspace_dir=workspace_dir,
        state=state,
        state_explicit=True,
        system_managed=name == "home",
        active_claim_count=0,
        launchable=True,
        display_name=display_name,
    )


def _stub_project_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, records: list[ProjectRecordWire]
) -> list[bool]:
    """Serve *records* as the project store; return each ``include_home`` seen."""
    import sase.core.paths as core_paths
    import sase.core.project_lifecycle_facade as facade

    include_home_seen: list[bool] = []

    def _list_records(
        root: object, states: object, *, include_home: bool = False, **kwargs: object
    ) -> list[ProjectRecordWire]:
        include_home_seen.append(include_home)
        return list(records)

    monkeypatch.setattr(core_paths, "sase_projects_dir", lambda: tmp_path)
    monkeypatch.setattr(facade, "list_project_records", _list_records)
    return include_home_seen


def test_cd_plus_resolves_the_labels_completion_offers_and_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``cd +sase`` and ``cd +home`` reach the checkouts completion promised."""
    include_home_seen = _stub_project_records(
        monkeypatch,
        tmp_path,
        [
            _record(
                "gh_sase-org__sase",
                display_name="sase",
                workspace_dir="/ws/github/sase",
            ),
            _record("home", workspace_dir="/ws/git/home"),
            _record("gh_org__old", display_name="old", state="disabled"),
        ],
    )

    by_label = resolve_cd("+sase", cwd="/")
    assert (by_label.pinned, by_label.outcome.exit_code) == ("/ws/github/sase", 0)
    assert by_label.changes_pin is True
    assert resolve_cd("+gh_sase-org__sase", cwd="/").pinned == "/ws/github/sase"
    assert resolve_cd("+home", cwd="/").pinned == "/ws/git/home"
    assert include_home_seen and all(include_home_seen)

    disabled = resolve_cd("+old", cwd="/")
    assert (disabled.pinned, disabled.outcome.exit_code) == (None, 2)
    missing = resolve_cd("+nope", cwd="/")
    assert missing.outcome.text == "error: no such project: nope"
    assert missing.changes_pin is False


def test_cd_plus_prefers_the_canonical_key_over_an_equal_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A label that collides with another project's key never steals the key."""
    _stub_project_records(
        monkeypatch,
        tmp_path,
        [
            _record("alias-holder", display_name="core", workspace_dir="/ws/holder"),
            _record("core", workspace_dir="/ws/core"),
        ],
    )

    assert resolve_cd("+core", cwd="/").pinned == "/ws/core"


def _dir_row(value: str) -> dict[str, Any]:
    return {"value": value, "badge": "dir", "source": "path"}


def test_cd_offers_unpin_in_the_empty_menu_after_the_directories() -> None:
    """``cd `` lists directories, then ``-``; ``-`` alone is only the unpin row."""
    context = cd_completion_context("cd ", len("cd "))
    assert context is not None
    empty = complete_cd(
        "cd ", len("cd "), context, [_dir_row("src/"), _dir_row("docs/")]
    )
    assert [item["insert_text"] for item in empty["items"]] == ["src/", "docs/", "-"]
    assert empty["kind"] == "dir"

    typed = complete_cd("cd s", len("cd s"), context, [_dir_row("src/")])
    assert [item["insert_text"] for item in typed["items"]] == ["src/"]

    dash_context = cd_completion_context("cd -", len("cd -"))
    assert dash_context is not None
    dash = complete_cd("cd -", len("cd -"), dash_context, [_dir_row("-notes/")])
    assert [item["insert_text"] for item in dash["items"]] == ["-notes/", "-"]

    project_context = cd_completion_context("cd +", len("cd +"))
    assert project_context is not None
    projects = complete_cd(
        "cd +",
        len("cd +"),
        project_context,
        [{"value": "home", "badge": "project", "source": "provider"}],
    )
    assert [item["insert_text"] for item in projects["items"]] == ["+home"]


async def test_cd_completes_directories_projects_and_unpin_on_the_screen(
    grammar_handle: Any,
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``cd`` slots list pinned-cwd directories, ``+project`` rows and ``-``."""
    from sase.completion.candidates.protocol import Candidate

    (tmp_path / "alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "notes.txt").write_text("not a directory")
    _stub_provider(
        monkeypatch,
        lambda kind: [Candidate("zeta", "enabled"), Candidate("home", "enabled")],
    )
    async with _panel(grammar_handle) as (page, screen):
        _pin_cwd(page, screen, tmp_path)
        await _type(page, screen, "cd ")
        await _await_provider_task(screen)
        assert _shown(screen) == ["alpha/", "-"]

        await _type(page, screen, "cd .")
        await _await_provider_task(screen)
        assert _shown(screen) == [".hidden/"]

        await _type(page, screen, "cd +")
        await _await_provider_task(screen)
        assert {"+zeta", "+home"} <= set(_shown(screen))


def _pin_cwd(page: Any, screen: Any, cwd: Path) -> None:
    from sase.ace.tui.command_line.context import CommandLineContext
    from sase.ace.tui.command_line.session import command_line_session_for

    command_line_session_for(page.app).cwd_pin = str(cwd)
    screen._working_context = CommandLineContext(
        cwd=str(cwd), project=None, pinned=True
    )


# -- path rows: dotfiles, the worker boundary, the ``--cwd`` slot ------------------


def test_path_scan_lists_dotfiles_only_once_the_typed_name_starts_with_a_dot(
    tmp_path: Path,
) -> None:
    """Dotfiles stay hidden until asked for, and cache under their own key."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text("secret")
    (tmp_path / "src").mkdir()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".cache").mkdir()

    plain = path_completion_request("", str(tmp_path))
    dotted = path_completion_request(".", str(tmp_path))
    assert [row["value"] for row in path_candidates(plain, directories_only=False)] == [
        "src/",
        "sub/",
    ]
    assert [
        row["value"] for row in path_candidates(dotted, directories_only=False)
    ] == [
        ".git/",
        "src/",
        "sub/",
        ".env",
    ]
    assert plain.source_key != dotted.source_key

    nested_plain = path_completion_request("sub/", str(tmp_path))
    nested_dotted = path_completion_request("sub/.", str(tmp_path))
    assert path_candidates(nested_plain, directories_only=False) == []
    assert [
        row["value"] for row in path_candidates(nested_dotted, directories_only=False)
    ] == ["sub/.cache/"]


async def test_path_scan_runs_in_the_debounced_worker_not_on_the_keystroke(
    grammar_handle: Any,
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The directory scan happens in a worker thread, after the debounce."""
    import sase.ace.tui.command_line.screen_completion as screen_module

    (tmp_path / "alpha").mkdir()
    (tmp_path / "notes.txt").write_text("file")
    scan_threads: list[int] = []
    real_scan = screen_module.path_candidates

    def _spy(request: Any, **kwargs: Any) -> list[dict[str, Any]]:
        scan_threads.append(threading.get_ident())
        return real_scan(request, **kwargs)

    monkeypatch.setattr(screen_module, "path_candidates", _spy)
    async with _panel(grammar_handle) as (page, screen):
        _pin_cwd(page, screen, tmp_path)
        await _type(page, screen, "proc run --cwd ")
        await _await_provider_task(screen)
        scan_threads.clear()

        screen._provider_cache.invalidate()
        screen._refresh_completion()  # the keystroke path: synchronous, on the loop
        assert scan_threads == []
        await _await_provider_task(screen)
        assert len(scan_threads) == 1
        assert scan_threads[0] != threading.get_ident()


async def test_path_rows_reach_the_popup_for_a_cwd_slot_through_complete(
    grammar_handle: Any, history_file: Path, tmp_path: Path
) -> None:
    """``proc run --cwd `` completes directories, not files, in the pinned cwd."""
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "notes.txt").write_text("file")
    async with _panel(grammar_handle) as (page, screen):
        _pin_cwd(page, screen, tmp_path)
        await _type(page, screen, "proc run --cwd ")
        await _await_provider_task(screen)
        assert _shown(screen) == ["alpha/", "beta/"]

        await _type(page, screen, "proc run --cwd b")
        await _await_provider_task(screen)
        assert _shown(screen) == ["beta/"]


# -- provider fetches for entity slots ---------------------------------------------


def test_project_slots_always_fetch_but_proc_and_agent_slots_only_when_empty() -> None:
    """Partial in-memory readers merge the provider; complete ones stand alone."""
    app = SimpleNamespace(
        _projects=["alpha-local"],
        _agents=[SimpleNamespace(agent_name="athena.1", status="running")],
        _proc_projection=SimpleNamespace(rows=[SimpleNamespace(proc_id="proc-1")]),
    )
    assert needs_provider_fetch("project", app) is True
    assert needs_provider_fetch("project", SimpleNamespace()) is True
    assert needs_provider_fetch("proc", app) is False
    assert needs_provider_fetch("proc", SimpleNamespace()) is True
    assert needs_provider_fetch("agent", app) is False
    assert needs_provider_fetch("agent", SimpleNamespace()) is True


def test_provider_rows_merge_behind_in_memory_rows_without_duplicates() -> None:
    """In-memory project rows come first; the provider adds only what is new."""
    cache = ProviderCache(ttl_seconds=60.0)
    cache.commit(
        cache.next_generation(),
        "project",
        None,
        [
            {"value": "alpha-local", "source": "provider"},
            {"value": "zeta-remote", "source": "provider"},
            {"value": "home", "source": "provider"},
        ],
    )
    app = SimpleNamespace(_projects=["alpha-local"])
    assert [row["value"] for row in _in_memory_rows(app, "project")] == ["alpha-local"]

    merged = collect_dynamic_candidates(app, "project", None, cache)
    assert [row["value"] for row in merged] == ["alpha-local", "zeta-remote", "home"]
    assert merged[0]["source"] == "tui"


def _in_memory_rows(app: Any, kind: str) -> list[dict[str, Any]]:
    return [row.to_dynamic() for row in _in_memory_candidates(app, kind)]


async def test_proc_slot_fetches_from_the_provider_when_app_state_is_empty(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no live procs the ``proc`` slot falls back to the provider."""
    from sase.completion.candidates.protocol import Candidate

    fetched: list[str] = []

    def _fetch(kind: str) -> list[Candidate]:
        fetched.append(kind)
        return [Candidate("proc-77", "just check")]

    _stub_provider(monkeypatch, _fetch)
    async with _panel(grammar_handle) as (page, screen):
        assert _in_memory_candidates(page.app, "proc") == []
        await _type(page, screen, "proc show ")
        await _await_provider_task(screen)
        assert fetched == ["proc"]
        assert "proc-77" in _shown(screen)


async def test_project_slot_merges_provider_rows_behind_the_tui_projects(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project no loaded agent mentions still completes through the provider."""
    from sase.completion.candidates.protocol import Candidate

    fetched: list[str] = []

    def _fetch(kind: str) -> list[Candidate]:
        fetched.append(kind)
        return [Candidate("zeta-remote", "enabled"), Candidate("home", "enabled")]

    _stub_provider(monkeypatch, _fetch)
    async with _panel(grammar_handle) as (page, screen):
        monkeypatch.setattr(page.app, "_projects", ["alpha-local"], raising=False)
        assert [row.value for row in _in_memory_candidates(page.app, "project")] == [
            "alpha-local"
        ]
        await _type(page, screen, "project disable ")
        await _await_provider_task(screen)
        assert fetched == ["project"]
        assert {"alpha-local", "zeta-remote", "home"} <= set(_shown(screen))


# -- the marked row on a mounted screen ---------------------------------------------


async def test_marked_row_for_a_variadic_agent_slot_on_the_mounted_screen(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``agent wait `` offers ``‹N marked›`` built from the Agents-tab mark order."""
    from tests.ace.tui._agent_marking_helpers import _make_agent

    alpha = _make_agent(
        cl_name="alpha", agent_name="alpha", raw_suffix="20240101120000"
    )
    beta = _make_agent(cl_name="beta", agent_name="beta", raw_suffix="20240101130000")
    idle = _make_agent(cl_name="idle", agent_name="idle", raw_suffix="20240101140000")
    async with _panel(grammar_handle) as (page, screen):
        app = page.app
        monkeypatch.setattr(app, "_agents", [alpha, beta, idle])
        monkeypatch.setattr(app, "_agents_with_children", [alpha, beta, idle])
        monkeypatch.setattr(app, "_marked_agent_order", [beta.identity, alpha.identity])
        await _type(page, screen, "agent wait ")

        first = screen._popup_state.items[0]
        assert first["display"] == "‹2 marked›"
        assert first["insert_text"] == "beta alpha "
        assert {"alpha", "beta", "idle"} <= set(_shown(screen))

        await _type(page, screen, "agent show ")  # a single-value slot: no marked row
        assert not any("marked" in text for text in _shown(screen))


# -- the key-to-paint probe ---------------------------------------------------------


async def test_probe_keeps_a_strong_reference_to_its_append_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop holds tasks weakly, so the probe must hold its own until done."""
    from sase.ace.tui.command_line import completion_probe

    path = tmp_path / "perf.jsonl"
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(path))

    completion_probe.schedule_command_line_keystroke_probe(
        lambda callback: callback(), time.perf_counter(), True
    )
    pending = set(completion_probe._PENDING_APPENDS)
    assert len(pending) == 1
    await asyncio.gather(*pending)
    await asyncio.sleep(0)
    assert not completion_probe._PENDING_APPENDS
    assert json.loads(path.read_text(encoding="utf-8"))["indexed"] is True


async def test_probe_starts_at_key_receipt_not_at_the_refresh(
    grammar_handle: Any,
    history_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample includes the Key -> ``TextArea.Changed`` queue delay."""
    from sase.ace.tui.command_line.input import CommandLineInput

    perf_path = tmp_path / "perf.jsonl"
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(perf_path))

    def _samples() -> list[dict[str, Any]]:
        if not perf_path.exists():
            return []
        return [
            json.loads(line)
            for line in perf_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    async with _panel(grammar_handle) as (page, screen):
        refresh_entries: list[float] = []
        real_refresh = screen._refresh_completion

        def _spy_refresh() -> None:
            refresh_entries.append(time.perf_counter())
            real_refresh()

        monkeypatch.setattr(screen, "_refresh_completion", _spy_refresh)
        sent_at = time.perf_counter()
        await page.press("b")
        await page.wait_for(
            lambda _state: any(s["t_keypress"] >= sent_at for s in _samples())
        )
        sample = next(s for s in _samples() if s["t_keypress"] >= sent_at)
        assert sample["action"] == "command_line.complete"
        assert refresh_entries
        assert sent_at <= sample["t_keypress"] < refresh_entries[0]

        widget = screen.query_one(CommandLineInput)
        # A refresh that finds the text the key arrived with was not that key's.
        widget._keypress_stamp = (1.0, widget.text)
        assert widget.take_keypress_stamp() is None
        widget._keypress_stamp = (2.0, widget.text + "x")
        assert widget.take_keypress_stamp() == 2.0
        assert widget.take_keypress_stamp() is None
