---
create_time: 2026-06-21 11:53:02
status: done
prompt: sdd/prompts/202606/agy_print_no_progress_recovery.md
---
# Plan: Fix the Antigravity (`agy`) "planning-only / waiting-for-approval" false-success

## Symptom (what the user is seeing)

Agents that run on the Antigravity (`agy`) LLM provider routinely **never do the work they were asked to do**. Instead
of producing the requested deliverable, the saved reply is a list of future-tense intentions that trails off while
"waiting", e.g.:

- `037.agy` (review two plans and recommend one): "… I will view the plan proposed by `036.cdx` … I am waiting for the
  command execution to complete and show the details for both agents. **Please approve the command if you haven't
  already.**"
- `03a.agy` / `03b.agy` (same task, _after_ an earlier diagnosis): "… I will list chats matching `038.cdx` … **I will
  stop calling tools for a moment and wait for the background search command to finish and notify me with its output.**"
- `022.agy` (same task class): an entire reply of "I will … I will … I will pause to wait for the command output to
  complete." with no recommendation ever produced.

In every case SASE reports the run as **successful**: the `agy --print` subprocess exits `0`, `done.json` is written
with no error, the commit finalizer records `no_changes`, and a completion notification fires. The user gets an
unexecuted to-do list (or a "please approve" / "waiting to be notified" message) instead of an answer, with **no signal
that anything went wrong**. This reproduces on essentially every multi-step `agy` run, not intermittently.

## Root cause

This is **not** a missing permission flag, even though the user's first instinct (and an earlier fork's framing) was "it
should be running with `--dangerously-skip-permissions`." The provider already passes it:

```
agy --print-timeout <dur> --model <model> --dangerously-skip-permissions --print <prompt>
```

`--dangerously-skip-permissions` is Antigravity's auto-approve flag (the `--yolo` equivalent), it is present on every
`agy` invocation, and the native Antigravity logs for the failing runs show tool confirmations being auto-approved. The
"please approve" wording is the **model narrating a stuck state**, not a real SASE/Antigravity approval gate.

The actual defect is an **interaction between Antigravity's background-task model and `agy --print` non-interactive
mode, which SASE then accepts as success**:

1. **`agy --print` is a real single-shot agentic loop, not an interactive session.** SASE launches one `agy --print`
   process per turn, streams its plain stdout, and has no event loop attached to it.
2. **Gemini 3.5 Flash (the default `agy` model) routinely dispatches inspection commands as Antigravity _background /
   async tasks_.** Antigravity's `run_command` tool takes a `WaitMsBeforeAsync` budget; when a command is expected to
   outlive that budget, Antigravity converts it into a background task that "notifies" the agent on completion. That
   design assumes an interactive event loop is present to deliver the notification and let the model take another turn.
3. **In print mode there is no such loop.** The model fires a command as a background task, ends its turn saying it will
   "wait to be notified" / "please approve" / "pause for the output", and `agy --print` then exits `0` — because the
   model produced a final assistant message with no further tool call. The background task may even complete, but there
   is no follow-up model turn to consume its result and finish the job.
4. **SASE treats any zero-exit `agy --print` stdout as a complete, successful answer.** `AgyProvider.invoke()` returns
   whatever came back on stdout as the final `InvokeResult`. The MVP only guarded _empty_ stdout (epic
   `agy_provider_mvp.md`, Phase 2 task 10: "Do not treat empty stdout as success"); the _non-empty-but-no-work_ case — a
   fully-formed planning/“waiting” narration — was never guarded. The provider's retry config only fires on transport
   `error_patterns` (`RESOURCE_EXHAUSTED`, `print-timeout`, …); a planning-only stub exits `0` and matches none, so **no
   retry, no continuation nudge, and no error ever fire.**

**One sentence:** Antigravity's background-task model is incompatible with `agy --print`'s single-shot, no-event-loop
execution — Gemini 3.5 Flash ends turns "waiting" for background tasks that print mode can never deliver — and
`AgyProvider` accepts that unexecuted/waiting narration as a successful final answer, producing a silent false success.

