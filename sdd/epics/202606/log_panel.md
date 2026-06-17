---
create_time: 2026-06-17 14:18:05
bead_id: sase-4t
tier: epic
status: wip
prompt: sdd/prompts/202606/log_panel.md
---
# Plan: `,L` Log Panel + Reliable Launch-Failure Logging

## Problem & Product Context

Today, when an agent launch or fan-out fails, the TUI shows an error toast such as `"Agent launch failed (see log)"` —
but there is **no way to view "the log" from the TUI**, and in most cases there is no durable log to view at all:

- The failure handlers call `log.exception(...)` on a module logger (`logging.getLogger(__name__)`), but `sase ace`
  never installs a file handler for the `sase` logger, so those tracebacks go nowhere the user can find.
- Only **fan-out** failures persist anything (`_record_fanout_launch_failure` writes
  `~/.sase/notifications/fanout_failures/*.txt`). Single-agent, multi-prompt, repeat, bulk, workflow, and chop failures
  persist nothing — the toast is the only trace, and it disappears.

So "see the log" is, for most failures, a dead end.

We will fix both halves of the problem:

1. **Reliability** — every agent launch / fan-out / multi-prompt / repeat / bulk / workflow / chop failure is _always_
   written to a durable log file that the panel shows.
2. **Visibility** — a new `,L` keymap (works from any tab) opens a **Log panel** that surfaces a few relevant logs,
   beautifully and intuitively. The "(see log)" toasts are rewritten to point users to `,L`.

This is led as a design: the result must be **intuitive, reliable, and beautiful**.

## Design Overview

### Two complementary log files (the reliability backstop)

We introduce/curate the canonical logs the panel shows, under `~/.sase/logs/`:

| Log source                           | File                                            | Role                                                                                                                                                                                                                                   |
| ------------------------------------ | ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Launch failures** (NEW, primary)   | `~/.sase/logs/launch_failures.log` (+ `.jsonl`) | Every launch/fan-out/workflow/chop failure, explicitly written with full context + traceback. Curated & human-readable.                                                                                                                |
| **TUI diagnostics** (NEW, catch-all) | `~/.sase/logs/tui.log`                          | A rotating `FileHandler` attached to the `sase` logger at `sase ace` startup. Captures _every_ existing `log.exception(...)`/`log.warning(...)` automatically — the backstop so even un-instrumented failures land somewhere findable. |
| Agent runs (existing)                | `~/.sase/logs/runs.jsonl`                       | Recent agent runs, for context.                                                                                                                                                                                                        |
| Events (existing)                    | `~/.sase/logs/events.jsonl`                     | Recent events (commits, revives, etc.), for context.                                                                                                                                                                                   |

The launch-failure log is the **explicit, guaranteed** record (written by each handler); `tui.log` is the **implicit,
automatic** record (written by the logging framework). Having both means the "see log" promise is honored even if a
future failure path forgets to call the explicit logger.

### Backend: a small launch-failure logging API

New module `src/sase/logs/launch_log.py`, sibling to the existing `run_log.py` and following its exact conventions
(module-level path overrides for tests, `fcntl`-locked append, `sase_subdir("logs")`):

```python
def log_launch_failure(
    *,
    kind: str,            # "single" | "fanout" | "multi_prompt" | "repeat" | "bulk" | "workflow" | "chop"
    display_name: str,
    exc: BaseException,
    project: str | None = None,
    workspace_num: int | None = None,
    prompt_preview: str | None = None,
    **context: Any,       # fanout_kind, slot_count, workflow_name, chop, vcs_ref, etc.
) -> None:
    """Append a structured record to launch_failures.jsonl AND a formatted,
    human-readable block (timestamp header, kind, display name, project,
    workspace, exception class+message, full traceback, prompt preview,
    extra context) to launch_failures.log."""
```

The existing fan-out-specific `_record_fanout_launch_failure` / `_write_fanout_failure_report` keep their
**notification** behavior, but their failure detail is routed through `log_launch_failure(kind="fanout", ...)` so
fan-out failures land in the same canonical log as everything else (no special-casing in the panel).

### Backend boundary note (Rust core)

Per `memory/short/rust_core_backend_boundary.md`, shared backend behavior belongs in `../sase-core`. We make a
**deliberate, documented decision to keep launch-failure logging in Python's `sase.logs` package**, because:

- The established precedent for exactly this kind of structured logging (`runs.jsonl`/`events.jsonl` via
  `sase.logs.run_log`, fan-out reports) is already Python.
- The failure context originates in Python TUI launch handlers and exceptions.
- The cross-frontend contract is the **file format and paths under `~/.sase/logs/`**, which any frontend (CLI, web) can
  read — that contract is documented in this plan and in code.

Phase 1 must first check `sase-core` for any existing launch/event-log API (`sase workspace open -p sase-core <N>`); if
one exists, route through the binding instead of adding a parallel Python writer. If not, the Python writer stands.

