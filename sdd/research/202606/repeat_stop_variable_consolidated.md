# STOP Output Variable: Breaking `%r`/`%repeat` Chains

Status: Research (consolidated from two independent passes)
Date: 2026-06-11

## Question

How should SASE support a new reserved `STOP` output variable, set via `sase var set STOP=1`, that breaks
`%repeat` / `%r` directive loops?

## TL;DR

`%repeat:N` is **not a runtime loop** — it is a launch-time fan-out. All N agents are spawned upfront, and iterations
2..N each get a `%wait:<predecessor>` directive prepended so they block until the prior iteration completes. "Breaking
the loop" therefore means: when an iteration sets `STOP`, every already-spawned downstream iteration must detect it
when it wakes and exit early instead of running its prompt.

**Recommended solution: a post-wake STOP check in the agent runner, with cascade-by-completion.** Pass each repeat
slot its chain predecessor's name via a new `SASE_REPEAT_PREV_NAME` env var (injected at both launch surfaces). After
`wait_for_dependencies()` returns, a repeat-chain member checks that predecessor's `output_variables` for a truthy
`STOP`. If found, it propagates `STOP` into its own `output_variables`, writes a normal `done.json`
(`outcome: "completed"` plus `repeat_stopped: true`), suppresses the completion notification, and exits before
claiming a deferred workspace or invoking the provider. Because the stopped iteration still reports
`outcome: "completed"`, the existing wait-resolution chop resolves the next waiter unchanged and the stop cascades
down the chain — with zero changes to the generic `%wait` machinery. `sase var set` needs no changes either.

The two research passes agreed on all architecture facts and on the cascade/finalization semantics, but differed on
*where* the STOP decision is made: in the runner (post-wake) vs. in the `wait_checks` chop (a `ready.json` stop
payload). The runner-side check wins because both designs end with the waiter self-finalizing anyway, and the
chop-side variant adds strictly more surface (`waiting.json` + `ready.json` schema extensions, a richer chop
dependency index, and a `WaitResult` return type for `wait_for_dependencies()`) for no functional gain. Details under
"Design Options".

## How the Relevant Subsystems Work Today

### 1. `%repeat` is a fan-out, not a loop

- Parsing: `src/sase/xprompt/directives.py` parses `%repeat:N` / `%r:N` into `PromptDirectives.repeat_count`; the
  Rust core planner (`plan_agent_launch_fanout` via `src/sase/core/agent_launch_facade.py`) produces the deterministic
  slot plan, but the chain runtime is pure Python. The core fan-out planner only marks slots after the first as
  `wait_for_previous` (`../sase-core/crates/sase_core/src/agent_launch/mod.rs:1068`) — it knows nothing about concrete
  names or runtime output variables, so STOP needs no Rust parser-contract change.
- Fan-out: `spawn_repeat_batch()` (`src/sase/agent/repeat_launcher.py:84-171`) is the shared entry point for both
  launch surfaces. It expands one prompt into N `RepeatAgentSpec`s (`repeat_launcher.py:50-58`). Iteration 1 gets
  `%n:<base>.1`; iteration k > 1 gets `%n:<base>.k\n%wait:<base>.(k-1)` prepended (`repeat_launcher.py:142-155`). The
  docstring is explicit that sequencing is coordinated at the agent level via generic `%wait`, not by a parent loop
  (`repeat_launcher.py:98-101`).
- Both launch surfaces spawn all slots up front and inject `SASE_REPEAT_NAME`, `SASE_REPEAT_ITERATION`, and
  `SASE_REPEAT_TOTAL` (constants at `repeat_launcher.py:45-47`):
  - TUI: `src/sase/ace/tui/actions/agent_workflow/_launch_repeat.py:105` (spawn) and `:129-134` (`_slot_env`);
  - CLI/cwd (`sase run -d` style): `src/sase/agent/launch_cwd.py:329` (spawn) and `:347-352` (`_spawn_repeat_slot`).
- There is **no chain/group ID** and **no existing early-exit mechanism**. Today a chain only stops early if an
  iteration fails (its waiter then blocks until the 24h wait timeout, after which it proceeds anyway) or the user
  kills agents in the TUI.

### 2. `sase var` output variables

