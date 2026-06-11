# STOP Output Variable: Breaking `%r`/`%repeat` Chains

Research into adding a reserved `STOP` output variable (set via `sase var set STOP=1`) that breaks the sequential
agent chain created by the `%r`/`%repeat` directive.

Date: 2026-06-11

---

## TL;DR

`%repeat:N` is **not a runtime loop** — it is a launch-time fan-out: all N agents are spawned upfront, and iterations
2..N each get a `%wait:<predecessor>` directive prepended so they block until the prior iteration completes.
"Breaking the loop" therefore means: **when an iteration sets `STOP`, every already-spawned downstream iteration must
detect it when it wakes and exit early instead of running its prompt.**

**Recommended solution (Option A below):** after `wait_for_dependencies()` returns in the agent runner, a repeat-chain
member checks its predecessor's `output_variables` for a truthy `STOP`. If found, it propagates `STOP` into its own
`output_variables`, writes a normal `done.json` with `outcome: "completed"` plus a `repeat_stopped: true` field, and
exits before claiming a workspace or executing its prompt. Because the stopped iteration still reports
`outcome: "completed"`, the existing wait-resolution chop resolves the next waiter unchanged, and the stop cascades
down the chain with zero changes to the generic `%wait` machinery.

---

## How the Relevant Subsystems Work Today

### 1. `%repeat` is a fan-out, not a loop

- Parsing: `src/sase/xprompt/directives.py:426-444` parses `%repeat:N` / `%r:N` (also paren forms) into
  `PromptDirectives.repeat_count` (`src/sase/xprompt/_directive_types.py:77`). The `r` alias is declared at
  `_directive_types.py:47`.
- Fan-out: `launch_agents_from_cwd()` (`src/sase/agent/launch_cwd.py:308-366`) detects the repeat directive and spawns
  N independent agents via `spawn_repeat_batch()` (`src/sase/agent/repeat_launcher.py:84-171`). The Rust core binding
  `plan_agent_launch_fanout()` (`src/sase/core/agent_launch_facade.py:136-145`) produces the deterministic slot plan,
  but the loop/chain runtime is pure Python.
- Chaining: `repeat_launcher.py:142-155` builds each slot's prompt. Iteration 1 gets `%n:<base>.1`; iteration k > 1
  gets `%n:<base>.k\n%wait:<base>.(k-1)` prepended. So sequencing is coordinated entirely through the generic `%wait`
  mechanism, not by the launcher.