### Log source registry (the backend↔UI contract)

A single source-of-truth registry decouples "what logs exist / how to read them" (backend) from "how the panel renders
them" (UI). New module (e.g. `src/sase/ace/tui/logs/sources.py`):

```python
@dataclass(frozen=True)
class LogSource:
    id: str                 # "launch_failures" | "tui" | "runs" | "events"
    title: str              # "Launch & Fan-out Failures"
    description: str        # one-line subtitle
    path: Path              # canonical path from sase.logs
    render: str             # "text" | "jsonl"   (jsonl is pretty-rendered)
    def read_tail(self, max_lines: int) -> str: ...   # efficient seek-tail

LOG_SOURCES: list[LogSource] = [...]   # ordered; launch_failures first (default)
```

Tail reading reuses the existing efficient `read_tail_seek` in `sase.axe.state` (O(tail), not O(file)). Canonical paths
come from `sase.logs` so there is one definition of each path.

### UI: the Log panel modal

New `LogModal(OptionListNavigationMixin, CopyModeForwardingMixin, ModalScreen[None])` in
`src/sase/ace/tui/modals/log_modal.py`, modeled on the existing `AgentRunLogModal` (two-panel list+detail) with
`HelpModal`'s styling conventions:

- **Left panel** — `OptionList` of the registry's `LogSource`s. Each row shows the title, plus last-modified time and
  size, and a subtle marker (e.g. `●`) when the file is non-empty. Default selection is **Launch & Fan-out Failures**.
- **Right panel** — `VerticalScroll` + `Static` rendering the selected log's tail as Rich `Text`:
  - Header line: file path · last modified · line count.
  - Severity colorization: `ERROR`/tracebacks in red, `WARNING` in yellow, timestamps in cyan, dim for stack frames
    (consistent with existing modal palette `#87D7FF`/`#FFD700`).
  - JSONL sources are pretty-rendered (one compact, readable line per record), not raw JSON.
  - **Empty-state** message when a file is missing/empty (e.g. _"No launch failures logged 🎉"_).
- **Footer hints**: `j/k navigate · [ ] cycle logs · ctrl+d/u scroll · r refresh · esc close`.
- `r` re-reads the tail (logs grow live); copy-mode (`%`) works via the forwarding mixin.
- Styling added to `src/sase/ace/tui/styles.tcss` following the `HelpModal` pattern (`align: center middle`,
  `double $primary` outer border, `scrollbar-gutter: stable`).

### Keymap wiring (`,L`, global / any tab)

`,L` is a **leader-mode** chord (`comma` enters leader mode, then `L`). `L` is currently free in `leader_mode.keys`. It
is dispatched with **no `current_tab` guard**, so it works from every tab. Files (the established 4-point leader-key
contract):

1. `src/sase/default_config.yml` → add `log_panel: "L"` under `ace.keymaps.modes.leader_mode.keys`.
2. `src/sase/ace/tui/keymaps/types.py` → add `"log_panel": "L"` to `LeaderModeKeymaps.keys` default factory.
3. `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py` → add a `log_panel` branch in `_dispatch_leader_key` (no
   tab guard) calling `action_show_log_panel()`.
4. `src/sase/ace/tui/widgets/_keybinding_modes.py` → include `,L` in the leader-mode footer for all tabs (the leader
   footer lists available `,`-subkeys).

Plus the handler `action_show_log_panel()` (new actions mixin) → `self.push_screen(LogModal())`, and a help-modal entry
(`src/sase/ace/tui/modals/help_modal/`) per the "Help Popup Maintenance" rule in `src/sase/ace/AGENTS.md`.

### Message updates

All "(see log)" toasts are rewritten to point at the panel with consistent phrasing via a shared constant (one place to
change wording), e.g.:

> `Agent launch failed — press ,L for the log`

Sites to update (exhaustive, from the launch-failure audit):

- `_launch_multi_model.py:168`, `:149`
- `_launch_multi_prompt.py:103`, `:95`
- `_launch_repeat.py:202` (and the dynamic `NameCollisionError` path `:194`)
- `_launch_bulk.py:153`
- `_launch_body.py:49`, `:113`, `:621`
- `_launch_tasks.py:89`
- `_workflow_exec.py:223`
- `axe_chop_run.py:204`

## Phases

Each phase is completed by a **distinct agent instance**, leaves the repo green (`just install && just check`), and is
independently reviewable.

### Phase 1 — Reliable failure-logging foundation (backend, no UI)

**Goal:** every launch/fan-out/multi-prompt/repeat/bulk/workflow/chop failure is durably logged with full context;
define the log-source registry contract.

- Check `sase-core` for an existing launch/event-log API; decide routing (see boundary note).
- Add `src/sase/logs/launch_log.py` with `log_launch_failure(...)` writing both `launch_failures.jsonl` and the
  human-readable `launch_failures.log` (run_log conventions: locked append, module-level path overrides for tests).