There is **no Antigravity CLI flag** to disable background tasks or force synchronous commands (`WaitMsBeforeAsync` is a
model-controlled tool parameter, and `agy --help` exposes no `--output-format` / `--json` / sync-execution switch). So
the fix must combine (a) steering the model away from the background-task path and (b) a SASE-side safety net that stops
accepting "no real progress" as success.

### Why the three existing draft plans are insufficient on their own

Three prior plans each captured one facet and would not, alone, fix the problem:

- `agy_background_task_permission_wording.md` — adds only a "don't ask for approval" prompt preamble. Treats the
  wording, relies on the model obeying instructions it currently ignores, and adds no safety net, so silent
  false-successes continue whenever the model still defers to a background task.
- `fix_agy_print_background_completion.md` — proposes parsing Antigravity's private log/trajectory and resuming via
  `agy --conversation`. Correct mechanism, but fragile: it depends on the unstable private DB/log schema and on
  `--continue`/`--conversation` print-mode session persistence that the migration research explicitly flagged as "needs
  a spike before relying on it."
- `agy_no_progress_turn_recovery.md` — has the strongest analysis (proved print mode can run tools; identified the
  no-tool-call final turn; proposed detection + bounded continuation + loud failure), but under-diagnosed the _trigger_
  as merely "intermittent model behavior" rather than the background-task/print-mode mismatch, and leaned on a text-only
  heuristic.

This plan **supersedes and merges** all three: it names the real trigger, steers the model off the background-task path,
uses the trajectory data SASE already captures as the primary (structural) progress signal with a text heuristic as
fallback, and converts silent false-success into recovery-or-loud-failure.

## Goals

1. An `agy` turn that produces only a plan / "waiting for a background task" / "please approve" narration is
   **automatically continued** to real execution, and if it still refuses to make progress, the run **fails loudly**
   instead of being reported as success.
2. Reduce how often the planning-only / background-deferral turn happens at all, by steering the `agy` model to run
   commands synchronously, never wait on a background task in print mode, never ask for approval, and write the final
   answer directly to stdout.
3. Keep all behavior **provider-local** to `AgyProvider`: no new `agy`-specific branches in the shared runner,
   finalizer, or retry engine, consistent with the epic's "keep provider code thin" principle.
4. Preserve the `agy` MVP contract: plain stdout remains the user-visible reply; SASE still does **not** fabricate
   `tool_calls.jsonl`, `usage.json`, or tool-panel rows from Antigravity internals.

## Non-goals

- Do **not** change Antigravity's permission flag; `--dangerously-skip-permissions` is already correct and stays.
- Do **not** scrape Antigravity's human TUI rendering or "brain" artifacts to synthesize structured tool/usage rows
  (still gated on a stable upstream contract).
- Do **not** make `--continue`/`--conversation` the session-persistence mechanism; reuse the proven accumulated-context
  restart pattern. (Native conversation resume can be a fast-follow once its print-mode persistence is proven.)
- Do **not** touch Claude/Codex/Qwen/OpenCode providers or the cross-provider runner/finalizer/retry engine.
- This is provider invocation glue, not cross-frontend domain behavior, so it stays Python-side in this repo and does
  not cross the Rust core boundary.

## Design

All work lives in `src/sase/llm_provider/agy.py` (+ its `_subprocess_agy.py` helper) and
`tests/test_llm_provider_agy.py`.

### 1. Steer the model off the background-task path (occurrence reduction)

Add a small provider-local helper that wraps the prompt with a compact Antigravity print-mode directive before it is
sent to `agy --print`. The directive tells the `agy` model, in effect:

- You are running non-interactively under SASE with `--dangerously-skip-permissions`; **never ask the user to approve a
  tool call or command** — approval is already granted.
- **Run commands synchronously and block for their output.** Do not dispatch background/async tasks and do not set a
  short async wait; there is no interactive loop to notify you, so a backgrounded command's result will be lost.
- **Never end a turn with only a plan** or a statement that you are "waiting" / "pausing" / "will be notified". Invoke
  your tools to actually carry out each step.
- Put the **final user-facing answer directly in your response** (stdout), not only in a brain artifact or a linked
  file.

