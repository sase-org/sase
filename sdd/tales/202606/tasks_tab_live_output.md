---
create_time: 2026-06-28 14:45:41
status: done
prompt: sdd/prompts/202606/tasks_tab_live_output.md
---
# Plan: Beautiful, Live Output for the Admin Center "Tasks" Tab

## 1. Problem & Product Context

The **SASE Admin Center → Tasks** tab (`#` then `4`) is where users watch every background operation the TUI runs:
`sase update`, plugin install/update/uninstall, dev update, and the ChangeSpec/agent VCS actions (sync, mail, accept,
rebase, revert, submit, archive, restore, status transitions, reword, tag, launch, and the fast save/dismiss/kill
persistence tasks).

Today the output is, bluntly, useless. For the most important task — `sase update`, which runs `uv tool upgrade sase`
and can take 10–60s of network + build time — the entire right-hand pane shows a single line: **"Task is running…"**,
then on completion shows only **"Completed: …"** in dim text. The user has no idea what is happening, whether it is
stuck, what packages are being resolved/built, or what actually changed.

### Root cause (verified in code)

The defect is architectural, not cosmetic:

1. **Subprocess output is never captured.** `capture_output()` in `src/sase/ace/tui/task_queue.py` redirects
   `sys.stdout`/`sys.stderr` — _Python-level objects_. Subprocesses (`uv`, `git`, `hg`) write to OS file descriptors
   1/2, which the redirect does not touch. So nothing a subprocess emits ever reaches the live buffer.
2. **The biggest tasks capture-and-discard.** `run_uv()` (`src/sase/uv_tool/runner.py`) runs
   `subprocess.run(capture_output=True)`, parses the result into a structured change set, and throws the raw text away.
   During the run the buffer is empty ("Task is running…"); after the run the buffer is _still_ empty, so the pane shows
   "Completed: …" while the genuinely useful change summary is dropped on the floor.
3. **The capture is thread-unsafe.** `sys.stdout` is process-global but is reassigned from inside Textual worker
   threads. Concurrent tasks (or a UI-thread `print`) corrupt each other's output.
4. **There is no "liveness" affordance.** No command echo, no current-phase label, no elapsed timer, and the `●` running
   icon never animates. A long task is indistinguishable from a hung one.
5. **Kill does not kill.** `_kill_background_task()` cancels the Textual worker but never terminates the child
   subprocess, so `uv`/`git` keeps running after "Killed by user".

### Goal

Make the output of **every** background task **much better** and **as live/realtime as possible**. Where true realtime
streaming is hard, show meaningful structured context _before and during_ the long operation (command, phase, elapsed)
so the pane is never empty or mute. The result must be **intuitive, reliable, and beautiful**.

### Non-goals

- Not changing _what_ the tasks do, only how they report and render progress.
- Not building a general pub/sub event bus or moving task execution into Rust (see §7).
- Not adding new task types.

## 2. Design Overview

Three pillars, each independently valuable and shippable:

- **Pillar A — A reliable streaming output model.** Replace the broken global-stdout hijack with a thread-safe,
  append-only, bounded `TaskLog` carried on `TaskInfo`, plus structured metadata (command, phase, elapsed, exit status).
  This is the foundation; everything else renders from it.
- **Pillar B — Streaming execution primitives + per-task adoption.** Give task bodies a small `TaskReporter` handle with
  `phase()`, `log()`, and a **line-streaming subprocess runner** (`reporter.run(argv)`). Adopt it across the task
  catalog in tiers, biggest payoff first.
- **Pillar C — A beautiful, live renderer.** Redesign the Tasks pane: an always-present **header card** (label, animated
  spinner, echoed command, live elapsed timer, current phase), a semantically-styled **streamed body**, and a clean
  **result footer** on completion. Animate the spinner and elapsed clock smoothly; re-render only when content changes.

The litmus for "done": open the Tasks tab during `sase update` and see the live `uv` resolution log scroll by under a
header reading `$ uv tool upgrade sase ⠹ 0:07 · Resolving packages…`, ending in a tidy "Updated sase + 3 plugins in 12s"
summary card — never a bare "Task is running…".

## 3. Pillar A — Reliable Streaming Output Model

### 3.1 `TaskLog` (new, thread-safe, bounded)

Add a `TaskLog` type (in `task_queue.py` or a sibling `task_output.py`) that owns task output:

- Append-only list of `TaskLogLine(text, stream, ts)` where `stream ∈ {stdout, stderr, progress, header, result}` drives
  styling.
- A `threading.Lock` guarding all mutation/snapshot; a monotonically increasing **`version`** counter bumped on every
  append so the renderer can cheaply skip no-op repaints.
