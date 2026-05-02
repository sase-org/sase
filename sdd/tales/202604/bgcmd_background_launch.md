---
create_time: 2026-04-24 13:22:30
status: done
prompt: sdd/prompts/202604/bgcmd_background_launch.md
---
# Plan: Move AXE bgcmd launch work off the TUI event loop

## Problem

After the user triggers the AXE background-command workflow (`,!` from leader mode on the CLs tab, or `!!` from any tab)
and confirms the final command modal, the TUI noticeably stalls before the new bgcmd appears. The stall is a blocking
slice of VCS work running on the Textual event loop inside `_start_bgcmd`
(`src/sase/ace/tui/actions/axe_bgcmd.py:140-206`):

1. `run_sase_hg_clean(workspace_dir, f"{cl_name}-bgcmd")` — cleans the target workspace.
2. `provider.resolve_revision(cl_name, project, workspace_dir)` — resolves the CL to a revision.
3. `provider.checkout(resolved, workspace_dir)` — switches the workspace to that revision.
4. `start_background_command(...)` — spawns the actual long-running subprocess.

All four run synchronously on the UI thread, so keystrokes, redraws, and the AXE refresh timer freeze until checkout
returns. Checkout on a large repo commonly dominates, which matches the symptom the user is seeing.

The existing `Y`-sync action has the exact same VCS preamble but runs it on a worker thread via
`_submit_background_task` (`task_actions.py:43`) and surfaces progress through the generic task queue (`TaskQueue`, task
indicator, runners modal, task-queue modal). `!`-launched bgcmds should follow that pattern.

## Goals

- `,!` and `!!` return control to the TUI event loop immediately after the final modal is dismissed; no visible freeze
  during workspace clean, revision resolution, or checkout.
- The user gets feedback that launch work is in flight (toast on submit, spinner/count in the existing task indicator,
  entry visible in the Runners modal / task-queue modal while workspace prep runs).
- On success, the bgcmd appears in the AXE sidebar and the view switches to the new slot — same end state as today.
- On failure, the user sees the same error notifications today's code emits (sase_hg_clean warning, `checkout failed`,
  `Failed to start background command`), and the slot is left clear.
- Per-CL concurrency: reuse the `TaskQueue` dedup so a user hammering `,!` on the same CL doesn't stack parallel
  checkouts against the same workspace.

## Non-goals

- Cancelling an in-flight bgcmd launch. The sync task isn't cancellable mid-checkout either; matching that behavior
  keeps scope tight. (Task-queue modal's existing kill button will still work — it just won't unwind a
  partially-completed VCS step.)