Keep it minimal and behind `AgyProvider` so it never leaks to other runtimes. Apply the existing oversized-prompt argv
guard to the **wrapped** prompt, and keep the original user prompt available separately for interrupt/continuation
context reconstruction.

### 2. No-progress detection + bounded auto-continuation + loud failure (primary safety net)

In `AgyProvider.invoke()`, after a turn returns exit `0`, classify whether the turn actually made progress before
accepting it as the final answer.

- **Primary, structural signal (preferred when available).** The provider already snapshots the Antigravity trajectory
  DB before the run (`prepare_agy_tool_call_extraction`) and reads new steps after it (`append_agy_tool_call_events`).
  Reuse that same snapshot/diff to ask a precise question: did this turn execute any tool, and does it end on a
  `run_command` step still in a `RUNNING` / backgrounded status with no later model turn consuming it? A turn that
  executed **no** tools, or that ends on an unconsumed background/RUNNING command, is no-progress. This is far more
  reliable than text matching and is gated exactly like the existing extraction (supported version + artifacts dir).
- **Fallback, text signal (always available).** When trajectory data is unavailable, use a conservative, multi-signal
  heuristic `_looks_like_no_progress(content)`: the reply is dominated by future-tense intention lines (`I will` /
  `I'll` / `I am going to` / `Next, I will`), **and** ends on a "waiting / pausing / please approve / will be notified /
  background" note (or is below a small substance threshold), **and** lacks the markers the model uses when it actually
  finished. Keep the phrase/regex list data-driven and unit-tested with the real `022.agy` / `03b.agy` text as positive
  fixtures and real completed answers as negative fixtures, to bound false positives.
- **Recovery.** When a turn is classified no-progress, reuse the **existing accumulated-context restart loop** already
  in `invoke()` (the one used for interrupts): re-invoke `agy --print` with the accumulated context plus an
  `agy`-specific continuation nudge — _"You described a plan but did not carry it out. Do not restate the plan. Run your
  tools synchronously now to execute each step, then output the final answer directly."_ This is distinct from the
  context-limit `_RETRY_CONTINUATION_NUDGE`.
- **Bound + loud failure.** Cap the continuations (`_MAX_NO_PROGRESS_CONTINUATIONS`, default small, overridable via a
  `SASE_AGY_*` env var, counted separately from interrupt cycles). If the cap is exhausted and the result still looks
  like no progress, raise `LLMInvocationError` with an actionable message (and conversation/artifact pointers when
  known). This converts the silent false-success into a real error that the existing retry engine / `done.json` failure
  path can surface — directly extending the epic's "do not treat empty stdout as success" requirement to the
  non-empty-but-no-work case.

This adds **no runner branch**: it reuses machinery the provider already owns (the restart loop and the trajectory
snapshot) and stays entirely inside `AgyProvider`.

### 3. Pin the workspace cwd (secondary correctness fix, found while diagnosing)

`AgyProvider._run_subprocess` spawns `agy` with only `env=`, never `cwd=` or `--add-dir`. The migration research and
probe stderr (`Shell cwd was reset to …`) show `agy`'s shell tool can then operate **outside** the agent's workspace.
Pass the agent workspace explicitly — set `cwd=` on `subprocess.Popen` and add `--add-dir <workspace>` — matching how
the runner hands the workspace to other providers (confirm the working-directory source before wiring it). Not the cause
of the false-success, but a latent correctness bug worth closing in the same change.

## Tests

Extend `tests/test_llm_provider_agy.py` (anchor on its existing `@patch("…agy.subprocess.Popen")` unit tests, the
`SASE_AGY_PATH` fake-CLI integration test `test_agy_provider_invokes_fake_cli_and_writes_artifacts`, the
interrupt-resume test `test_agy_provider_interrupt_resume_prompt_construction`, and the trajectory test
`test_agy_provider_extracts_tool_calls_from_trajectory_db`):

- **Prompt directive:** the wrapped prompt sent as the `--print` argv contains the directive and the original user
  prompt; the oversized-prompt guard applies to the wrapped prompt; nested `%model:agy/<name>` resolution still holds.
- **No-progress detection (text):** verbatim `022.agy` / `03b.agy` stubs and an empty/whitespace reply classify
  positive; real completed multi-paragraph answers classify negative.
