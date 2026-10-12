"""Review stage and read-only CLI check for the New Project wizard."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

from sase.ace.tui.actions._durable_ops import sase_argv
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.modals.confirm_dialog import ConfirmKind
from sase.ace.tui.modals.projects_pane_init import check_timeout, init_cwd
from sase.ace.tui.session_proc_reporter import SessionProcReporter
from sase.noninteractive_subprocess import run_noninteractive
from sase.workspace_provider.utils import non_interactive_git_env

from .new_project_review_model import (
    ApplySubmission,
    ReviewView,
    apply_submission,
    build_review,
    strip_transport_flags,
)
from .new_project_rendering import clean_source_text

_ADD_DUPLICATE_MESSAGE = "This project add plan is already being checked."
_CREATE_DUPLICATE_MESSAGE = "This project create plan is already being checked."
_PUBLIC_STYLE = "#FFAF5F"


def _document_mode(document: Mapping[str, Any]) -> str:
    return str(document.get("mode") or "add")


def _duplicate_message(mode: str) -> str:
    if mode == "create":
        return _CREATE_DUPLICATE_MESSAGE
    return _ADD_DUPLICATE_MESSAGE


def _check_argv(document: Mapping[str, Any]) -> list[str]:
    """Build the CLI check argv from the reviewed document's apply argv."""
    raw = document.get("apply_argv")
    argv = [str(item) for item in raw] if isinstance(raw, list) else []
    if argv and argv[0] == "sase":
        argv = argv[1:]
    return sase_argv(*strip_transport_flags(argv), "--check", "--json")


