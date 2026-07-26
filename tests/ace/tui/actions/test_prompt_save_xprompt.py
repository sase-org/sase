"""Prompt-bar writes selected by the unified xprompt/snippet save panel."""

from __future__ import annotations

import asyncio
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml  # type: ignore[import-untyped]
from textual.app import App, ComposeResult

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt import (
    PromptBarSaveXpromptMixin,
    _run_git_commit_push_sync,
)
from sase.ace.tui.modals import (
    ConfirmActionModal,
    UnifiedSaveLocation,
    UnifiedXPromptSaveModal,
    UnifiedXPromptSaveResult,
)
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import StashedPromptPane
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat


class _SaveHarness(PromptBarSaveXpromptMixin):
    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.git_offers: list[tuple[str, bool, str, str]] = []
        self._user_snippets: dict[str, str] = {}
        self._snippets_cache: dict[str, str] | None = None
        self._pending_snippet_saves: dict[str, str] = {}

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _offer_git_commit(
        self,
        file_path: str,
        *,
        is_new: bool,
        xprompt_name: str,
        noun: str = "xprompt",
        commit_type: str = "xprompt",
    ) -> None:
        del commit_type
        self.git_offers.append((file_path, is_new, xprompt_name, noun))


class _CommitHarness(PromptBarSaveXpromptMixin):
    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.submitted: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.config_refreshes: list[str] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _submit_tracked_task(self, *args: object, **kwargs: object) -> object:
        self.submitted.append((args, kwargs))
        return object()

    def _request_prompt_catalog_config_refresh(self, *, reason: str) -> None:
        self.config_refreshes.append(reason)