- Per-slot env vars (`repeat_launcher.py:45-47`, injected in `launch_cwd.py`):
  `SASE_REPEAT_NAME` (the slot's own name), `SASE_REPEAT_ITERATION` (1-based), `SASE_REPEAT_TOTAL`.
- There is **no chain/group ID** and **no existing early-exit mechanism**. Today a chain only stops early if an
  iteration fails (its waiter then blocks until the 24h timeout) or the user kills agents in the TUI.

### 2. `sase var` output variables

- Skill source: `src/sase/xprompts/skills/sase_var.md` → agents run `sase var set KEY=VALUE ...`.
- CLI: `src/sase/main/parser_var.py`, handler `src/sase/main/var_handler.py:18-71` (requires `SASE_AGENT=1` and
  `SASE_ARTIFACTS_DIR`).
- Storage: `src/sase/core/agent_output_variables.py:44-66` merges keys into the `output_variables` dict in the agent's
  `agent_meta.json`, with fcntl locking + atomic rename. Keys match `[A-Za-z_][A-Za-z0-9_]*`; values are strings.
  `STOP` is a valid key today — it just has no special meaning.
- Consumption: `src/sase/agent/output_variable_context.py` builds the reserved Jinja `agents` namespace for downstream
  agents, resolving waited producers via `_resolve_waited_agent()` (`output_variable_context.py:180-197`), which uses
  `resolve_resume_agent_name()` + the producer's `agent_meta.json`. This is exactly the machinery a STOP check needs.
- Precedent for "magic" variables: the only reserved cross-agent name is `agents` (`output_variable_context.py:14`).
  Within workflow steps there are control variables like `_chdir` (consumed by the executor and popped from output —
  see `sdd/research/202603/xprompt_special_output_variables.md`). There is currently **no STOP/SKIP/ABORT concept
  anywhere**.

### 3. `%wait` runtime: markers + chop

- The spawned agent process itself blocks before executing its prompt. `wait_for_dependencies()`
  (`src/sase/axe/run_agent_wait.py:52-211`) writes `waiting.json` into its own artifacts dir, then polls every 2s
  (24h max) for a `ready.json` to appear (`run_agent_wait.py:101-111`), checking `was_killed()` each tick.
- A lumberjack chop, `src/sase/scripts/sase_chop_wait_checks.py`, scans all `waiting.json` markers and writes
  `ready.json` when every awaited dependency is resolved. The critical predicate: a named dependency resolves only
  when its newest `done.json` has `outcome == "completed"` (`sase_chop_wait_checks.py:23,199-208` and
  `is_resolved()` at `:159-173`). `failed` and `killed` outcomes never resolve — the waiter just keeps waiting.
- After the wait, the runner proceeds (`src/sase/axe/run_agent_runner.py:294-388`): resolves wait chats, claims a
  deferred workspace if applicable (`run_agent_runner.py:321-344`), builds the output-variable context from the waited
  producers (`:358-361`), and runs the prompt.
- Terminal outcomes written to `done.json` (via `src/sase/axe/run_agent_markers.py:76-113`): `completed`, `failed`,
  `killed`, `noop`, `plan_rejected`. The TUI maps these in
  `src/sase/ace/tui/models/_loaders/_done_loaders.py:110-130` (and again at `:260-277` for the Rust-wire snapshot
  path): `noop` hides the entry, `failed` → FAILED, `plan_rejected` → PLAN REJECTED, else DONE.

### Key consequence

The producer that calls `sase var set STOP=1` finishes **normally** (`outcome: "completed"`), so the chop will resolve
its waiter as usual. The natural interception point is therefore **in the waiter, right after it wakes** — the
predecessor's `agent_meta.json` is final and stable at that moment (the chop only fires after `done.json` exists), and
the existing output-variable resolution code already knows how to find and read it.

---

## Design Options Considered

### Option A — Post-wake STOP check in the agent runner (RECOMMENDED)

After `wait_for_dependencies()` returns, and only when the agent is a repeat-chain member (iteration ≥ 2), read the
chain predecessor's `output_variables`. If `STOP` is truthy:

1. Propagate `STOP` into the stopping agent's own `output_variables` (so the *next* iteration sees it and the stop
   cascades down the chain).
2. Write `done.json` with `outcome: "completed"` plus `repeat_stopped: true` (and `stopped_by: <producer-name>`).
3. Exit 0 without claiming a deferred workspace or executing the prompt.

- **Pros:** No changes to the generic `%wait` semantics or the chop; cascade falls out of the existing
  resolved-on-completed rule; all needed primitives exist (`resolve_resume_agent_name`,
  `set_agent_output_variables`, marker writers); check runs *before* deferred-workspace claim, so stopped iterations
  never consume a workspace; pure Python, consistent with the rest of the wait runtime.
- **Cons:** Cascade is sequential — each downstream iteration needs one chop cycle + ≤2s poll to wind down, so a
  `%r:10` chain stopped at iteration 1 takes ~8 chop cycles to fully drain (see "fast-path" extension below);
  stopped iterations display as DONE until the TUI learns about `repeat_stopped` (phase 2).

### Option B — Chop-side detection

Teach `sase_chop_wait_checks.py` to inspect resolved dependencies' `output_variables` and write a stop signal (e.g.
`ready.json` with `{"stop": true}`); the waiter checks the flag after waking.

- **Pros:** Centralizes the decision where dependency state is already being read.
- **Cons:** The chop is generic `%wait` infrastructure with no repeat awareness; `waiting.json` would need new
  repeat-chain fields so the chop can tell a repeat link from an ordinary `%wait` handoff; logic is split across the
  chop *and* the waiter (the waiter must still act on the flag); more schema surface for no functional gain over A.

### Option C — New terminal outcome `"stopped"`

Stopped iterations write `outcome: "stopped"`, and the chop's resolution predicate is extended to treat `stopped` as
resolved (for repeat waiters only? for everyone?).

- **Pros:** Most explicit domain modeling; status display falls out naturally.
- **Cons:** Touches every consumer of `outcome` (chop resolution, TUI done-loaders for both filesystem and Rust-wire
  paths, `status_buckets.py`, episodes/importance code, `agents/cli_show.py`, name-registry lookup, the `sase-core`
  done-record wire). Worst, it makes generic `%wait` semantics ambiguous: should a non-repeat consumer waiting on a
  stopped producer proceed or block? Option A sidesteps the question entirely by keeping the outcome `completed`.

### Option D — Kill-based fan-out

When `sase var set STOP=1` runs (or a chop notices it), write user-kill intents
(`src/sase/agent/user_kill.py`) for all downstream siblings; their wait loops already poll `was_killed()`.