- Skill source: `src/sase/xprompts/skills/sase_var.md` → agents run `sase var set KEY=VALUE ...`.
- CLI: `src/sase/main/parser_var.py`, handler `src/sase/main/var_handler.py` (requires `SASE_AGENT=1` and
  `SASE_ARTIFACTS_DIR`); the handler does not special-case variable names — a property worth keeping. `STOP` should
  be a convention interpreted by repeat orchestration, not by the var-writing command.
- Storage: `src/sase/core/agent_output_variables.py` merges keys into `agent_meta.json["output_variables"]` under an
  fcntl lock with an atomic rename (`:63`, `:94-101`). Keys match `[A-Za-z_][A-Za-z0-9_]*` (`:19`), so `STOP` is a
  valid key today — it just has no special meaning.
- Consumption: `src/sase/agent/output_variable_context.py` builds the reserved Jinja `agents` namespace for
  downstream agents, resolving waited producers via `_resolve_waited_agent()` (`:180-197`, using
  `resolve_resume_agent_name()` + the producer's `agent_meta.json`). This is exactly the machinery a STOP check
  needs.
- There is currently no STOP/SKIP/ABORT concept anywhere; the only reserved cross-agent name is `agents`
  (`output_variable_context.py:14`). Workflow steps have control variables like `_chdir` (see
  `sdd/research/202603/xprompt_special_output_variables.md`) — precedent for "magic" variable conventions.

### 3. `%wait` runtime: markers + chop

- The spawned agent process blocks itself before executing its prompt. `wait_for_dependencies()`
  (`src/sase/axe/run_agent_wait.py:52`) writes `waiting.json` into its own artifacts dir, then polls every 2s (24h
  max, then proceeds anyway) for a `ready.json`, checking `was_killed()` each tick.
- A lumberjack chop, `src/sase/scripts/sase_chop_wait_checks.py`, scans all `waiting.json` markers and writes
  `ready.json` (payload: just `{"resolved_deps": waiting_for}`, `:364`) when every awaited dependency resolves. The
  critical predicate: a dependency resolves only when its newest `done.json` has `outcome == "completed"`
  (`_SUCCESS_OUTCOME` at `:23`, `is_resolved()` at `:159-173`). `failed` and `killed` never resolve.
- After the wait, the runner proceeds (`src/sase/axe/run_agent_runner.py:306-388`): resolves wait chats (`:317`),
  claims a deferred workspace if applicable (`:321-344`), builds the output-variable context from waited producers
  (`:358-361`), and runs the prompt (`run_execution_loop`, `:388`). The runner also has an existing
  `suppress_completion_notification` flag (`:165`, `:431`, `:546`) the stop path can reuse.
- Terminal outcomes written to `done.json` (via `src/sase/axe/run_agent_markers.py:54-106`): `completed`, `failed`,
  `killed`, `noop`, `plan_rejected`. The TUI maps these in `src/sase/ace/tui/models/_loaders/_done_loaders.py`
  (filesystem path at `:110-130`, Rust-wire snapshot path at `:261-275`): `noop` hides the entry, `failed` → FAILED,
  `plan_rejected` → PLAN REJECTED, else DONE.

### 4. Contrast: workflow YAML `repeat:` loops

YAML workflow `repeat:` loops are a different mechanism: they run inside one `WorkflowExecutor` process and already
have a first-class `until:` condition checked after every iteration
(`src/sase/xprompt/workflow_executor_loops.py:324-371`). The new `STOP` convention is needed for `%repeat`/`%r`
specifically, because those future iterations are already-spawned, separately parked agents.

### Key consequence

The producer that calls `sase var set STOP=1` finishes **normally** (`outcome: "completed"`), so the chop resolves
its waiter as usual. The natural interception point is therefore **in the waiter, right after it wakes** — the
predecessor's `agent_meta.json` is final and stable at that moment (the chop only fires after `done.json` exists),
and the existing output-variable resolution code already knows how to find and read it.

## Design Options Considered

### Option A — Post-wake STOP check in the agent runner (RECOMMENDED)

After `wait_for_dependencies()` returns, and only when the agent is a repeat-chain member (iteration ≥ 2), read the
chain predecessor's `output_variables`. If `STOP` is truthy: propagate `STOP` into the agent's own
`output_variables`, write `done.json` with `outcome: "completed"` plus `repeat_stopped: true` and
`stopped_by: <producer>`, and exit 0 without claiming a workspace or executing the prompt.

- **Pros:** No changes to generic `%wait` semantics, the chop, `waiting.json`/`ready.json` schemas, or
  `wait_for_dependencies()`'s signature; cascade falls out of the existing resolved-on-completed rule; all needed
  primitives exist (`resolve_resume_agent_name`, `set_agent_output_variables`, the marker writers); the check runs
  before the deferred-workspace claim, so stopped iterations never consume a workspace; ownership stays clean
  (`sase var set` writes only current-agent metadata, the chop only resolves barriers, the waiting runner owns its
  own marker lifecycle and exit).
- **Cons:** Cascade is sequential — each downstream iteration needs one chop cycle + ≤2s poll to wind down, so a
  `%r:10` chain stopped at iteration 1 takes ~8 chop cycles to fully drain (see Phase 3 fast-path if that ever
  matters); stopped iterations display as plain DONE until Phase 2 lands.

### Option B — Chop-side detection (`ready.json` stop payload)

Persist repeat metadata (`repeat_previous_name` etc.) into `waiting.json`; extend the chop's dependency index to
carry output variables; when the repeat predecessor resolves with truthy `STOP`, write `ready.json` with
`{"repeat_stop": true, "repeat_stop_source": ..., "repeat_stop_value": ...}`; change `wait_for_dependencies()` to
return a `WaitResult` so the runner can act on the payload and self-finalize.

This was the recommendation of one research pass, and it shares Option A's end state (the waiter self-finalizes as a
successful skipped slot). Rejected on consolidation: the chop is generic `%wait` infrastructure with no repeat
awareness today, and this variant adds schema surface to `waiting.json`, `ready.json`, and the chop's index plus a
signature change to `wait_for_dependencies()` — all to move a decision the runner can make itself with one env var.
The logic also ends up split across the chop *and* the runner, since the runner must still act on the flag.

