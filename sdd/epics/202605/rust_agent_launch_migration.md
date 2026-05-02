---
create_time: 2026-05-01 12:13:46
bead_id: sase-1r
status: done
prompt: sdd/prompts/202605/rust_agent_launch_migration.md
---
# Rust-backed agent launch migration

## Question answered

Yes. The parts of agent launch that would benefit most from moving from Python into `../sase-core` are the
deterministic, pre-runtime pieces:

- RUNNING-field workspace allocation, claim, and transfer logic in `src/sase/running_field/_workspace.py` and
  `src/sase/running_field/_operations.py`.
- Low-level launch preparation in `src/sase/agent/launcher.py`: prompt temp-file creation, output path derivation, env
  shaping, subprocess spawning, and post-spawn workspace claim/kill-on-failure behavior.
- Fan-out planning in `src/sase/agent/multi_prompt_launcher.py`, `src/sase/agent/repeat_launcher.py`,
  `src/sase/xprompt/_directive_alt.py`, and the TUI launch mixins. This includes deterministic parsing of `%model`,
  `%alt`, `%r`, `%wait`, multi-prompt separators, local-xprompt serialization metadata, unique timestamp allocation, and
  the current one-second sleeps between spawned agents.

The parts that should not move first are the Textual UI handlers, Python plugin hooks for VCS/workspace providers, and
the actual agent runner/provider execution (`run_agent_runner.py`, Claude/Gemini/Codex provider code). Those remain
host/application logic. Rust should own the stable, deterministic backend contract that can be called from the TUI/CLI
without duplicating parsing and mutation logic.

## Current launch shape

The single-agent TUI path already avoids blocking the Textual event loop by sending `_run_agent_launch_body()` through
`asyncio.to_thread()`, but that worker still performs a long Python preflight before the agent appears:

- Parse multi-prompt/frontmatter and possibly expand multi-agent xprompts.
- Resolve VCS refs, history, MRU, file references, workflow dispatch, `%wait`, `%model`, and `%r`.
- Allocate workspace number by reading/parsing the RUNNING field.
- Resolve workspace directory and clean non-main workspaces through provider/Python code.
- Spawn a Python subprocess and then claim the workspace in the ProjectSpec file.

The multi-agent paths are worse for total launch latency:

- Multi-model TUI launch sleeps one second between subagents.
- Repeat launch sleeps one second between subagents.
- Multi-prompt launch may poll `agent_meta.json` for up to 30 seconds between segments so bare `%wait` can resolve to
  the previous agent's eventual name.
- TUI and CLI launch paths duplicate similar logic, so behavior fixes tend to land in one path first.

This explains why TUI interaction may unblock quickly after prior fixes, while the agents still appear slowly and launch
bursts feel sluggish.

## Migration principles

- Keep Rust bindings as required, strict `sase_core_rs` facades, matching the existing `sase.core.rust` pattern.
- Move stable wire contracts first, then callers. Avoid Python fallback for newly ported production facades.
- Use Rust for pure parsing/planning and deterministic file-content mutations. Let Python keep plugin calls, Textual
  scheduling, and provider/runtime execution.
- Prefer one shared launch planner/executor used by both TUI and CLI over separate Python launch branches.
- Preserve all runtime-neutral behavior: Claude, Gemini, Codex, and plugin providers must use the same launch path.
- Each phase below should be assigned to one distinct agent instance and should leave the repo in a shippable state.

## Phase 1: Baseline and launch wire contract

Goal: make launch latency measurable and define the wire boundary before porting behavior.

Work:

- Add focused timing around TUI launch stages: prompt parsing, multi-agent xprompt expansion, VCS resolution, history
  writes, workspace allocation, workspace directory resolution/clean, low-level spawn, workspace claim, fan-out sleeps,
  and multi-prompt naming wait.
- Add a small perf harness that can run launch planning/spawn with fake subprocesses and temp ProjectSpec files, so
  later phases can prove regressions without starting real LLM CLIs.
- Introduce launch wire dataclasses on the Python side only, for example:
  - `AgentLaunchRequestWire`
  - `AgentLaunchPreparedWire`
  - `WorkspaceClaimRequestWire`
  - `WorkspaceClaimOutcomeWire`
  - `LaunchFanoutPlanWire`
- Mirror those wire shapes as empty/skeleton Rust structs in `../sase-core` with serde tests, but do not call them from
  production yet.

Likely files:

- `src/sase/core/agent_launch_wire.py`
- `src/sase/core/agent_launch_facade.py`
- `tests/test_core_agent_launch*.py`
- `tests/perf/bench_agent_launch*.py`
- `../sase-core/crates/sase_core/src/agent_launch/`
- `../sase-core/crates/sase_core_py/src/lib.rs`

Definition of done:

- Baseline numbers exist for plain prompt, VCS prompt, `%model` fan-out, `%r` fan-out, multi-prompt, and `%wait`.
- No production launch behavior changes.
- `just install && just check` passes in `sase`; `cargo test --workspace` passes in `../sase-core`.