- Add `install_tui_file_logging()` (e.g. `src/sase/ace/tui/log_setup.py`) attaching a `RotatingFileHandler` for the
  `sase` logger → `~/.sase/logs/tui.log`; call it once at `sase ace` startup. Ensure it does not double-install, and is
  scoped to the TUI (not the bare CLI / tests).
- Wire **every** failure site listed above to call `log_launch_failure(...)`; generalize `_record_fanout_launch_failure`
  to delegate failure detail to the shared logger while keeping its notification.
- Add `src/sase/ace/tui/logs/sources.py` with `LogSource` + `LOG_SOURCES`, reusing `read_tail_seek`; canonical paths
  exported from `sase.logs`.
- **Tests:** unit-test `log_launch_failure` (both files written, traceback captured); test the registry readers (tail,
  empty-state, jsonl pretty-render); at least one test per failure category asserting a record is persisted.

**Acceptance:** inducing an agent launch failure writes the error+traceback to both `launch_failures.log` and `tui.log`.
No UI yet. `just check` green.

### Phase 2 — `,L` keymap + Log panel modal (functional UI)

**Goal:** `,L` opens a working Log panel from any tab, consuming the Phase 1 registry.

- Add `LogModal` (`src/sase/ace/tui/modals/log_modal.py`) + `styles.tcss` rules: left `OptionList` of sources, right
  scrollable colorized detail, footer hints, `r` refresh, copy-mode, empty states, default-select launch failures.
- Keymap wiring (4-point contract above) + `action_show_log_panel()` handler + leader-footer entry; verify `L` is free
  and config/types parity holds.
- Help-modal entry documenting `,L`.
- **Tests:** Textual pilot test that `,`→`L` opens the modal from each tab, navigates sources, and scrolls; a smoke test
  that the modal renders each source without error.

**Acceptance:** from any tab, `,L` opens a navigable, scrollable, dismissible Log panel showing the four logs.
`just check` green.

### Phase 3 — Message updates + end-to-end reliability audit

**Goal:** close the loop — every failure toast points to `,L`, and every toast path has a matching durable log write.

- Replace all "(see log)" strings with the shared `,L` hint constant across the sites above.
- Audit each failure site to guarantee a `log_launch_failure(...)` write exists (add any Phase 1 missed — e.g. the
  `_launch_tasks.py:89` generic fallback, the `axe_chop_run.py:204` chop path, the `_launch_body.py` name-reuse path).
- Nice-to-have: stash a "last failure" pointer so opening `,L` right after a failure highlights/jumps to the freshest
  entry.
- **Tests:** assert updated message text; assert each failure path persists a log entry the panel would show.

**Acceptance:** every failure message references `,L`; opening `,L` after a failure shows that exact failure.
`just check` green.

### Phase 4 — Beauty pass, visual snapshots & docs

**Goal:** make it beautiful and lock it down.

- Finalize aesthetics: borders, header, severity colorization, last-modified/size in the list, empty-state copy, scroll
  affordances; tune to the existing modal palette.
- Add PNG visual snapshot goldens for the panel (repo visual suite under `tests/ace/tui/visual/snapshots/png/`; accept
  via `--sase-update-visual-snapshots`).
- Docs: finalize the help-modal entry; update `src/sase/ace/AGENTS.md` help-popup sync if needed; verify no
  `memory/long/cli_rules.md` or `generated_skills.md` sync is required (only if a CLI surface was added — none is
  currently planned).
- **Acceptance:** `just check` + `just test-visual` green; panel matches goldens.

## Testing Strategy

- **Unit:** `launch_log` writers, registry tail/empty/jsonl rendering, file-handler install.
- **Per-failure-category:** each of the ~12 sites persists a record.
- **TUI pilot:** `,L` opens from each tab; navigation/scroll/refresh/dismiss.
- **Visual:** PNG snapshot of the panel (Phase 4).
- `just check` (ruff + mypy + pytest) after every phase; `just test-visual` in Phase 4.

## Risks & Notes

- **`tui.log` noise/volume:** scope the handler to the `sase` logger at `WARNING+` (or `INFO+`) with rotation so it
  stays focused on problems and bounded in size.
- **Footer convention:** `,L` is global, so per `src/sase/ace/AGENTS.md` it belongs in the **help modal** (not the
  conditional bottom footer); but it _does_ belong in the **leader-mode footer** (the list of `,`-subkeys shown while
  leader mode is active).
- **No new CLI surface** is planned, so the CLI/skill-contract and generated-skills pipelines should not need changes —
  Phase 4 verifies this.
- **Keymap parity:** keep `default_config.yml` and `LeaderModeKeymaps.keys` in sync (the gotchas memory); leader keys
  are not part of the `_BINDING_META`/`AppKeymaps` validation, so add an explicit parity check or test if convenient.
