---
create_time: 2026-07-06 22:55:05
status: done
prompt: sdd/prompts/202607/chat_update_builtin_engine.md
---
# Plan: Consolidate chat `/update` with the built-in SASE update engine

## Problem

The sase-telegram `/update` command (and the mobile gateway's `update-start` helper) launch the shared chat update
worker in `src/sase/integrations/chat_install.py`, whose core step is running a **user-configured shell command**
(`chat_install.command`). If that config is empty, `/update` refuses with `config_missing_command`.

Meanwhile, SASE has grown first-class update machinery that makes the custom script unnecessary:

- The Admin Center **Updates tab** `u` keymap and the **`sase update`** CLI command share the same engines:
  `src/sase/uv_tool/` (managed uv-tool installs: `uv tool upgrade sase` atomically re-resolves core + all injected
  plugins) and `src/sase/dev_update/` (editable/dev installs: fast-forward checkouts + reconcile + Rust rebuild).
  Routing between the two is automatic (`probe_uv_tool_install` + editable detection).
- Both surfaces already handle AXE restart: the TUI re-execs `sase ace --restart-axe`; the CLI restarts AXE inline via
  `restart_after_update` (`src/sase/main/update_restart.py`) when the update actually changed code and AXE is running.

So today there are two divergent update paths: the built-in engine (TUI + CLI) and the chat worker's arbitrary shell
command (with its own workspace resolution + VCS sync preamble that only existed to serve custom `just install`-style
scripts). This plan consolidates them: the chat worker drives the built-in engine, and `chat_install.command` (plus its
`sync_workspace` companion) is removed.

## Goals

1. `/update` from Telegram (and the mobile `update-start` helper) performs a real SASE update with **zero
   configuration**, using the exact same engine and routing (managed vs dev/editable) as the TUI Updates tab and
   `sase update`.
2. Preserve the chat worker's async architecture unchanged: single-flight lock, detached worker process, job state,
   timestamped logs, and the completion record that Telegram/mobile poll — the wire contracts consumers depend on stay
   compatible.
3. Remove the now-dead config surface (`chat_install.command`, `chat_install.sync_workspace`) and the launch statuses
   that only existed because of it (`config_missing_command`, `workspace_resolution_failed`).
4. Richer completion messages: surface "already up to date" / what changed instead of only an exit code.

## Non-goals

- No Rust core (`sase-core`) changes. The sase-58 epic's boundary decision (D6) already established that managing sase's
  own install lifecycle is Python packaging/process machinery, and the restart tale reaffirmed it. Nothing here crosses
  the boundary.
- No changes to the TUI Updates tab, `sase update`, or `sase plugin ...` behavior.
- No rename of the `chat_install` module/config key/state paths (kept deliberately for compatibility per
  `docs/integrations.md`).
- No cross-process notification of an already-running TUI when a chat update lands (same non-goal as the plugin restart
  tale; the Updates indicator covers staleness).

## Design

### 1. The worker runs `sase update --json` instead of the custom command

Rewrite the payload of `_run_worker` in `src/sase/integrations/chat_install.py`:

- **Drop** the workspace resolution (`_resolve_primary_workspace_for_chat_install`,
  `_resolve_registered_sase_workspace`) and the VCS `sync_workspace` step. They existed to give the custom script a
  synced checkout to install from; the built-in engine needs neither (managed updates pull from PyPI; dev updates sync
  their own checkouts under `update.dev_root` as part of `plan_dev_update`/`execute_dev_update`).
- **Run the update as a subprocess**: `[sys.executable, "-m", "sase", "update", "--json"]`, with
  `timeout=config.timeout_seconds` (timeout still maps to exit code 124). Stdout/stderr are captured into the worker log
  exactly like today, and the JSON payload (versioned via `UPDATE_JSON_SCHEMA_VERSION`) is parsed best-effort to build
  the completion message ("Update completed: sase 0.5.0 → 0.6.1, 2 plugins updated", "Already up to date", or the typed
  detection error). Parsing failures fall back to today's exit-code-based message, so schema drift can never break the
  worker.

Why a subprocess of the real CLI rather than importing the engine in-process or calling `handle_update_command`
directly:

- It is the strongest form of consolidation: the chat path executes literally the same command a user would run, so
  routing (managed vs dev), rendering conventions, error messages, and future `sase update` improvements are inherited
  for free — no third orchestration of the uv_tool/dev_update primitives that could drift (the TUI mixins and the CLI
  handler are already two).
- The update replaces the very venv the worker is running from; keeping the mutation in a child process (as the current
  custom-command design already does) isolates the worker's post-update bookkeeping from the swapped environment.
- `sase update` is non-interactive by default (epic D5); without `-t/--to` there is no prompt, so it is safe to drive
  headlessly.

Non-uv-tool installs (pip/pipx, dev-checkout venv) now fail fast with the engine's strict-detection actionable error
(epic D4) in the log and completion message, instead of silently depending on whatever the custom script did. This is
the intended behavior, and a **deliberate breaking change** for anyone whose `/update` relied on a custom script to
update a non-canonical install.

### 2. AXE handling: stop pre-stopping, keep the safety net

Today the worker unconditionally stops AXE before updating and restarts it in its cleanup path. Neither the TUI `u` path
nor `sase update` stops AXE up front — they restart it after a changed update — so pre-stopping is not required by the
engine's own standard, and it creates avoidable downtime when the update fails.

New behavior:

- The worker no longer stops AXE first. `sase update` itself restarts AXE inline when code changed and AXE is running
  (existing `restart_after_update` semantics; its restart info also lands in the JSON payload and the log).
- After the subprocess returns, the worker runs an **ensure-AXE-running** step reusing the existing retry helper
  (`restart_axe` in `_chat_install_worker.py`, honoring `chat_install.restart_attempts`): if AXE is not running, start
  it with retries. This preserves today's contract that AXE is up after every `/update` attempt, keeps exit code 5 ("axe
  restart failed") and the `restart_succeeded` completion field meaningful, and improves the failure story — a failed
  update now leaves a running AXE untouched on old code instead of stop/starting it.

### 3. Config + status surface cleanup

- `src/sase/default_config.yml` and `src/sase/config/sase.schema.json`: remove `chat_install.command` and
  `chat_install.sync_workspace`; keep `timeout_seconds` and `restart_attempts`. The schema is strict
  (`additionalProperties: false`), so users with the old keys will get a validation nudge from config tooling to delete
  them — desirable visibility for a removed knob; call it out in the docs.
- `_chat_install_models.py`: shrink `ChatInstallConfig` accordingly; drop `config_missing_command` and
  `workspace_resolution_failed` from `LaunchStatus`. `ChatInstallLaunchResult`/`ChatInstallStatusResult` keep their
  shapes otherwise.
- `_chat_install_config.py`: stop reading the removed keys (unknown keys in user config are ignored by the loader, so
  stale configs keep working at runtime).
- `_chat_install_cli.py`: drop the now-unneeded required `--workspace` argument; the completion record's `workspace`
  field becomes optional (readers already `.get()` it; nothing downstream renders it).
- `start_chat_install_worker()` no longer needs config/workspace preconditions — it acquires the lock and launches.
- Mobile helpers (`_mobile_helper_updates.py`): remove the branch raising `MobileHelperBridgeError` for the two removed
  statuses. Wire schema unchanged.
- Docs: `docs/configuration.md#chat_install` (rewrite: zero-config built-in update; remaining fields),
  `docs/integrations.md` chat-update-worker section (new worker step list), `docs/mobile_gateway.md` mention of
  `chat_install.command`. Historical blog posts stay untouched.

### 4. sase-telegram side

In the sase-telegram repo (open it via `sase workspace open -p sase-telegram ...`):

- `_format_update_ack` in `src/sase_telegram/scripts/sase_tg_inbound.py`: drop the `config_missing_command` and
  `workspace_resolution_failed` branches. Keep the generic `result.message` fallback and the existing
  `_ChatInstallUnavailableResult` import-fallback so the plugin still degrades gracefully against an older sase (version
  skew must stay tolerable in both directions; new sase + old telegram already works because the old branches simply
  never fire).
- `_format_update_completion`: prefer the completion record's `message` field when present (this is where the new "what
  changed" summary surfaces in Telegram), falling back to today's exit-code text; keep appending the log path.
- Docs: README.md `/update` bullets and the "Update" section of `docs/inbound.md` — describe the built-in zero-config
  update (managed + dev routing, AXE ensure-running) instead of `chat_install.command`.

## Testing

- `tests/test_chat_install.py` (sase): rewrite worker tests around an injected fake subprocess runner — assert the exact
  `sase update --json` argv, timeout wiring and the 124 mapping, JSON-derived vs fallback completion messages,
  ensure-AXE-running retry behavior (started when down, untouched when up, exit code 5 on exhaustion), lock adoption,
  and completion-record round-trip with the optional `workspace`. Launch tests lose the config/workspace precondition
  cases and gain a "launches with empty config" case.
- `tests/test_mobile_helper_updates.py`: statuses cleanup; start/status wire payloads unchanged otherwise.
- sase-telegram `tests/test_inbound.py`: `/update` ack formatting for the surviving statuses; completion formatting
  prefers `message` with exit-code fallback; unavailable-fallback behavior preserved.
- Run `just check` in both repos.

## Risks / edge cases

- **Breaking change**: custom `chat_install.command` scripts stop being honored. Anyone updating a non-uv-tool install
  via `/update` now gets the strict-detection error with guidance. This is the point of the consolidation, but it must
  be prominent in the changelog/docs.
- **Dev updates can be slow** (Rust rebuild). `timeout_seconds` default (900) is retained and now bounds `sase update`;
  document that dev-mode users may need to raise it.
- **Version skew**: an older installed sase without the new worker behavior paired with a newer sase-telegram (and vice
  versa) must keep working; the design above keeps both directions compatible via unchanged wire shapes and fallback
  formatting.
- The worker inherits `sase update`'s single inline AXE restart plus its own ensure-running retries; double restarts
  cannot occur because the ensure step only starts AXE when it is not running.

## Sequencing (each step independently shippable, `just check` green)

1. **sase repo — worker rewrite**: subprocess-driven `sase update --json`, AXE ensure-running, config/model/status
   cleanup, schema + default config, unit tests.
2. **sase repo — consumer + docs sweep**: mobile helper status cleanup, `docs/configuration.md`, `docs/integrations.md`,
   `docs/mobile_gateway.md`.
3. **sase-telegram repo**: ack/completion formatting, README + `docs/inbound.md`, inbound tests.