## Phase 2: Rust-backed RUNNING-field allocation and claim planning

Goal: eliminate the Python read/parse/scan/mutate path for launch claims and make allocation plus claim a single
contract.

Work:

- In `../sase-core`, implement RUNNING-field claim parsing and content mutation using the existing ProjectSpec parsing
  conventions.
- Add Rust functions for:
  - `list_workspace_claims_from_content(content)`.
  - `plan_claim_workspace_from_content(content, request)`.
  - `plan_transfer_workspace_claim_from_content(content, request)`.
  - `allocate_and_claim_workspace_from_content(content, min_workspace, max_workspace, request)`.
- In Python, update `claim_workspace()`, `transfer_workspace_claim()`, and `get_first_available_axe_workspace()` callers
  to use a facade that performs one locked read-modify-write where possible.
- Keep the actual file lock and atomic write in Python for this phase, matching the existing cleanup/status facade
  style.

Why this matters:

- Current TUI paths call `get_first_available_axe_workspace()` before `claim_workspace()`, causing two ProjectSpec reads
  and a TOCTOU retry/kill path.
- Rust can parse and mutate the RUNNING section faster and with less Python object churn.

Definition of done:

- Existing workspace claim, release, retry-transfer, and agent launch tests pass.
- New tests cover duplicate workspace rejection, deferred workspace `0`, transfer by PID, empty/missing RUNNING fields,
  and malformed claim rows.
- Launch callers can allocate and claim through one facade call without changing visible behavior.

## Phase 3: Shared low-level launch preparation facade

Goal: centralize deterministic pre-spawn launch setup while keeping Python `subprocess.Popen` for one more phase.

Work:

- Add a Rust-backed launch preparation binding that accepts `AgentLaunchRequestWire` plus host-supplied values
  (`python_executable`, `runner_script`, `sase_tmpdir`, output shard root, preallocated env prefix data).
- Return a prepared wire record with:
  - prompt temp-file path after writing prompt bytes.
  - output path.
  - sanitized safe name.
  - argv vector.
  - cwd.
  - final environment delta.
  - claim request data.
- Replace the ad hoc preparation in `spawn_agent_subprocess()` with the facade result, but leave `Popen`, kill-on-claim
  failure, home project-file creation, and chop registry recording in Python.
- Cache runner-script resolution on the Python side so launch does not repeatedly `find_spec()`.

Why this matters:

- It shrinks `spawn_agent_subprocess()` to host-only orchestration.
- It gives a stable contract for the later Rust process-spawn phase.
- It reduces repeated Python path/env/string handling on the TUI worker path.

Definition of done:

- Tests assert exact argv/env/output path/prompt-file behavior for normal, home, deferred workspace, VCS preallocation,
  local xprompt file, extra env, and managed Codex home cleanup.
- Existing launch and retry-spawn tests pass.

## Phase 4: Remove artificial fan-out sleeps with Rust batch timestamp allocation

Goal: make `%model` and `%r` launches create all child processes as fast as the machine can safely spawn them.

Work:

- Add a Rust timestamp batch allocator that preserves the current `YYmmdd_HHMMSS` visible format while guaranteeing
  uniqueness within a batch without `time.sleep(1)`.
- Use it from:
  - TUI multi-model launch.
  - TUI repeat launch.
  - CLI repeat launch.
  - multi-prompt sub-model fan-out.
- Replace the one-second sleeps in fan-out paths with unique batch timestamps and immediate spawn attempts.

Important constraint:

- Do not change the timestamp format in this phase unless every loader, artifact path, and display parser is updated.
  Prefer same-format unique allocation first, even if it means waiting only for clock rollover when absolutely required
  or using a deterministic per-batch timestamp source accepted by existing artifact naming.

Definition of done:

- A `%model(a,b,c)` launch no longer incurs two seconds of parent-side sleep.
- A `%r:5` launch no longer incurs four seconds of parent-side sleep.
- Tests prove unique workflow/artifact timestamps for batches launched within one second.

## Phase 5: Rust fan-out planning for directives and prompt segmentation

Goal: move deterministic prompt fan-out parsing to Rust and return a launch plan that both TUI and CLI can execute.

Work:

- Port the deterministic text transforms to `../sase-core`:
  - Split multi-prompt segments on `---` outside fenced blocks.
  - Detect YAML frontmatter boundaries, but keep local-xprompt object construction in Python.
  - Detect `%wait`.
  - Split `%model`, `%m`, `%alt`, and `%(` variants.
  - Parse `%r` / `%repeat` plus `%name` / `%n` enough to produce per-slot prompt specs.
- Keep full xprompt catalog loading and xprompt body expansion in Python, but call the Rust planner before/after
  expansion as needed.
- Add a Python `plan_agent_launch_fanout()` facade that returns a normalized `LaunchFanoutPlanWire`.
- Use that facade from TUI and CLI, initially behind the same public function boundaries.

Why this matters:

- The same prompt should fan out the same way from `sase ace`, `sase run -d`, bead work, and chop launches.
- Rust can do the repeated fenced-block/regex scans without Python allocation overhead.