- **Pros:** Immediate chain teardown (~2s), no new wake-time logic.
- **Cons:** Conflates a logical, expected control-flow signal with the kill machinery: downstream agents exit
  `128+15` with `killed`-style outcomes and KILLED-looking history, kill intents were designed for human action, and
  the var handler would need to resolve sibling artifact dirs at `set` time. Bad UX and semantics for what is a
  successful early termination.

### Rejected: converting `%repeat` to a true loop

Spawning iteration k+1 only after k finishes without STOP would solve this "for free" but changes the whole feature's
architecture and UX (all N agents currently appear in the TUI immediately, names/timestamps are reserved as a batch,
`LaunchFanoutPlanWire` in the Rust core plans all slots upfront). Far too invasive for this feature.

---

## Recommended Solution (Option A, detailed)

### Semantics

- Reserved variable name: `STOP` (exact, case-sensitive — consistent with the all-caps style of a control flag and
  valid under the existing key regex). Canonical usage: `sase var set STOP=1`.
- Truthiness: falsy values are `""`, `"0"`, `"false"`, `"no"`, `"off"` (case-insensitive); anything else is truthy.
  This makes `STOP=0` a safe no-op for templated prompts that compute the value.
- Scope: STOP only affects **repeat-chain waits**. Ordinary `%wait` consumers, multi-agent `---` segments, and `%alt`
  fan-outs are unaffected — for them `STOP` remains a plain user variable. (Extending to other contexts can be a
  follow-up; see Open Questions.)
- A stopped iteration is a *successful* terminal state: `outcome: "completed"`, exit code 0, marked with
  `repeat_stopped: true` and `stopped_by: <name>` in `done.json`.

### Phase 1 — Core behavior