- **Bounded** by a ring buffer (e.g. last ~5,000 lines / ~512 KB) with a "… N earlier lines trimmed" head marker, so a
  chatty long task cannot grow memory without bound.
- `snapshot()` returns an immutable view; `text()` returns the joined string (for copy/edit).

### 3.2 `TaskInfo` changes

Extend `TaskInfo` with: `log: TaskLog` (replaces `_live_buffer: io.StringIO`), `command: list[str] | None` (echoed in
the header), `phase: str | None` (current high-level step), and `exit_code: int | None`. `get_live_output()` is
reimplemented on top of `TaskLog.text()` so the existing copy/edit actions keep working unchanged.
`started_at`/`finished_at` already exist and drive the elapsed clock.

### 3.3 Retire the global stdout hijack

`capture_output()`'s global `sys.stdout`/`sys.stderr` swap is removed as the _primary_ path. Output becomes **explicit**
via the reporter (§4), which is both thread-safe and actually captures subprocesses. For backward compatibility during
migration, a thin, opt-in `redirect_print_to(log)` helper (using `contextlib.redirect_stdout` to a per-task writer that
appends to that task's `TaskLog`) remains available for not-yet-migrated Python tasks, but it is per-call and documented
as best-effort — it is no longer the mechanism the marquee tasks rely on.

## 4. Pillar B — Streaming Execution Primitives

### 4.1 `TaskReporter`

A lightweight handle handed to each task body, wrapping that task's `TaskInfo`/`TaskLog`:

- `reporter.phase(label)` — set the high-level phase shown in the header (e.g. "Resolving packages", "Building
  sase-core-rs", "Pushing to origin"); also drops a styled marker line.
- `reporter.log(text, *, stream="stdout")` — append a line (thread-safe).
- `reporter.run(argv, **kw) -> CompletedProcess` — **the streaming subprocess runner** (§4.2).
- `reporter.section(title)` — optional visual divider for multi-step tasks.

The reporter is threaded into task bodies by extending `_submit_tracked_task()` / `_submit_background_task()` in
`src/sase/ace/tui/actions/task_actions.py` to pass a reporter to the callable. To avoid a 25-call-site flag-day, the
submit helpers accept **both** zero-arg callables (legacy, wrapped with best-effort print capture) and reporter-taking
callables (detected by arity), so adoption is incremental and each tier lands independently.

### 4.2 Streaming subprocess runner

A new `stream_subprocess(argv, *, on_line, cancel_event, cwd, env, timeout) -> CompletedProcess` helper (new module
`src/sase/ace/tui/task_subprocess.py`). It:

- Spawns via `subprocess.Popen` with `stdout=PIPE`, `stderr=STDOUT` (merged, ordered), `text=True`, line-buffered, in
  its own process group (`start_new_session=True`) so it can be killed cleanly.
- A reader loop pumps **each line to `on_line` as it arrives** (this is the realtime path) while accumulating the full
  text, and returns a `subprocess.CompletedProcess`-shaped result so existing parsers are unchanged.
- Honors a `cancel_event`: on set, terminates the process group (SIGTERM, escalating to SIGKILL).
- Registers the live `Popen`/process group on the `TaskInfo` so **kill actually kills** (§6).

This mirrors the real-time stderr-streaming pattern the workflow executor already uses for python steps
(`src/sase/xprompt/workflow_executor_steps_script.py`), generalized and made the standard.

### 4.3 `run_uv` integration (zero churn to its parser)

`run_uv()` already accepts an injectable `run_fn` matching `subprocess.run`'s signature. We pass a streaming `run_fn`
built from `stream_subprocess` + the reporter, so uv's resolution log streams live **and** the existing
`parse_uv_output()` still runs on the accumulated text. The uv runner's own logic needs no change; only
`run_sase_update_summary()` and the plugin-op task bodies thread the reporter through. Critically, on success we now
also feed the **change-set summary** into the result footer instead of discarding it.

### 4.4 Per-task adoption tiers

Adopt the reporter across the catalog, highest payoff first. Each tier is a shippable increment.

- **Tier 1 — Streaming subprocess tasks (the screenshot offenders).** `sase update`, `dev update`, plugin
  install/update/uninstall. These get true live `uv`/`git` output via §4.2/§4.3, a command-echo header, phase labels,
  and a rich result footer (packages added/upgraded/removed). This is where "Task is running…" → live log has the
  largest impact.
- **Tier 2 — Workflow & VCS tasks.** sync, mail, accept, rebase, revert, submit, archive, restore, status transitions,
  reword, add_tag, launch. These already shell out to `git`/`hg`/workflow steps and `print`/`console.print`. Route their
  subprocess calls through the streaming runner where feasible, and add `reporter.phase()` markers at the meaningful
  boundaries (claim workspace → checkout → operation → push). In-process workflow classes (e.g. AcceptWorkflow) that
  emit nothing get explicit `phase()` reporting so the pane shows progress rather than silence.
- **Tier 3 — Fast persistence tasks.** save, dismiss, kill, agent-directive, revert_preview. These are sub-second, so
  streaming is moot; instead they get an **immediate action header** ("Persisting dismissal of 3 agents…") and a
  **structured result summary** ("✓ Dismissed agent-a, agent-b, agent-c") — satisfying the "show meaningful output even
  when realtime is unnecessary" requirement.

A task's adoption is mechanical: swap its body's hidden subprocess/`print` calls for `reporter.run(...)` /
`reporter.phase(...)` / `reporter.log(...)`. No behavior changes.

## 5. Pillar C — Beautiful, Live Renderer

Redesign the right-hand output pane (`src/sase/ace/tui/modals/tasks_pane.py` + `styles.tcss`) from "dump the buffer into
a `Static`" into a structured, three-zone view:

### 5.1 Header card (always present — fixes the empty pane)

A compact, styled card rendered even before any output exists:

```
  sase update                                          ⠹  0:07
  $ uv tool upgrade sase
  Resolving packages…
  ────────────────────────────────────────────────────────────
```

- Task label + **animated braille spinner** while running (✓/✗ on completion).
- **Live elapsed timer** (`m:ss`), ticking smoothly.
- **Echoed command** (`$ …`) when the task ran one, dim/monospace.
- **Current phase** (`reporter.phase(...)`), so even with zero stdout the pane says what's happening.

This single change eliminates the "Task is running…" dead-end: the header is informative from t=0.

### 5.2 Streamed body

The `TaskLog` lines, rendered with light semantic styling (reuse the approach in
`src/sase/ace/tui/util/axe_log_renderer.py`): stderr tinted, `phase`/`section` markers emphasized, errors/warnings
highlighted, ANSI preserved via `Text.from_ansi`. Output is **capped/tailed** using the existing `lazy_syntax.py` caps
so huge logs stay responsive. Smart auto-scroll (already present) is retained: stick to bottom while running unless the
user scrolls up.

### 5.3 Result footer (on completion)

A clean outcome card replacing today's dim "Completed: …":

```
  ────────────────────────────────────────────────────────────
  ✓ Updated sase + 3 plugins in 12s
      ↑ sase            1.4.2 → 1.5.0
      ↑ sase-telegram   0.3.1 → 0.3.4
      + sase-nvim       (new)  0.1.0
```

For `sase update`/plugin ops this is the change-set summary we currently discard. For VCS tasks it is the final status
line; for failures it is the error with the captured tail. Success is cyan/green, failure red, with the elapsed time.

### 5.4 Task list (left pane) polish

Animate the running row's spinner (same frames), keep the colored status icons, and show a concise secondary line
(current phase or final outcome) under each row so the list itself is scannable.

### 5.5 Animation & refresh (performance-safe)

Per `memory/tui_perf.md` (never block the event loop; selective updates over full rebuilds):

- A single lightweight timer (~120ms) advances the spinner frame and the elapsed clock **only while ≥1 task is running
  and the Tasks tab is active**; it stops otherwise. Spinner/clock updates touch only the header widgets, not the list
  or body.
- The body re-renders **only when `TaskLog.version` changed** since the last paint (cheap integer compare), not
  unconditionally every tick.
- All task work stays on worker threads; the renderer only reads thread-safe snapshots. No synchronous I/O or subprocess
  calls on the event loop.

## 6. Reliability

- **Kill actually kills.** `stream_subprocess` registers the child process group on `TaskInfo`;
  `_kill_background_task()` sets the task's `cancel_event` and terminates the process group (SIGTERM→SIGKILL) before
  marking the task killed — no orphaned `uv`/`git`.
- **Thread safety.** All output flows through `TaskLog`'s lock; no shared global stdout. Concurrent tasks cannot corrupt
  each other.
- **Bounded memory.** Ring-buffered log with a trimmed-head marker.
- **Cancellation cooperation.** The reader loop and the runner poll `cancel_event` so a killed task stops promptly even
  mid-stream.
- **Failure capture.** On non-zero exit/exception, the captured tail is preserved and shown in the result footer (today
  errors often show with no context).
- **Graceful absence.** If a task ran no subprocess and reported no phases, the header still shows label + spinner +
  elapsed; the body shows a tasteful "Working…" rather than a hard-coded string.

## 7. Rust Core Boundary (explicitly considered)

Per `CLAUDE.md`, shared backend/domain behavior belongs in `../sase-core`. This feature is evaluated against that litmus
("would another frontend need this to match the TUI?") and is **correctly Python/TUI-local**:

- The Tasks tab, its live task model, and its renderer are presentation infrastructure unique to the ACE TUI; there is
  no CLI/web equivalent of "the Tasks tab" to keep in sync.
- The underlying operations keep their existing boundaries: the uv runner is already Python (`src/sase/uv_tool/`),
  workflow execution is already Python (`src/sase/xprompt/`), and Rust-side agent spawning (detached-to-file) is
  untouched.
- `stream_subprocess` is a thin local subprocess adapter, not a reimplementation of core domain logic, so it stays here
  per the "thin local adapter" allowance.

If a future non-TUI frontend ever needs identical live task semantics, the streaming runner + task model would be the
thing to lift into Rust — flagged here as out of scope, not overlooked.

## 8. Testing

- **Unit:** `TaskLog` thread-safety/bounding/version counter; `stream_subprocess` line ordering, merged streams,
  cancellation/kill, timeout; the streaming `run_fn` adapter feeding `parse_uv_output` (live lines + correct final
  parse); reporter arity-detection in the submit helpers; kill terminates the process group.
- **Behavioral:** the marquee tasks (`sase update`, a plugin op, sync) produce a non-empty header + streamed body +
  result footer; a failing task surfaces its captured tail.
- **Visual PNG snapshots** (`just test-visual`, goldens in `tests/ace/tui/visual/snapshots/png/`): new goldens for the
  header card (running, with spinner frame pinned for determinism), a mid-stream body, the success footer, and the
  failure footer. Spinner frame and elapsed text are injected as fixed values in fixtures to keep renders deterministic.
- Update `tests/ace/tui/test_tasks_pane.py` for the new model and rendering paths.

## 9. Rollout (incremental, each step shippable)

1. **Foundation:** `TaskLog`, `TaskInfo` fields, reporter plumbing in the submit helpers, retire the global hijack
   (legacy print-capture shim retained). No visible change yet; existing tests green.
2. **Streaming primitive:** `stream_subprocess` + the uv `run_fn` adapter + real kill-the-process.
3. **Tier 1 adoption + renderer:** wire `sase update`/dev-update/plugin ops to the reporter and ship the new
   header/body/footer renderer + spinner. This is the headline UX win (the screenshot fix).
4. **Tier 2 adoption:** sync/mail/VCS/launch tasks gain phase reporting + streamed subprocess output.
5. **Tier 3 adoption:** fast persistence tasks gain immediate action header + structured summaries.
6. **Polish:** left-list secondary lines, visual snapshot goldens, help/hints text refresh.

## 10. Risks & Mitigations

- **Perf regression from animation.** Mitigated by gating the timer on active-tab + running-count, touching only header
  widgets, and version-gated body repaints (§5.5); validate with `SASE_TUI_PERF=1` (target p95 < 16ms).
- **uv parse drift.** The streaming adapter accumulates the exact same text `subprocess.run` would have returned, so
  `parse_uv_output` is unaffected; covered by a dedicated test.
- **Migration surface (25 call sites).** Arity-based back-compat means tiers land independently; unmigrated tasks keep
  working via the legacy shim until adopted.
- **Output flooding.** Bounded ring buffer + tail caps keep memory and render cost flat.

## 11. Primary Files Touched

- `src/sase/ace/tui/task_queue.py` — `TaskLog`, `TaskInfo` fields, retire global hijack.
- `src/sase/ace/tui/task_subprocess.py` _(new)_ — `stream_subprocess`, `TaskReporter`, uv adapter.
- `src/sase/ace/tui/actions/task_actions.py` — reporter plumbing, arity detection, real kill.
- `src/sase/ace/tui/modals/tasks_pane.py` — header/body/footer renderer, spinner/elapsed timer.
- `src/sase/ace/tui/styles.tcss` — header card, footer, list secondary-line styling.
- Task bodies by tier: `modals/plugins_browser_sase_update.py`, `plugins_browser_{install,update, uninstall}.py`;
  `actions/sync.py`, `actions/base.py`, `actions/proposal_rebase.py`, `actions/status.py`, agent persistence actions;
  `src/sase/uv_tool/` only via injected `run_fn`.
- Tests: `tests/ace/tui/test_tasks_pane.py`, new unit tests, new visual snapshot goldens.
