---
create_time: 2026-05-11 11:12:55
status: done
prompt: sdd/prompts/202605/merge_qa_sections.md
---
# Plan: Merge Multiple `### Questions and Answers` Sections in Agent Prompts

## Problem

When an agent asks the user questions across multiple rounds (e.g. a planner enters `QUESTION` state more than once, or
a question round is followed by a feedback round and then more questions), the follow-up prompt accumulates _one
independent_ `### Questions and Answers` section per round, each restarting numbering at `Q1`. The snapshot in
`~/tmp/sase_snapshot.txt` shows this concretely: a single prompt contains two `### Questions and Answers` headers, with
Q1/Q2 (Repro, Symptom) in the first and Q1/Q2 (Launch surface, Symptom) in the second — four total questions that should
be labeled Q1–Q4 under one header.

The follow-up agent reads the prompt as if it were two unrelated batches of questions. That obscures the chronological
narrative ("you asked these, then re-asked these"), makes references like "see Q3 above" impossible, and creates
ambiguity when the same `header` (e.g. "Symptom") appears in two rounds.

Each round also emits its own `%xprompts_enabled:false` ... `%xprompts_enabled:true` wrap around its body, and may carry
its own `Global Note` plus `---` separator. After multiple rounds the prompt has multiple wrap pairs and multiple
global-note blocks interleaved with question blocks.

The same shape leaks into:

- The chat transcript saved for each question step (`save_chat_history(..., response=format_qa_for_prompt(...))`).
- The SDD prompt snapshot, via `update_spec_with_qa(...)`, which currently appends a fresh QA block to the file each
  round.
- The feedback-retry path (`run_agent_exec_plan.py:258-260`), which rebuilds `state.current_prompt` by concatenating
  every entry in `state.qa_sections` — so a plan that goes through two QA rounds followed by a feedback rejection ends
  up with two non-merged `### Questions and Answers` headers in the rebuilt prompt.

## Goal

After any number of question rounds, the follow-up prompt contains **exactly one** `### Questions and Answers` section,
with continuous numbering (`#### Q1`, `#### Q2`, …) spanning every question asked so far, wrapped in a single
`%xprompts_enabled:false` ... `%xprompts_enabled:true` pair, and with a single trailing `Global Note` block (if any).
The SDD prompt snapshot mirrors the same merged section. The chat transcripts for each question step continue to render
the QA state visible at the end of that step (which means each step's transcript shows the running merged section, not a
per-round delta — see Decision 2).

## Where it goes wrong today

1. **`src/sase/main/qa_markdown.py:38`** — `build_qa_markdown` is single-round: it unconditionally writes
   `### Questions and Answers` and numbers `f"Q{idx + 1}"` from `enumerate(questions)`. It has no notion of a continuing
   series.

2. **`src/sase/axe/run_agent_helpers.py:511`** — `format_qa_for_prompt(questions, response)` calls `build_qa_markdown`
   and wraps the result in `%xprompts_enabled:false` markers. One round in, one wrapped section out.

3. **`src/sase/axe/run_agent_exec_plan.py:619-621`** — the question handler does:

   ```python
   qa_text = format_qa_for_prompt(q_data.get("questions", []), response)
   state.qa_sections.append(qa_text)
   state.current_prompt = state.current_prompt + "\n\n" + qa_text
   ```

   On the second round, `state.current_prompt` _already contains_ the first round's section, and we append a second one.

4. **`src/sase/axe/run_agent_exec_plan.py:258-260`** — the feedback path reconstructs the prompt as
   `original_prompt + "\n\n".join(state.qa_sections) + "\n\n### Additional Requirements\n...`. Same issue from a
   different angle: replay of `qa_sections` reproduces N independent headers.

5. **`src/sase/axe/run_agent_exec_plan.py:629-635`** — `update_spec_with_qa(spec_path, qa_text)` appends each round's
   text to the SDD prompt snapshot. `update_prompt_with_qa` in `src/sase/sdd/files.py:359-363` is a pure append:
   `existing.rstrip("\n") + "\n\n" + qa_markdown + "\n"`. So the snapshot file accrues the same duplicated headers.