def _run_check(
    argv: list[str],
    cwd: str,
    timeout: float,
    reporter: SessionProcReporter,
    *,
    mode: str = "add",
) -> TrackedProcResult[dict[str, Any]]:
    """Run and decode ``sase project add|create … --check --json``."""
    verb = "create" if mode == "create" else "add"
    reporter.log(f"Checking the project {verb} plan…")
    env = non_interactive_git_env()
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        result = run_noninteractive(argv, cwd=cwd, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return TrackedProcResult(
            success=False,
            message=f"Project check failed: {error}",
            error=str(error),
        )
    if result.returncode not in (0, 1):
        detail = (result.stderr or result.stdout or "").strip()
        message = f"Project check exited {result.returncode}"
        if detail:
            message += f": {detail[-1200:]}"
        return TrackedProcResult(success=False, message=message, error=message)
    try:
        document = json.loads(result.stdout)
    except ValueError as error:
        detail = (result.stderr or result.stdout or "").strip()
        message = f"Could not read project check plan: {error}"
        if detail:
            message += f"\n{detail[-1200:]}"
        return TrackedProcResult(success=False, message=message, error=message)
    if not isinstance(document, dict):
        return TrackedProcResult(
            success=False,
            message="Project check returned an invalid plan document.",
            error="invalid plan document",
        )
    return TrackedProcResult(
        success=True, message="Project plan ready.", payload=document
    )


class NewProjectReview(Vertical):
    """Read-only project add or create plan with confirmation."""

    class ApplyRequested(Message):
        """The user confirmed the exact plan shown in Review."""

        def __init__(self, submission: ApplySubmission) -> None:
            super().__init__()
            self.submission = submission

    class BackRequested(Message):
        """The user asked to return to Configure."""

    BINDINGS = [
        ("y", "confirm", "Apply"),
        ("b", "back", "Back"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._document: dict[str, Any] = {}
        self._view: ReviewView | None = None
        self._loading = False
        self._check_generation = 0
        self._notice = ""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="new-project-review-scroll"):
            yield Static(
                "ADD PLAN",
                id="new-project-review-card-heading",
                classes="new-project-card-heading",
            )
            yield Static(
                "Checking the exact add plan…",
                id="new-project-review-state",
                markup=False,
            )
            yield Static("", id="new-project-review-rows", markup=False)
            yield Static("", id="new-project-review-warnings", markup=False)
            yield Static("", id="new-project-review-blockers", markup=False)
            yield Static("", id="new-project-review-argv", markup=False)
        with Horizontal(id="new-project-review-actions"):
            yield Button("‹ Configure", id="new-project-review-back")
            yield Button(
                "Add project  [y]",
                id="new-project-review-confirm",
                disabled=True,
                variant="primary",
            )

    def on_unmount(self) -> None:
        self._bump_generation()
        self._loading = False
        self._view = None

    def show_loading(self, message: str = "Checking the exact add plan…") -> None:
        """Clear confirmability and show a loading state for resume or check."""
        self._bump_generation()
        self._loading = True
        self._view = None
        self._notice = ""
        self.set_class(False, "review-ready")
        if self.is_mounted:
            self._render_loading(message)

    def invalidate_check(self) -> None:
        """Drop in-flight check identity so a stale completion cannot confirm."""
        self._bump_generation()
        self._loading = False
        self._view = None
        self.set_class(False, "review-ready")
        if self.is_mounted:
            self._disable_confirm()

    def start_check(self, document: dict[str, Any], *, notice: str = "") -> None:
        """Submit the exact check command and render its returned plan."""
        self._document = dict(document)
        self._view = None
        self._notice = notice
        self._loading = True
        generation = self._bump_generation()
        fingerprint = str(document.get("intent_fingerprint") or "")
        identity_key = str((document.get("target") or {}).get("identity_key") or "")
        mode = _document_mode(document)
        self.set_class(False, "review-ready")
        self.set_class(mode == "create", "danger")
        if self.is_mounted:
            self._render_loading()
        app = self.app
        submit = getattr(app, "_submit_session_worker", None)
        if not callable(submit):
            self.set_error("Project check queue is unavailable.")
            return
        argv = _check_argv(document)
        cwd = str(init_cwd())
        timeout = check_timeout(1)

        def task(reporter: SessionProcReporter) -> TrackedProcResult[dict[str, Any]]:
            return _run_check(argv, cwd, timeout, reporter, mode=mode)

        def completed(result: TrackedProcCompletion[dict[str, Any]]) -> None:
            self._apply_check_completion(generation, fingerprint, result)

        if mode == "create":
            submitted = submit(
                "project-create-check",
                task,
                on_complete=completed,
                display_name="Check project create plan",
                cl_name=identity_key,
                dedup_key=f"project-create-check:{identity_key}:{fingerprint}",
                duplicate_message=_duplicate_message(mode),
            )
        else:
            submitted = submit(
                "project-add-check",
                task,
                on_complete=completed,
                display_name="Check project add plan",
                cl_name=identity_key,
                dedup_key=f"project-add-check:{identity_key}:{fingerprint}",
                duplicate_message=_duplicate_message(mode),
            )
        if submitted is None:
            self.set_error(_duplicate_message(mode))

    def show_document(self, document: dict[str, Any], *, notice: str = "") -> None:
        """Render a supplied check document (also used by deterministic previews)."""
        self._bump_generation()
        self._document = dict(document)
        self._notice = notice
        self._loading = False
        self._view = build_review(self._document)
        self.set_class(self._view.is_danger, "danger")
        if self.is_mounted:
            self._render_view()

    def set_error(self, message: str) -> None:
        """Show a check failure and keep confirmation disabled."""
        self._loading = False
        self._view = None
        self.set_class(False, "review-ready")
        if self.is_mounted:
            self.query_one("#new-project-review-state", Static).update(
                Text(clean_source_text(message), style="#FF5F5F")
            )
            self._disable_confirm()

    def _bump_generation(self) -> int:
        self._check_generation += 1
        return self._check_generation

    def _apply_check_completion(
        self,
        generation: int,
        fingerprint: str,
        result: TrackedProcCompletion[dict[str, Any]],
    ) -> None:
        if not self.is_mounted:
            return
        if generation != self._check_generation or not self._loading:
            return
        current = str(self._document.get("intent_fingerprint") or "")
        if fingerprint and current and fingerprint != current:
            return
        self._loading = False
        payload = result.payload
        if result.success and isinstance(payload, dict):
            self._document = payload
            self._view = build_review(payload)
            self._render_view()
            return
        self.set_error(result.message or "Project check failed.")

    def _disable_confirm(self) -> None:
        self.query_one("#new-project-review-confirm", Button).disabled = True

    def _render_loading(self, message: str = "Checking the exact add plan…") -> None:
        mode = _document_mode(self._document)
        if message == "Checking the exact add plan…" and mode == "create":
            message = "Checking the exact create plan…"
        heading = "CREATE PLAN" if mode == "create" else "ADD PLAN"
        self.query_one("#new-project-review-card-heading", Static).update(
            Text(heading, style="bold")
        )
        self.query_one("#new-project-review-state", Static).update(
            Text(clean_source_text(message), style="dim")
        )
        self.query_one("#new-project-review-rows", Static).update("")
        self.query_one("#new-project-review-warnings", Static).update("")
        self.query_one("#new-project-review-blockers", Static).update("")
        self.query_one("#new-project-review-argv", Static).update("")
        confirm = self.query_one("#new-project-review-confirm", Button)
        confirm.disabled = True
        confirm.label = (
            "Create repository  [y]" if mode == "create" else "Add project  [y]"
        )
        kind = ConfirmKind.DANGER if mode == "create" else ConfirmKind.NEUTRAL
        confirm.variant = "error" if kind is ConfirmKind.DANGER else "primary"
        self.set_class(mode == "create", "danger")

    def _heading_text(self, view: ReviewView) -> Text:
        heading = Text()
        if view.is_danger:
            heading.append("! ", style="bold #FF5F5F")
        if view.is_danger and view.visibility:
            heading.append("CREATE ", style="bold")
            vis = view.visibility.upper()
            heading.append(
                vis,
                style=f"bold {view.public_style}" if view.is_public else "bold",
            )
            if view.repo_name:
                heading.append(" " + clean_source_text(view.repo_name), style="bold")
            return heading
        heading.append(clean_source_text(view.heading), style="bold")
        return heading

    def _render_view(self) -> None:
        view = self._view
        if view is None:
            return
        compact = self.size.width < 90
        self.set_class(compact, "compact")
        self.set_class(True, "review-ready")
        self.set_class(view.is_danger, "danger")
        self.set_class(view.is_danger, "confirm-dialog--danger")
        self.set_class(not view.is_danger, "confirm-dialog--neutral")
        self.query_one("#new-project-review-card-heading", Static).update(
            self._heading_text(view)
        )
        state = Text()
        if self._notice:
            state.append(clean_source_text(self._notice), style=_PUBLIC_STYLE)
        else:
            state.append(clean_source_text(view.notice), style="dim")
            if view.keep_notice:
                state.append("\n")
                state.append(clean_source_text(view.keep_notice), style="dim")
        self.query_one("#new-project-review-state", Static).update(state)
        rows = Text()
        for row in view.rows:
            rows.append(row.glyph + " ", style=row.style)
            rows.append(clean_source_text(row.label), style="bold")
            if row.detail and not compact:
                rows.append("  " + clean_source_text(row.detail), style="dim")
            rows.append("\n")
        self.query_one("#new-project-review-rows", Static).update(rows)
        warnings = Text()
        public_warning = any(
            "public visibility" in warning.casefold() for warning in view.warnings
        )
        if view.is_public and not public_warning:
            warnings.append("⚠ PUBLIC visibility\n", style=_PUBLIC_STYLE)
        for warning in view.warnings:
            warnings.append(
                "⚠ " + clean_source_text(warning) + "\n", style=_PUBLIC_STYLE
            )
        self.query_one("#new-project-review-warnings", Static).update(warnings)
        blockers = Text()
        for blocker in view.blockers:
            blockers.append("✗ " + clean_source_text(blocker.message), style="#FF5F5F")
            if blocker.hint:
                blockers.append(
                    "\n  " + clean_source_text(blocker.hint), style="#FF5F5F"
                )
            blockers.append("\n")
        self.set_class(bool(view.blockers), "has-blockers")
        self.query_one("#new-project-review-blockers", Static).update(blockers)
        self.set_class(bool(view.warnings or view.is_public), "has-warnings")
        argv = Text("$ " + clean_source_text(view.argv_line), style="dim")
        self.query_one("#new-project-review-argv", Static).update(argv)
        confirm = self.query_one("#new-project-review-confirm", Button)
        confirm.disabled = not view.can_confirm
        confirm.label = view.confirm_label
        kind = ConfirmKind.DANGER if view.is_danger else ConfirmKind.NEUTRAL
        confirm.variant = "error" if kind is ConfirmKind.DANGER else "primary"

    @on(Button.Pressed, "#new-project-review-back")
    def _back_pressed(self) -> None:
        self.post_message(self.BackRequested())

    @on(Button.Pressed, "#new-project-review-confirm")
    def _confirm_pressed(self) -> None:
        self.action_confirm()

    def action_back(self) -> None:
        self.post_message(self.BackRequested())

    def action_confirm(self) -> None:
        if self._loading or self._view is None or not self._view.can_confirm:
            return
        self.post_message(self.ApplyRequested(apply_submission(self._document)))


__all__ = ["NewProjectReview"]