1. **Pass the predecessor name explicitly.** Add `prev_name: str | None` to `RepeatAgentSpec`
   (`src/sase/agent/repeat_launcher.py:50-58`, populated at `:142-155` as `names[k - 2]` for k > 1) and a new
   `REPEAT_PREV_NAME_ENV = "SASE_REPEAT_PREV_NAME"` env var injected alongside the existing three in
   `_spawn_repeat_slot()` (`src/sase/agent/launch_cwd.py:~330-350`). Deriving the predecessor from
   `SASE_REPEAT_NAME` string surgery would be fragile (the `allocate_resume_names`/`allocate_wait_names` paths at
   `repeat_launcher.py:123-140` don't guarantee a simple `base.k` shape); an explicit env var is unambiguous and also
   keeps the check independent of any user-supplied `%wait:<other>` directives mixed into the prompt.

2. **New helper module**, e.g. `src/sase/axe/run_agent_repeat_stop.py`:
   - `is_stop_value(value: str) -> bool` — the truthiness rule above.
   - `check_repeat_stop() -> str | None` — returns the stopping producer's name when `SASE_REPEAT_PREV_NAME` is set
     and that agent's `output_variables["STOP"]` is truthy. Resolve the producer the same way
     `_resolve_waited_agent()` does (`src/sase/agent/output_variable_context.py:180-197`); export a small public
     helper from that module (e.g. `read_waited_agent_output_variables(name)`) rather than duplicating the
     resolution logic.

3. **Hook in the runner** (`src/sase/axe/run_agent_runner.py`, immediately after `wait_for_dependencies()` returns at
   `:307-315` and **before** the deferred-workspace claim at `:321`):
   - If `check_repeat_stop()` returns a producer name:
     a. `set_agent_output_variables(artifacts_dir, {"STOP": <propagated value>})` — write **before** `done.json`
        so the next waiter can never wake (the chop keys off `done.json`) and observe missing variables.
     b. Write the done marker via the existing writer (`src/sase/axe/run_agent_markers.py:76+`) with
        `outcome="completed"` and new optional kwargs `repeat_stopped=True`, `stopped_by=<producer>`.
     c. Log a clear line (`Repeat chain stopped by <producer> (STOP=<value>); skipping execution`), update the
        artifact index, and return success without running the prompt.
   - Cascade: iteration k sets STOP → k+1 wakes (chop resolves k's completed outcome), detects STOP, propagates, and
     completes-as-stopped → chop resolves k+1 → k+2 repeats the pattern → … The chain drains one chop cycle per link
     with **zero** chop modifications.

4. **Docs + skill contract** (same change set):
   - `docs/xprompt.md` repeat section (`~:1141-1177`): document STOP semantics, truthiness, and cascade latency.
   - `src/sase/xprompts/skills/sase_var.md`: document the reserved `STOP` variable. Skill files are **generated** —
     after editing the source, run `sase init-skills --force` then `chezmoi apply` (per
     `memory/long/generated_skills.md`). No `sase commit` CLI arguments change, but the skill/CLI contract rule
     applies: update the skill doc and its tests in the same turn as the behavior.
   - No new CLI surface is needed (reuses `sase var set`), so `memory/long/cli_rules.md` is not triggered. If a
     convenience `sase var stop` subcommand is ever added, consult that memory first (long+short options, etc.).

### Phase 2 — TUI visibility (optional polish)

- Map `repeat_stopped: true` in `done.json` to a distinct status (suggest `DONE (STOPPED)`, keeping it in the DONE
  bucket of `src/sase/agent/status_buckets.py`) in **both** done-loader paths:
  `src/sase/ace/tui/models/_loaders/_done_loaders.py:110-130` (filesystem) and `:260-277` (wire snapshot).
- The wire path reads a Rust-backed done record, so the new field must be added to the done wire struct in
  `../sase-core/crates/sase_core` and its Python binding (per `memory/short/rust_core_backend_boundary.md`, via
  `sase workspace open -p sase-core <workspace_num>`). This is the only Rust-core touch in the whole feature and is
  why it is split into its own phase — Phase 1 is fully functional without it (stopped iterations show as DONE, and
  the propagated `STOP` is already visible in the prompt panel's OUTPUT VARIABLES section via
  `_agent_display_parts.py:79-99`).

### Phase 3 — Fast-path cascade (optional, only if drain latency matters)

For long chains, the one-chop-cycle-per-link drain can be collapsed: when an agent detects STOP, it can resolve all
downstream sibling names and write a `repeat_stop.json` marker into each of their artifact dirs, and the wait poll
loop (`run_agent_wait.py:101-111`) gains a third check (`ready.json` | killed | `repeat_stop.json`). Cross-dir marker
writes have precedent (the chop writes `ready.json` into other agents' dirs; the TUI wait-override in
`_wait_resume.py` does too). Defer this until the simple cascade proves too slow in practice — it adds sibling
resolution and a new marker lifecycle for a latency win that may not matter at typical chop cadence and chain lengths.

### Testing plan

- `tests/test_repeat_launcher.py`: `prev_name` populated for k > 1, `None` for k = 1; env injection asserted in
  `tests/test_agent_launch_repeat.py` (alongside the existing `SASE_REPEAT_*` assertions).
- New `tests/test_run_agent_repeat_stop.py`: truthiness table; no-op when `SASE_REPEAT_PREV_NAME` unset / producer has
  no vars / STOP falsy; stop path writes vars-then-done ordering; `stopped_by` recorded; deferred workspace never
  claimed on stop.
- Chain-cascade integration test in the style of `tests/test_axe_chop_wait_checks.py`: producer completed with
  STOP → waiter resolves (chop unchanged) → stopped waiter's `done.json` resolves the next link.
- Phase 2: TUI display tests next to `tests/ace/tui/widgets/test_agent_display_output_variables.py` and done-loader
  tests for both load paths.

### Edge cases

- **Producer retried/resumed:** both the chop (`sase_chop_wait_checks.py:73-75`, newest-timestamp wins) and
  `resolve_resume_agent_name()` resolve to the newest run for a name, so the STOP check sees the same producer
  generation the wait resolution did.
- **User-supplied `%wait` mixed with repeat:** the check consults only `SASE_REPEAT_PREV_NAME`, so unrelated waits
  can't trigger or mask a stop.
- **`%repeat:1` / iteration 1:** no predecessor, env unset, check is a no-op by construction.
- **STOP set by a non-repeat agent:** inert — nothing reads it specially outside the repeat-chain check.
- **Write-order race:** propagating STOP into `output_variables` *before* writing `done.json` guarantees the next
  waiter (which can only wake after `done.json` exists) always sees the propagated value.

---

## Open Questions

1. **Display treatment (Phase 2):** `DONE (STOPPED)` vs. a first-class `STOPPED` status — the former keeps
   status-bucket logic untouched; recommend it.
2. **Should generic `%wait` consumers ever honor STOP?** e.g. a named producer sets STOP and an unrelated
   `%wait:<producer>` consumer skips itself. Recommend no for now — surprising at a distance; revisit if a real use
   case appears.
3. **Convenience syntax:** a `sase var stop` subcommand or a `%stop_on:<var>` directive could layer on later; both are
   additive and out of scope for v1.