### Option C — New terminal outcome `"stopped"`

Most explicit domain modeling, but it touches every consumer of `outcome` (chop resolution, both TUI done-loader
paths, `status_buckets.py`, episodes/importance code, `agents/cli_show.py`, name-registry lookup, and the `sase-core`
done-record wire). Worst, it makes generic `%wait` semantics ambiguous: should a non-repeat consumer waiting on a
"stopped" producer proceed or block? Keeping the outcome `completed` sidesteps the question entirely.

### Option D — Kill-based fan-out

Write user-kill intents (`src/sase/agent/user_kill.py`) for all downstream siblings; their wait loops already poll
`was_killed()`. Immediate teardown (~2s), but it conflates a successful control-flow signal with the kill machinery:
downstream agents exit `128+15` with killed-style outcomes and KILLED-looking history, and the var handler would need
to resolve sibling artifact dirs at `set` time. Bad UX and semantics for what is a successful early termination.

### Rejected outright

- **Blocking `ready.json` for downstream slots:** "breaks" the loop by leaving waiting agents parked (until the 24h
  timeout makes them proceed anyway — worse). Stale active work in the TUI, manual cleanup.
- **Chop writes `done.json` for downstream waiters:** duplicates runner finalization, races with the live waiting
  process, and still needs a signal to stop the poll loop.
- **Converting `%repeat` to a true loop** (spawn k+1 only after k finishes without STOP): solves this "for free" but
  changes the feature's architecture and UX — all N agents currently appear in the TUI immediately, names/timestamps
  are reserved as a batch, and the Rust core plans all slots upfront. Far too invasive.

## Recommended Solution (Option A, detailed)

### Semantics

- Reserved variable name: `STOP` (exact, case-sensitive; valid under the existing key regex). Canonical usage:
  `sase var set STOP=1`.
- Truthiness is conservative: falsy values are `""`, `"0"`, `"false"`, `"no"`, `"off"` (case-insensitive); anything
  else is truthy. This makes `STOP=0` a safe no-op for templated prompts that compute the value.
- Scope: STOP only affects **repeat-chain waits**. Ordinary `%wait` consumers, multi-agent `---` segments, and `%alt`
  fan-outs are unaffected — for them `STOP` remains a plain user variable readable as `agents["name"].STOP`.