- **No-progress detection (trajectory):** a synthetic trajectory snapshot whose final step is a `RUNNING`/backgrounded
  `run_command`, or that shows zero executed tools, classifies positive; a snapshot with executed tools + a substantive
  reply classifies negative.
- **Continuation loop:** a fake `agy` that returns a planning-only stub first and real content second fires exactly one
  continuation and returns the real content; a clean first answer returns immediately with no extra invocation (guards
  against false positives / wasted calls).
- **Cap exhaustion → loud failure:** a fake `agy` that always stubs raises `LLMInvocationError` after the cap, with
  subprocess invocations equal to cap+1.
- **MVP invariants preserved:** still writes `live_reply.md`, still does **not** create `usage.json` or fabricate
  `tool_calls.jsonl`/thinking artifacts from internals.
- **cwd:** `subprocess.Popen` is called with the expected `cwd` and/or `--add-dir <workspace>`.

## Verification

- `just install` then the focused suites:
  `pytest tests/test_llm_provider_agy.py tests/test_agy_integration_polish.py tests/ace/tui/tools/test_reader_agy.py`
- Because this changes source in the sase repo, finish with `just check`.
- Optional real smoke: re-run an `agy` "review two plans and recommend one" task a few times and confirm it now either
  produces the recommendation or fails loudly, instead of returning a planning-only stub.
- Update the Antigravity section of `docs/llms.md` to document the print-mode background-task hazard, the runtime
  directive, and the no-progress recovery/loud-failure behavior (and clarify that `--dangerously-skip-permissions`
  already handles tool approval, so background-task completion is a separate concern).

## Risks / mitigations

- **Heuristic false positives** (a real short answer treated as no-progress → wasted re-invocation or spurious error):
  prefer the structural trajectory signal; keep the text heuristic conservative and multi-signal; cover with
  negative-case tests from real answers; keep the continuation cap low.
- **Heuristic false negatives** (a stub slips through): still strictly better than today; the directive lowers
  occurrence and the loud-failure path covers the repeated case.
- **Over-engineering / scope creep:** keep all logic provider-local and data-driven; no runner/finalizer/retry-engine
  changes; native `--conversation` resume deferred to a future spike.

## Acceptance criteria

- `AgyProvider` still launches `agy` with `--dangerously-skip-permissions`, still writes `live_reply.md`, and still
  emits no fabricated structured artifacts.
- The prompt sent to `agy --print` instructs the model to run commands synchronously, never wait on a background task or
  ask for approval in print mode, and answer directly in stdout.
- A planning-only / "waiting for a background task" / "please approve" turn is auto-continued; if it persists past the
  cap, `invoke()` raises `LLMInvocationError` rather than returning a false success.
- Focused `agy` provider tests pass and `just check` is green.
- `docs/llms.md` explains the background-task/print-mode hazard and why this fix resolves the observed `agy` behavior
  without changing SASE plan-approval semantics.

## References

- Provider: `src/sase/llm_provider/agy.py` (`invoke`, the accumulated-context restart loop, `_run_subprocess`,
  `llm_default_retry_config`); trajectory helper `src/sase/llm_provider/_subprocess_agy.py`
  (`prepare_agy_tool_call_extraction`, `append_agy_tool_call_events`).
- Retry plumbing: `src/sase/llm_provider/retry_config.py` (`_RETRY_CONTINUATION_NUDGE`, `error_patterns`).
- Tests: `tests/test_llm_provider_agy.py`.
- Epic / research: `sdd/epics/202606/agy_provider_mvp.md` (Phase 2 task 10; Phase 7 parity),
  `sdd/research/202606/agy_migration_consolidated.md` (no `--output-format`/sync flag; `cwd`/`--add-dir` recommendation;
  `--continue` "needs a spike"), `sdd/research/202606/agy_e2e_hardening.md`.
- Superseded drafts (merged here): `agy_no_progress_turn_recovery.md`, `fix_agy_print_background_completion.md`,
  `agy_background_task_permission_wording.md`.
- Failing transcripts: `037.agy`, `03a.agy`, `03b.agy`, `022.agy` (all "review two plans and recommend one"). </content>
  </invoke>