- Changing the modal flow (ProjectSelect → WorkspaceInput → CommandHistory). Modal UX is not the bottleneck.
- Any change to `_rerun_bgcmd` (re-run path skips the VCS preamble — no blocking work to move).
- Reworking `start_background_command` itself (it's a fast `Popen`).

## Design

### Split `_start_bgcmd` into a pure task function + dispatcher

Mirror `sync.py`'s structure: a module-level `_bgcmd_launch_task` that does the VCS work and the subprocess spawn, plus
a thin dispatcher on `AxeBgCmdMixin` that packages the closure and hands it to `_submit_background_task`.

```
# axe_bgcmd.py (sketch)

def _bgcmd_launch_task(
    slot, command, project, workspace_num, workspace_dir, cl_name
) -> tuple[bool, str, int | None]:
    """Run sase_hg_clean + checkout + start_background_command.

    Returns (success, message, pid). `pid` is None on failure so the success
    callback can rely on it being present when success is True.
    """
    if cl_name is not None:
        clean_ok, clean_err = run_sase_hg_clean(workspace_dir, f"{cl_name}-bgcmd")
        if not clean_ok:
            print(f"Warning: sase_hg_clean failed: {clean_err}")  # captured

        provider = get_vcs_provider(workspace_dir)
        resolved = provider.resolve_revision(cl_name, project, workspace_dir)
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            return (False, f"checkout failed: {checkout_err}", None)

    pid = start_background_command(
        slot=slot, command=command, project=project,
        workspace_num=workspace_num, workspace_dir=workspace_dir,
    )
    if pid is None:
        return (False, "Failed to start background command", None)

    return (True, f"Started bgcmd in slot {slot}: {command[:30]}", pid)
```

Two subtle points:

- `start_background_command` mutates disk state under `~/.sase/axe/bgcmd/<slot>/`. That's already designed to be safe
  from non-UI threads (sync uses the same pattern), so moving it off the event loop doesn't introduce new races. The
  slot was reserved synchronously when we picked it in `action_start_bgcmd` / `_start_bgcmd_from_changespec` (via
  `find_first_available_slot`); the worker is still the only writer for that slot.
- `add_or_update_command(command, project, cl_name)` (history write) is currently called after the subprocess launch. We
  move it to the `on_success` callback on the main thread — it's a JSON read-modify-write on
  `~/.sase/command_history.json` and doesn't need to race with the VCS work.

### Dispatcher on `AxeBgCmdMixin`

`_start_bgcmd` becomes:

```
def _start_bgcmd(self, slot, command, project, workspace_num, cl_name=None):
    try:
        workspace_dir = get_workspace_directory(project, workspace_num)
    except RuntimeError as e:
        self.notify(f"Failed to get workspace: {e}", severity="error")
        return

    def task_callable() -> tuple[bool, str]:
        ok, msg, _pid = _bgcmd_launch_task(
            slot, command, project, workspace_num, workspace_dir, cl_name
        )
        return ok, msg

    def on_success() -> None:
        from sase.history.command import add_or_update_command
        add_or_update_command(command, project, cl_name)
        self._load_bgcmd_state()
        self._switch_to_axe_view(slot)

    # Dedup key: prefer cl_name; fall back to a slot-scoped synthetic key so
    # the !! (no-CL) path still gets a TaskQueue entry without colliding
    # across slots.
    dedup_key = cl_name or f"bgcmd-slot-{slot}"
    project_file = ...  # see "Dedup key & project_file" below

    submitted = self._submit_background_task(
        "bgcmd-launch", dedup_key, project_file, task_callable,
        on_success=on_success,
    )
    if submitted:
        cmd_notify = command[:30] + "..." if len(command) > 30 else command
        self.notify(f"Starting: {cmd_notify}")
```

### Dedup key & `project_file`

`_submit_background_task` takes a `cl_name: str` and `project_file: str`; it's used for TaskQueue dedup and for the
Runners/Task-queue modal display.

- When `cl_name` is set (the `,!` path always; the `!!` path if the user picked a CL), use the real CL name and the
  ChangeSpec's `.gp` file path so the task shows up in the runners modal the same way `sync` does, and concurrent `,!`
  invocations on the same CL dedup cleanly. Resolve the project_file from the ChangeSpec list if available; fall back to
  the `<project>.gp` path in `~/.sase/projects/` when the caller only has a project name (the `!!` path after
  ProjectSelectModal may not have a ChangeSpec in-memory).
- When `cl_name` is `None` (the `!!`-project-only path), use `f"bgcmd-slot-{slot}"` as the synthetic dedup key and the
  project's `.gp` path. This keeps the task visible in the runners modal and prevents the user from firing a second `!!`
  at the same slot while the first is still resolving. The dedup collision window is very short (slot becomes busy once
  the subprocess is spawned anyway).

Minor wart: the TaskQueue's dedup message ("A bgcmd-launch task is already running for bgcmd-slot-3") is a little ugly
when the key is synthetic. Worth either (a) special-casing the notify text in the dispatcher when cl_name is None, or
(b) living with it because the collision is rare. Pick (a) — cheap.

### Slot reservation window

Today the slot is "reserved" only by `find_first_available_slot` returning it; nothing writes to the slot dir until
`start_background_command` runs. With the work on a worker thread, a second `!` key press could call
`find_first_available_slot` and get the same slot back before the worker has spawned the subprocess.

Two options, in order of preference:

1. **Write a placeholder marker synchronously** in the dispatcher before submitting the task — e.g. create
   `~/.sase/axe/bgcmd/<slot>/pending` and teach `find_first_available_slot` to treat a slot with a `pending` marker as
   occupied. Clean the marker inside `_bgcmd_launch_task` after `start_background_command` returns (and also in an error
   path). This is the minimal change and keeps slot ownership on disk where the rest of bgcmd state already lives.
2. Keep a process-local `set[int]` of in-flight slots on the mixin and consult it alongside the on-disk check. Simpler
   code, but loses the crash-safety property (a crashed launch would leave no record).

Go with option 1. The `pending` marker also lets the AXE sidebar render a "starting…" row for the slot while the VCS
prep runs, which is a nice-to-have that falls out for free.

### Failure paths & notifications

Map today's inline notifications to the new flow:

| Today (synchronous)                                      | New (task-queue)                                                                                                                                                                                                        |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `notify(f"Failed to get workspace: {e}", error)`         | Same — this still runs synchronously in the dispatcher before the task is submitted.                                                                                                                                    |
| `notify(f"Warning: sase_hg_clean failed: {e}", warning)` | Logged into the task's captured output (the `print` in `_bgcmd_launch_task`). Not surfaced as a toast; user can open the task-queue modal to see it. Matches how sync handles the same warning.                         |
| `notify(f"checkout failed: {e}", error)`                 | Returned as `(False, "checkout failed: …")` — surfaced by `_on_task_worker_completed` as an error toast.                                                                                                                |
| `notify("Failed to start background command", error)`    | Same — returned as `(False, …)`.                                                                                                                                                                                        |
| `notify(f"Started: {cmd_notify}")`                       | Split into two toasts: "Starting: …" on submit (dispatcher) and the task's success message ("Started bgcmd in slot N: …") on completion. The double-notify mirrors sync's "Sync started for X" + "Synced X: …" pattern. |

On failure we also need to clear the `pending` marker so the slot doesn't leak. `_bgcmd_launch_task` should do this in a
`finally`-style cleanup before returning.

### Reload behavior

`_on_task_worker_completed` already calls `self._reload_and_reposition()` for every completed task, which will refresh
the ChangeSpecs view. For bgcmd we additionally need `_load_bgcmd_state()` + `_switch_to_axe_view(slot)`; those go in
the `on_success` callback so they only fire when the launch actually worked. On failure the generic reload is enough.

## Files changed

- `src/sase/ace/tui/actions/axe_bgcmd.py` — extract `_bgcmd_launch_task` module function; rewrite `_start_bgcmd` as the
  dispatcher; resolve `project_file` for the TaskQueue entry.
- `src/sase/ace/tui/bgcmd.py` — add a `pending` marker helper (`mark_slot_pending`, `clear_slot_pending`) and have
  `find_first_available_slot` treat a slot with a `pending` marker as occupied.
- `src/sase/ace/tui/widgets/bgcmd_list.py` — optional: render a "starting…" row for pending slots so the user sees
  immediate feedback in the sidebar. (Nice-to-have; skip if it grows the diff.)
- `tests/test_bgcmd.py` — extend to cover the `pending` marker behavior of `find_first_available_slot`.
- `tests/ace/tui/test_axe_bgcmd.py` (new, mirroring `tests/ace/tui/test_sync.py`) — cover: dispatcher submits a task and
  returns immediately; success callback writes history + switches view; failure path leaves slot clear; per-CL dedup
  blocks a second `,!`.
- Help modal / keybinding docs: no change — user-visible behavior (the triggers, modal flow, end state) is unchanged.

## Risks & open questions

- **Task-queue modal ergonomics.** The runners modal currently lists background tasks keyed by (task_type, cl_name).
  Adding a `bgcmd-launch` task_type is new — confirm the modal groups/sorts sensibly and that the "kill" button is safe.
  Killing mid-checkout won't unwind VCS state but sync has the same caveat, so parity is acceptable.
- **`!!`-no-CL dedup key.** The synthetic `bgcmd-slot-N` key means two users-of-the-same-TUI (not a real scenario) or a
  fast double-press could still deduplicate cleanly; no correctness risk, just a cosmetic dedup message we already
  committed to softening.
- **Crash recovery.** A crash between "pending marker written" and "subprocess spawned" would leave a stale marker.
  Cheapest mitigation: on AceApp startup, clear any pending markers for slots that don't have a live pid. Add this to
  the plan if the reviewer flags it; otherwise defer — users today tolerate stale pid files in the same directory.

## Rollout

Single PR. No feature flag needed — the external behavior is a strict improvement (faster perceived launch, identical
success/failure semantics, new task shows up in existing modals). Before marking complete, exercise `,!` and `!!`
manually in the TUI against a real repo where checkout takes

> 1s to confirm the UI no longer freezes.