- A stopped iteration is a *successful* terminal state: `outcome: "completed"`, exit code 0, marked with
  `repeat_stopped: true` and `stopped_by: <name>` in `done.json`, with the completion notification suppressed.

### Phase 1 — Core behavior (pure Python)

1. **Pass the predecessor name explicitly.** Add `prev_name: str | None` to `RepeatAgentSpec`
   (`repeat_launcher.py:50-58`; populated at `:142-155` as `names[k - 2]` for k > 1, `None` for k = 1) and a new
   `REPEAT_PREV_NAME_ENV = "SASE_REPEAT_PREV_NAME"` constant. Inject it alongside the existing three env vars at
   **both** launch surfaces: TUI `_slot_env` (`_launch_repeat.py:129-134`) and CLI/cwd `_spawn_repeat_slot`
   (`launch_cwd.py:347-352`). Deriving the predecessor from `SASE_REPEAT_NAME` string surgery would be fragile — the
   `allocate_resume_names`/`allocate_wait_names` paths (`repeat_launcher.py:123-140`) don't guarantee a simple
   `base.k` shape — and an explicit env var also keeps the check independent of user-supplied `%wait:<other>`
   directives mixed into the prompt. Optionally persist `repeat_name`/`repeat_iteration`/`repeat_total`/
   `repeat_prev_name` into `agent_meta.json` for debugging and TUI display.

2. **New helper module**, e.g. `src/sase/axe/run_agent_repeat_stop.py`:
   - `is_stop_value(value: str) -> bool` — the truthiness rule above.
   - `check_repeat_stop() -> tuple[str, str] | None` — returns `(producer_name, stop_value)` when
     `SASE_REPEAT_PREV_NAME` is set and that agent's `output_variables["STOP"]` is truthy. Resolve the producer the
     same way `_resolve_waited_agent()` does (`output_variable_context.py:180-197`); export a small public helper
     from that module (e.g. `read_waited_agent_output_variables(name)`) rather than duplicating the resolution
     logic.

3. **Hook in the runner** (`run_agent_runner.py`, immediately after `wait_for_dependencies()` returns at `:307-315`
   and **before** the deferred-workspace claim at `:321`). If `check_repeat_stop()` fires:
   1. `set_agent_output_variables(artifacts_dir, {"STOP": <propagated value>})` — write **before** `done.json` so
      the next waiter (which can only wake after `done.json` exists) always sees the propagated value. Optional
      metadata keys like `STOP_SOURCE` are nice-to-have, not required for the loop break.
   2. Write the done marker via the existing writer (`run_agent_markers.py`) with `outcome="completed"` and new
      optional kwargs `repeat_stopped=True`, `stopped_by=<producer>`.
   3. Set `suppress_completion_notification = True` (existing flag, `run_agent_runner.py:165`), log a clear line
      (`Repeat chain stopped by <producer> (STOP=<value>); skipping execution`), update the artifact index, and
      return success — skipping wait chats, workspace claim, output-variable Jinja rendering, and
      `run_execution_loop()`.
   - Cascade: iteration k sets STOP → the chop resolves k's completed outcome and wakes k+1 → k+1 detects STOP,
     propagates, completes-as-stopped → the chop wakes k+2 → … The chain drains one chop cycle per link with zero
     chop modifications, and every slot reaches a terminal state (nothing is left parked).

4. **Docs + skill contract** (same change set):
   - `docs/xprompt.md` repeat section (`~:1143-1177`) and the cross-agent output variables section: document STOP
     semantics, truthiness, and cascade latency.
   - `docs/configuration.md` `sase var` section.
   - `src/sase/xprompts/skills/sase_var.md`: document the reserved `STOP` variable. Skill files are **generated** —
     after editing the source, run `sase init-skills --force` then deploy (per `memory/long/generated_skills.md`).
   - No new CLI surface is needed (reuses `sase var set`), so `memory/long/cli_rules.md` is not triggered. If a
     convenience `sase var stop` subcommand is ever added, consult that memory first (long+short options, etc.).

   Suggested user-facing wording: *"Inside a `%repeat`/`%r` iteration, an agent can stop the remaining repeat slots
   by running `sase var set STOP=1` before it completes. STOP only affects the repeat-generated predecessor wait;
   ordinary agents that wait on this producer can still read `agents["name"].STOP` like any other output variable."*