Definition of done:

- Golden parity tests cover existing directive parser fixtures and launch fan-out cases.
- Existing TUI launch tests pass with the Rust planner.
- No behavior change for xprompt-injected `%model`; Python still expands xprompts where necessary.

## Phase 6: Preplanned names for multi-prompt `%wait`

Goal: remove most `agent_meta.json` polling between multi-prompt segments.

Work:

- Extend the launch plan to optionally reserve/declare agent names before spawning.
- For multi-prompt segments where segment `N+1` uses bare `%wait`, rewrite it to wait on the planned name of segment `N`
  instead of waiting for the runner to write `agent_meta.json`.
- Keep the old polling path only for cases where the previous segment's name cannot be known safely before launch.
- Move any reusable name-reservation read/mutate logic into Rust only after preserving existing collision semantics.

Why this matters:

- Multi-prompt launch currently blocks between segments for naming, even though many names are explicit or can be
  reserved before child startup.
- This turns sequential parent-side waiting into deterministic plan construction.

Definition of done:

- Multi-prompt chains with explicit `%name`, repeat-generated names, and planner-reserved auto names launch without
  naming polling.
- Tests cover fallback to polling for truly dynamic names.
- `%wait` behavior is unchanged from the agent's perspective.

## Phase 7: Rust process spawn binding

Goal: move the final low-level process creation into Rust, releasing the GIL and combining spawn plus claim failure
handling behind one binding.

Work:

- Add a PyO3 binding that accepts the prepared launch wire and spawns the detached process via Rust.
- Preserve current semantics:
  - `stdin=DEVNULL`
  - stdout/stderr to the output file
  - detached process group/session behavior
  - explicit cwd
  - full env map
  - child termination if the claim/transfer fails
- Keep Python responsible for determining `python_executable`, `runner_script`, plugin env-prefix mapping, and chop
  registry recording.
- Replace Python `subprocess.Popen` inside `spawn_agent_subprocess()` with the binding.

Risks:

- Cross-platform process detachment semantics are subtle. If this repo only supports Unix in practice, state that in
  tests and docs. If Windows wheels are supported for this binding, add Windows-specific process creation flags.
- Do not merge this phase until failure-mode tests prove no orphaned launched child is left after claim failure.

Definition of done:

- Spawn tests cover success, output redirection, bad cwd, claim failure cleanup, retry transfer failure cleanup, and env
  propagation.
- `spawn_agent_subprocess()` becomes a thin Python facade around Rust spawn plus Python-only side effects.

## Phase 8: Unify TUI and CLI launch execution

Goal: delete duplicated launch orchestration and make the TUI/CLI execute the same Rust-backed launch plan.

Work:

- Introduce a shared Python launch executor that accepts `LaunchFanoutPlanWire` and host callbacks:
  - UI notification/refresh callback for TUI.
  - print/log callback for CLI.
  - workspace directory resolver callback for provider-managed workspaces.
  - xprompt expansion callback.
- Route these through it:
  - `launch_agent_from_cwd()`
  - `_run_agent_launch_body()`
  - `_launch_multi_prompt_agents()`
  - `_launch_multi_model_agents()`
  - `_launch_repeat_agents()`
  - bead work and chop launch call sites that currently go through `launch_agent_from_cwd()`.
- Remove duplicated Python branches once tests prove parity.

Definition of done:

- There is one shared launch planning/execution core for CLI and TUI.
- TUI handlers mostly snapshot context, schedule work, and surface notifications.
- Existing launch fan-out tests remain green and add at least one cross-entrypoint parity test per launch shape.

## Phase 9: Cleanup, docs, and performance gate

Goal: make the migration maintainable and prevent launch latency from regressing.

Work:

- Remove dead Python helpers that were fully replaced.
- Update `docs/rust_backend.md` with agent-launch bindings, supported host/Python responsibilities, and rollback/debug
  instructions.
- Add a launch latency regression check to the existing perf artifacts or a lightweight CI-friendly benchmark.
- Add `sase core health` coverage for a representative launch binding so stale `sase_core_rs` wheels fail clearly.

Definition of done:

- Docs explain which launch parts are Rust and which remain Python.
- Benchmarks show launch planning and fan-out are faster than the Phase 1 baseline.
- `just install && just check` passes in `sase`; `cargo test --workspace` and clippy pass in `../sase-core`.

## Expected payoff

The largest user-visible win should come before the risky Rust process-spawn phase:

- Phase 2 removes Python-heavy RUNNING parsing/mutation and makes allocation plus claim atomic.
- Phase 4 removes intentional one-second sleeps for multi-model/repeat launch bursts.
- Phase 5 removes duplicated Python directive/fan-out parsing.
- Phase 6 removes most multi-prompt naming polling.

Phase 7 is worth doing only after those wins are measured. Python `subprocess.Popen` itself is unlikely to be the only
major source of launch latency; the surrounding Python preflight and intentional sleeps are currently better targets.