6. **`src/sase/axe/run_agent_exec.py:192`** and **`src/sase/axe/run_agent_retry_spawn.py:64`** — both define
   `qa_sections: list[str]` on the agent state, with retry-handoff serialization
   (`tests/test_axe_run_agent_retry_spawn.py:195`) round-tripping it through JSON. The chosen data model has to remain
   serializable for spawn-on-retry handoff to keep working.

## Approach: aggregate rounds, render once

Instead of trying to detect and surgically merge text after the fact, change the data model so the prompt is _always
rendered from a structured list of rounds_. The merged form is then the only form, and there's no second representation
to keep in sync.

### Data model

Replace `state.qa_sections: list[str]` with a structured `state.qa_rounds: list[QARound]`. A round is just the inputs
that produced one section today:

```python
@dataclass
class QARound:
    questions: list[dict[str, Any]]   # original q_data["questions"]
    answers: list[dict[str, Any]]     # aligned answer dicts (the same list format_qa_for_prompt already builds)
    global_note: str | None
```

`QARound` is a plain dataclass over JSON-serializable primitives so retry-handoff continues to work — the existing JSON
test just needs to switch from `"qa_sections": []` to `"qa_rounds": []`.

### Renderer

Add a new function in `src/sase/main/qa_markdown.py`:

```python
def build_merged_qa_markdown(rounds: list[QARound]) -> str: ...
```

Semantics:

- Emits exactly one `### Questions and Answers` header.
- Iterates through `rounds` in order; for each question across all rounds, emits `#### Q{N}: {header}` where `N` is a
  monotonically increasing counter across rounds (not per-round).
- Renders each question's option ballot exactly as `build_qa_markdown` does today (so the existing single-round output
  is a special case of N=1).
- For global notes: see Decision 1 below.

Keep `build_qa_markdown(questions, answers, global_note)` as a thin wrapper around
`build_merged_qa_markdown([QARound(questions, answers, global_note)])` so existing callers (notably the TUI live preview
at `src/sase/ace/tui/modals/user_question_modal.py:399-410`) keep working unchanged. This preserves the modal-vs-prompt
parity invariant the existing test `test_build_qa_markdown_direct_matches_format_qa_for_prompt_body` enforces.

Add `merge_qa_for_prompt(rounds: list[QARound]) -> str` in `run_agent_helpers.py` that wraps the merged body in _one_
`%xprompts_enabled:false` ... `%xprompts_enabled:true` pair. Retain `format_qa_for_prompt(questions, response)` as a
single-round convenience that constructs one `QARound` and delegates — this keeps the test surface stable for the
existing 20+ tests in `tests/test_qa_format.py`.

### Call sites

In `run_agent_exec_plan.py`:

1. **Question handler** (lines 619-621): build a `QARound` from `q_data["questions"]` and the aligned
   answers/global-note from `response`, append it to `state.qa_rounds`, then rebuild `state.current_prompt` from
   scratch:

   ```python
   state.current_prompt = state.original_prompt + "\n\n" + merge_qa_for_prompt(state.qa_rounds)
   ```

   This requires `state.original_prompt` to be the _bare_ prompt (no QA suffix). It already is (`run_agent_exec.py:192`
   initializes from the initial prompt, and the feedback path at line 258 already uses it as the bare base) — but the
   spec line should be added to the field docstring so future edits don't break it.

2. **Feedback-retry path** (lines 257-262): change the inner loop to use `merge_qa_for_prompt(state.qa_rounds)` instead
   of `for qa in state.qa_sections: base += "\n\n" + qa`. After this change both call sites build the same merged
   section.

3. **Chat history** (line 583): pass `merge_qa_for_prompt(state.qa_rounds)` as the `response` so the chat shows the
   running merged section after this round (see Decision 2).