### Phase 2 — TUI visibility (optional polish)

Map `repeat_stopped: true` in `done.json` to a distinct status (suggest `DONE (STOPPED)`, keeping it in the DONE
bucket of `src/sase/agent/status_buckets.py`) in **both** done-loader paths (`_done_loaders.py:110-130` filesystem,
`:261-275` wire snapshot). The wire path reads a Rust-backed done record, so the new field must be added to the done
wire struct in `../sase-core/crates/sase_core` and its Python binding (per
`memory/short/rust_core_backend_boundary.md`). This is the only Rust-core touch in the whole feature and is why it is
split into its own phase — Phase 1 is fully functional without it (stopped iterations show as DONE, and the
propagated `STOP` is already visible in the prompt panel's OUTPUT VARIABLES section).

### Phase 3 — Fast-path cascade (optional, only if drain latency matters)

For long chains, the one-chop-cycle-per-link drain can be collapsed: when an agent detects STOP, resolve all
downstream sibling names and write a `repeat_stop.json` marker into each of their artifact dirs, and give the wait
poll loop a third check (`ready.json` | killed | `repeat_stop.json`). Cross-dir marker writes have precedent (the
chop writes `ready.json` into other agents' dirs). Defer until the simple cascade proves too slow in practice — it
adds sibling resolution and a new marker lifecycle for a latency win that may not matter at typical chop cadence and
chain lengths.

## Edge Cases

- **Producer retried/resumed:** both the chop and `resolve_resume_agent_name()` resolve to the newest run for a
  name, so the STOP check sees the same producer generation the wait resolution did.
- **User-supplied `%wait` mixed with repeat:** the check consults only `SASE_REPEAT_PREV_NAME`, so unrelated waits
  can't trigger or mask a stop. If an unrelated waited agent has `STOP=1` but the repeat predecessor does not, the
  slot runs normally after both dependencies resolve.
- **`%repeat:1` / iteration 1:** no predecessor, env unset, check is a no-op by construction.
- **STOP set by a non-repeat agent:** inert — nothing reads it specially outside the repeat-chain check.
- **Failed/killed/malformed predecessor:** never treated as STOP; existing wait semantics (block until resolution or
  the 24h timeout) are unchanged.
- **Write-order race:** propagating STOP into `output_variables` *before* writing `done.json` guarantees the next
  waiter always sees the propagated value.

## Tests To Add

- `tests/test_repeat_launcher.py`: `prev_name` populated for k > 1, `None` for k = 1.
- `tests/test_agent_launch_repeat.py` (TUI) and the CLI/cwd repeat test: `SASE_REPEAT_PREV_NAME` injected alongside
  the existing `SASE_REPEAT_*` assertions at both surfaces.
- New `tests/test_run_agent_repeat_stop.py`: truthiness table (`STOP=0`/`false`/`no`/`off` are no-ops); no-op when
  `SASE_REPEAT_PREV_NAME` unset or producer has no vars; stop path writes vars-then-done ordering; `stopped_by`
  recorded; deferred workspace never claimed; completion notification suppressed.
- Runner test near `tests/test_axe_run_agent_runner_deferred_workspace.py`: repeat STOP exits before deferred
  workspace claim and before `run_execution_loop()`.
- Chain-cascade integration test in the style of `tests/test_axe_chop_wait_checks.py`: producer completed with
  STOP → waiter resolves (chop unchanged) → stopped waiter's `done.json` resolves the next link; an unrelated waited
  dependency with STOP does not stop the slot.
- Phase 2: TUI display tests next to `tests/ace/tui/widgets/test_agent_display_output_variables.py` and done-loader
  tests for both load paths.

## Open Questions

1. **Display treatment (Phase 2):** `DONE (STOPPED)` vs. a first-class `STOPPED` status — the former keeps
   status-bucket logic untouched; recommend it.
2. **Should generic `%wait` consumers ever honor STOP?** Recommend no for now — surprising action at a distance;
   revisit if a real use case appears.
3. **Convenience syntax:** a `sase var stop` subcommand or a `%stop_on:<var>` directive could layer on later; both
   are additive and out of scope for v1.