class _SaveFlowApp(PromptBarSaveXpromptMixin, App[None]):
    """Exercise prompt dispatch and the real async save-panel boundary."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._prompt_context = None
        self._user_snippets: dict[str, str] = {}
        self._snippets_cache: dict[str, str] | None = None
        self._pending_snippet_saves: dict[str, str] = {}
        self.save_requests: list[PromptInputBar.SaveAsXpromptRequested] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value)

    async def on_prompt_input_bar_save_as_xprompt_requested(
        self, event: PromptInputBar.SaveAsXpromptRequested
    ) -> None:
        self.save_requests.append(event)
        await super().on_prompt_input_bar_save_as_xprompt_requested(event)

    def _offer_git_commit(self, *_args: object, **_kwargs: object) -> None:
        pass

    def get_snippets(self) -> dict[str, str]:
        return self._snippets_cache or self._user_snippets


async def _wait_save_tasks(harness: object) -> None:
    tasks = list(getattr(harness, "_xprompt_save_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def test_empty_save_request_toasts_noop() -> None:
    harness = _SaveHarness()
    await harness.on_prompt_input_bar_save_as_xprompt_requested(
        PromptInputBar.SaveAsXpromptRequested([])
    )
    await _wait_save_tasks(harness)
    assert harness.notifications == [("Nothing to save as an xprompt", "warning")]
    assert harness.pushed == []


async def test_request_opens_one_screen_with_active_pane_snippet_source() -> None:
    harness = _SaveHarness()
    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [
                    StashedPromptPane(text="alpha", frontmatter=""),
                    StashedPromptPane(text="beta", frontmatter=""),
                ],
                snippet_body="beta",
            )
        )
        await _wait_save_tasks(harness)

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    assert modal._body == "alpha\n---\nbeta"
    assert modal._snippet_body == "beta"
    assert modal._pane_count == 2


async def test_request_converts_placeholders_for_xprompt_preview_only() -> None:
    harness = _SaveHarness()
    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [
                    StashedPromptPane(
                        text="Deploy <service> to <target file>",
                        frontmatter=(
                            "---\n"
                            "input:\n"
                            "  service:\n"
                            "    type: path\n"
                            "    default: api\n"
                            "---"
                        ),
                    )
                ],
                snippet_body="Deploy <service> to <target file>",
            )
        )
        await _wait_save_tasks(harness)

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    assert modal._body == "Deploy {{ service }} to {{ target_file }}"
    assert modal._snippet_body == "Deploy <service> to <target file>"
    service = modal._frontmatter.get_input("service")
    assert service is not None
    assert service.type is InputType.PATH
    assert service.default == "api"
    target = modal._frontmatter.get_input("target_file")
    assert target == InputArg(name="target_file", type=InputType.TEXT)


async def test_request_reuses_undeclared_jinja_name_without_duplicate_input() -> None:
    harness = _SaveHarness()
    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [StashedPromptPane(text="Deploy <service> with {{ service }}")]
            )
        )
        await _wait_save_tasks(harness)

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    assert modal._body == "Deploy {{ service }} with {{ service }}"
    assert modal._frontmatter.inputs == []


async def test_ctrl_g_ctrl_x_ctrl_x_opens_panel_in_snippet_mode(
    tmp_path: Path,
) -> None:
    xprompt_directory = tmp_path / "xprompts"
    xprompt_directory.mkdir()
    snippet_config = tmp_path / "sase.yml"
    snippet_config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    xprompt_location = UnifiedSaveLocation(
        location=XPromptLocation("Xprompts", str(xprompt_directory), "directory"),
        group="CWD directories",
        display_path=str(xprompt_directory),
        names=frozenset(),
    )
    snippet_location = UnifiedSaveLocation(
        location=XPromptLocation("Snippets", str(snippet_config), "config"),
        group="Config files",
        display_path=str(snippet_config),
        names=frozenset(),
    )
    app = _SaveFlowApp("draft to reuse")

    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[xprompt_location],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[snippet_location],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        async with app.run_test(size=(105, 36)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            text_area = bar.active_text_area()

            await pilot.press("ctrl+g", "ctrl+x")
            for _ in range(20):
                await pilot.pause()
                if isinstance(app.screen, UnifiedXPromptSaveModal):
                    break

            modal = app.screen
            assert isinstance(modal, UnifiedXPromptSaveModal)
            assert len(app.save_requests) == 1
            assert bar.all_prompt_texts() == ["draft to reuse"]
            assert text_area._insert_g_prefix_pending is False
            assert bar._g_prefix_hints_visible is False

            await pilot.press("ctrl+x")
            assert modal._mode == "snippet"
            assert bar.all_prompt_texts() == ["draft to reuse"]

    # Opening and toggling the deterministic panel never writes either target.
    assert list(xprompt_directory.iterdir()) == []
    assert snippet_config.read_text(encoding="utf-8") == "ace:\n  snippets: {}\n"


async def test_save_request_returns_while_location_reads_are_stuck() -> None:
    harness = _SaveHarness()
    entered = threading.Event()
    release = threading.Event()

    def _slow_locations(*_args: object) -> list[object]:
        entered.set()
        release.wait(timeout=1.0)
        return []

    def _slow_last_used() -> dict[str, str]:
        entered.set()
        release.wait(timeout=1.0)
        return {}

    try:
        with (
            patch(
                "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
                side_effect=_slow_locations,
            ),
            patch(
                "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
                side_effect=_slow_locations,
            ),
            patch(
                "sase.xprompt.save_state.load_last_used_locations",
                side_effect=_slow_last_used,
            ),
        ):
            await asyncio.wait_for(
                harness.on_prompt_input_bar_save_as_xprompt_requested(
                    PromptInputBar.SaveAsXpromptRequested(
                        [StashedPromptPane(text="draft")]
                    )
                ),
                timeout=0.05,
            )
            await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
    finally:
        release.set()
        await _wait_save_tasks(harness)


async def test_unified_markdown_result_writes_typed_name_authoritatively(
    tmp_path: Path,
) -> None:
    harness = _SaveHarness()
    target = UnifiedXPromptSaveResult(
        mode="xprompt",
        name="ns/foo",
        path=str(tmp_path / "ns_foo.md"),
        location_path=str(tmp_path),
        target_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        display_path="./ns_foo.md",
        exists=False,
        frontmatter=PromptFrontmatter(name="ns/foo", description="Saved"),
    )
    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        await harness._write_xprompt_target(target, "new body")

    written = Path(target.path).read_text(encoding="utf-8")
    assert "name: ns/foo" in written
    assert "description: Saved" in written
    assert written.endswith("new body\n")
    assert harness.notifications == [("Created xprompt 'ns/foo'", None)]
    assert harness.git_offers == [(target.path, True, "ns/foo", "xprompt")]


async def test_unified_config_result_inserts_xprompt(tmp_path: Path) -> None:
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("theme: dark\n", encoding="utf-8")
    harness = _SaveHarness()
    target = UnifiedXPromptSaveResult(
        mode="xprompt",
        name="review",
        path=str(config),
        location_path=str(config),
        target_format=SaveTargetFormat.CONFIG,
        entry_name="review",
        display_path="./sase/sase.yml",
        exists=False,
        frontmatter=PromptFrontmatter(description="Review code"),
    )
    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        await harness._write_xprompt_target(target, "check this")

    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert payload["xprompts"]["review"] == {
        "description": "Review code",
        "content": "check this",
    }


async def test_unified_snippet_result_writes_only_active_pane_and_refreshes(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    harness = _SaveHarness()
    target = UnifiedXPromptSaveResult(
        mode="snippet",
        name="review",
        path=str(config),
        location_path=str(config),
        target_format=None,
        entry_name="review",
        display_path="./sase/sase.yml",
        exists=False,
        frontmatter=PromptFrontmatter(),
    )

    with (
        patch("sase.xprompt.save_state.save_last_used_location", return_value=True),
    ):
        await harness._write_snippet_target(target, "beta")

    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert payload["ace"]["snippets"] == {"review": "beta"}
    assert harness._user_snippets == {}
    assert harness._pending_snippet_saves == {"review": "beta"}
    assert harness._snippets_cache == {"Review": "Beta", "review": "beta"}
    assert harness.git_offers == [(str(config), True, "review", "snippet")]


async def test_chezmoi_source_save_expands_in_same_mounted_prompt_before_apply(
    tmp_path: Path,
) -> None:
    source_config = tmp_path / "chezmoi" / "dot_config" / "sase" / "sase.yml"
    source_config.parent.mkdir(parents=True)
    source_config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    target = UnifiedXPromptSaveResult(
        mode="snippet",
        name="welcome",
        path=str(source_config),
        location_path=str(source_config),
        target_format=None,
        entry_name="welcome",
        display_path="chezmoi source",
        exists=False,
        frontmatter=PromptFrontmatter(),
    )
    app = _SaveFlowApp("draft")
    app._user_snippets = {"applied": "Applied"}
    app._snippets_cache = {
        "applied": "Applied",
        "xprompt": "Hello $1$0",
    }
    app._prompt_catalog = SimpleNamespace(
        explicit_snippets={
            "applied": "Applied",
            "xprompt": "Hello $1$0",
        }
    )

    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        async with app.run_test() as pilot:
            text_area = app.query_one(PromptTextArea)
            assert text_area.is_mounted

            await app._write_snippet_target(target, "#[xprompt] from $1")

            assert app._pending_snippet_saves == {"welcome": "#[xprompt] from $1"}
            assert app._snippets_cache["applied"] == "Applied"
            assert app._snippets_cache["xprompt"] == "Hello $1$0"
            assert app._snippets_cache["welcome"] == "Hello $1 from $2$0"
            assert app._snippets_cache["Welcome"] == "Hello $1 from $2$0"

            text_area.load_text("Welcome")
            text_area.cursor_location = (0, len("Welcome"))
            with patch.object(
                type(text_area),
                "_ace_app",
                new_callable=lambda: property(lambda _self: app),
            ):
                assert text_area._try_expand_snippet() is True
            assert app.query_one(PromptTextArea) is text_area
            assert text_area.text == "Hello  from "
            await pilot.pause()


async def test_second_save_replaces_pending_trigger_deterministically(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    target = UnifiedXPromptSaveResult(
        mode="snippet",
        name="review",
        path=str(config),
        location_path=str(config),
        target_format=None,
        entry_name="review",
        display_path=str(config),
        exists=False,
        frontmatter=PromptFrontmatter(),
    )
    harness = _SaveHarness()

    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        await harness._write_snippet_target(target, "first")
        await harness._write_snippet_target(target, "second")

    assert harness._pending_snippet_saves == {"review": "second"}
    assert harness._snippets_cache == {"Review": "Second", "review": "second"}


async def test_live_save_preserves_authored_capital_collision_off_event_loop() -> None:
    from sase.ace.tui import prompt_catalog

    harness = _SaveHarness()
    harness._user_snippets = {"Foo": "authored capital"}
    event_loop_thread = threading.get_ident()
    composition_threads: list[int] = []
    real_compose = prompt_catalog.compose_pending_snippet_saves

    def record_compose(
        explicit_snippets: dict[str, str],
        pending_snippet_saves: dict[str, str],
    ) -> dict[str, str]:
        composition_threads.append(threading.get_ident())
        return real_compose(explicit_snippets, pending_snippet_saves)

    with patch.object(
        prompt_catalog,
        "compose_pending_snippet_saves",
        side_effect=record_compose,
    ):
        await harness._publish_saved_snippet("foo", "lower save")

    assert composition_threads
    assert all(thread_id != event_loop_thread for thread_id in composition_threads)
    assert harness._pending_snippet_saves == {"foo": "lower save"}
    assert harness._snippets_cache == {
        "Foo": "authored capital",
        "foo": "lower save",
    }


def test_commit_push_confirmation_submits_tracked_task(tmp_path: Path) -> None:
    path = tmp_path / "xprompts" / "review.md"
    path.parent.mkdir()
    path.write_text("body", encoding="utf-8")
    harness = _CommitHarness()
    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.has_git_changes",
            return_value=True,
        ),
    ):
        harness._offer_git_commit(str(path), is_new=True, xprompt_name="review")
        confirm, callback = harness.pushed[0]
        assert isinstance(confirm, ConfirmActionModal)
        assert callable(callback)
        callback(True)
    assert len(harness.submitted) == 1
    args, kwargs = harness.submitted[0]
    assert args[:3] == ("xprompt-commit", "xprompts/review.md", str(tmp_path))
    assert kwargs["dedup_key"] == f"xprompt-commit:{tmp_path}:xprompts/review.md"


def test_successful_snippet_commit_refreshes_config_catalog(tmp_path: Path) -> None:
    path = tmp_path / "sase.yml"
    path.write_text("ace: {}\n", encoding="utf-8")
    harness = _CommitHarness()
    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.has_git_changes",
            return_value=True,
        ),
    ):
        harness._offer_git_commit(
            str(path),
            is_new=False,
            xprompt_name="review",
            noun="snippet",
            commit_type="snippet",
        )
        _confirm, callback = harness.pushed[0]
        assert callable(callback)
        callback(True)

    on_complete = harness.submitted[0][1]["on_complete"]
    assert callable(on_complete)
    on_complete(
        SimpleNamespace(
            success=True,
            message="Committed and pushed; applied chezmoi changes",
            payload=False,
        )
    )

    assert harness.config_refreshes == ["snippet_commit_apply"]


def test_failed_or_skipped_snippet_commit_does_not_refresh_catalog(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sase.yml"
    path.write_text("ace: {}\n", encoding="utf-8")
    harness = _CommitHarness()
    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.has_git_changes",
            return_value=True,
        ),
    ):
        harness._offer_git_commit(
            str(path),
            is_new=False,
            xprompt_name="review",
            noun="snippet",
            commit_type="snippet",
        )
        _confirm, callback = harness.pushed[0]
        assert callable(callback)
        callback(False)
        assert harness.submitted == []

        callback(True)

    on_complete = harness.submitted[0][1]["on_complete"]
    assert callable(on_complete)
    on_complete(
        SimpleNamespace(success=False, message="chezmoi apply failed", payload=False)
    )

    assert harness.config_refreshes == []


def test_git_commit_push_worker_runs_git_sequence(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    path = tmp_path / "review.md"
    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=run,
        ),
        patch("sase.config.get_use_chezmoi", return_value=False),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is True
    assert calls[-3:] == [
        ["git", "-C", str(tmp_path), "commit", "-m", "chore: Add xprompt review"],
        ["git", "-C", str(tmp_path), "pull", "--rebase"],
        ["git", "-C", str(tmp_path), "push"],
    ]


def test_git_commit_push_worker_stops_on_add_failure(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    with patch(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
        return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="pathspec"),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )
    assert result.success is False
    assert result.message == "Git add failed: pathspec"


def test_git_commit_push_worker_backs_off_then_removes_stale_index_lock(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    commit_attempts = 0

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal commit_attempts
        if argv[3] == "commit":
            commit_attempts += 1
            if lock.exists():
                return subprocess.CompletedProcess(
                    argv,
                    128,
                    stdout="",
                    stderr=f"fatal: Unable to create '{lock}': File exists.",
                )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=run,
        ),
        patch("sase.git_lock_retry.git_lock_retry_delays", return_value=(0.001, 0.001)),
        patch("sase.config.get_use_chezmoi", return_value=False),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(tmp_path / "review.md"),
            commit_message="chore: Add xprompt review",
        )
    assert result.success
    assert result.index_lock_removed
    assert commit_attempts == 4
    assert not lock.exists()