4. **SDD spec update** (lines 629-635): pass `merge_qa_for_prompt(state.qa_rounds)` to a _new_ helper
   `set_prompt_qa(path, merged_qa_markdown)` that finds-and-replaces any prior `### Questions and Answers` block in the
   file (including its trailing global note and `---` separator) and replaces it with `merged_qa_markdown`. If no prior
   block exists, behavior is the same as today's append. Keep `update_prompt_with_qa` / `update_spec_with_qa` as thin
   wrappers that delegate to `set_prompt_qa` so the public API in `sase.sdd.__init__` doesn't break; the test in
   `tests/test_sdd.py:245` continues to cover the legacy wrapper but with replace-not-append semantics on a second call.

### Retry-handoff

`run_agent_retry_spawn.py:64` field rename `qa_sections` → `qa_rounds`. JSON serialization is one
`[dataclasses.asdict(r) for r in rounds]` away. `tests/test_axe_run_agent_retry_spawn.py:195` updated to use the new
field. No on-disk migration is needed — retry-handoff files are short-lived per-agent state, not durable artifacts. If a
stale handoff file with the old field name exists, deserialization should treat it as zero rounds (best-effort) rather
than crash.

## Decisions to make

**Decision 1: Global notes from multiple rounds.** Each round can carry a `global_note`. Three plausible behaviors:

- (a) **Last wins** — only the most recent round's note is rendered, single `Global Note` block at the bottom. Simple,
  matches "the user's final say."
- (b) **Concatenate as separate notes**, labeled per round: `> **Global Note (round 2):** ...`. Preserves history but is
  verbose and visually messy.
- (c) **Concatenate inline** as bullet points under a single `> **Global Note:**`. Compact, loses round attribution.

Recommend (a). The global note is meant to be a high-level steering message; it's almost always a refinement, and the
user is unlikely to want a multi-round note diary. Document the choice in `build_merged_qa_markdown`'s docstring. The
example in the snapshot only has one global note in round 2, so either (a) or (b) renders it correctly — pick (a) for
simplicity and revisit only if a user reports loss.

**Decision 2: Per-step chat history content.** The chat transcript saved at line 581-589 records the prompt → response
for the question step. Two options:

- (i) Save the _delta_ for this round (one round's QA, like today, just from a fresh `format_qa_for_prompt`).
- (ii) Save the _running merged section_ (everything so far, including this round).

Recommend (ii). It matches what the follow-up agent actually sees in its prompt and means a reader of an N-th-round chat
can read top-to-bottom without cross-referencing earlier chat files. The chat history is per-step, but the user-visible
artifact in the prompt is monotonic; making the chat reflect that is the less surprising default. Cheap to do — it's
just calling `merge_qa_for_prompt(state.qa_rounds)` after appending the new round.

**Decision 3: Detect-and-merge-on-load vs. always-render-from-rounds.** Could we instead leave `qa_sections` as text and
post-process at append time, scanning for `### Questions and Answers` headers and renumbering? Reject this — it's
brittle (header text would need to be a sentinel that can never appear in user free-form), and the SDD snapshot and
chat-history sites would each have to repeat the same scan-and-merge logic. The structured-rounds model is more invasive
but localizes the merge logic to one place.

## Risk and migration

- **Behavior change for in-flight agents during deploy.** An agent paused mid-run with a serialized state file using
  `qa_sections` would deserialize to an empty `qa_rounds` after upgrade. Mitigation: in the state loader, accept either
  `qa_sections` or `qa_rounds`; if only `qa_sections` is present, log a warning and reconstruct best-effort empty rounds
  (the rendered prompt will then miss prior QA, but the agent won't crash). Long-running planner sessions across a
  deploy are rare enough that this is acceptable.
- **TUI modal regression.** The modal preview goes through `build_qa_markdown` (single-round). Since we keep that
  function as a one-round wrapper around `build_merged_qa_markdown`, the modal must remain visually identical. The
  existing parity test (`test_qa_format.py:175`) defends against drift.
- **SDD prompt snapshot files committed to repos.** A snapshot file written by an old version (with two
  `### Questions and Answers` blocks) will be partially merged by `set_prompt_qa` on the next update (which only knows
  to replace the _last_ matching block). This is a one-time cosmetic issue affecting only snapshots actively being
  amended across an upgrade — accept it; the next agent run on that spec produces the clean form.

## Tests

New tests in `tests/test_qa_format.py`:

- `test_build_merged_qa_markdown_continuous_numbering`: two rounds × two questions each → output has exactly one
  `### Questions and Answers`, headers `Q1`/`Q2`/`Q3`/`Q4`, and round-2 headers map to round-2 question text.
- `test_merge_qa_for_prompt_single_wrapper_pair`: output has exactly one `%xprompts_enabled:false` and one
  `%xprompts_enabled:true` regardless of round count.
- `test_merged_global_note_last_wins`: round 1 has note "A", round 2 has note "B" → only "B" appears.
- `test_merged_global_note_round1_only_renders`: round 1 has a note, round 2 doesn't → round 1's note still renders
  (i.e. "last wins" means "last non-empty wins").
- `test_build_qa_markdown_single_round_unchanged`: existing single-round golden output for a fixed input is
  byte-for-byte preserved after refactor (regression guard for the modal preview and existing prompt tests).

Modify `tests/test_sdd.py` `test_update_spec_with_qa_legacy_wrapper`: call it twice with different QA markdown — assert
the file contains exactly one `### Questions and Answers` block matching the _second_ call's content
(replace-not-append).

Modify `tests/test_axe_run_agent_retry_spawn.py:195`: replace `"qa_sections": []` with `"qa_rounds": []`; add one
round-trip case with a non-empty `qa_rounds` to make sure dataclass-asdict / fromdict survives JSON.

New integration-flavor test in `tests/test_axe_run_agent_exec_plan.py` (or wherever the question-handler tests live —
search for existing fixtures first; if there's no existing test for this handler, file a small one with a fake `q_data`
/ `response` and assert `state.current_prompt` ends with a merged single section after two simulated rounds, and that
`state.qa_rounds` has length 2).

## Files to change

- `src/sase/main/qa_markdown.py` — add `QARound` dataclass, add `build_merged_qa_markdown`, make `build_qa_markdown` a
  one-round wrapper.
- `src/sase/axe/run_agent_helpers.py` — add `merge_qa_for_prompt(rounds)`; keep
  `format_qa_for_prompt(questions, response)` as a one-round convenience that delegates.
- `src/sase/axe/run_agent_exec.py` — rename `qa_sections` → `qa_rounds` in `RunAgentState`; update docstring on
  `original_prompt`.
- `src/sase/axe/run_agent_exec_plan.py` — append `QARound` instead of text; rebuild `current_prompt` from
  `original_prompt + merge_qa_for_prompt(rounds)` at both the question-handler site and the feedback-retry site; pass
  merged text to chat-history and SDD snapshot update.
- `src/sase/axe/run_agent_retry_spawn.py` — field rename + JSON serialize/deserialize for `qa_rounds`.
- `src/sase/sdd/files.py` — add `set_prompt_qa(path, merged_qa_markdown)` that replaces any prior
  `### Questions and Answers` block; route `update_prompt_with_qa` / `update_spec_with_qa` through it.
- Tests: `tests/test_qa_format.py`, `tests/test_sdd.py`, `tests/test_axe_run_agent_retry_spawn.py`, plus a small
  handler-level test.

## Non-goals

- Reformatting how individual questions render (ballot, multi-select indicator, "Other" line) — that stays exactly as
  `build_qa_markdown` produces today.
- Changing the TUI modal preview (it remains a single-round preview of the in-flight ballot).
- Reworking the question-marker / response JSON schema on disk — the change is purely in how we _aggregate and render_
  answers we already capture.
- Backfilling old SDD snapshot files in the repo. Snapshots are regenerated on next agent run on the spec.
