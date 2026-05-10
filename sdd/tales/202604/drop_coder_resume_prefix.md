---
create_time: 2026-04-19 15:29:09
status: done
prompt: sdd/prompts/202604/drop_coder_resume_prefix.md
---

# Plan: Drop `#resume:<planner>` from Coder Agent Prompts to Fix "Prompt is too long"

## Problem

Running a plan-driven coder agent via `sase ace` reliably hits Claude's "Prompt is too long" error partway through
multi-file implementation tasks — visible in the TUI as the last line in the agent's output stream after 20-40
successful tool calls. The error comes from Claude, not sase, and means the coder's `claude -p` session has exhausted
its ~200K-token context window.

Example: the `parent_p4head_leak` coder agent ran from 15:00:07 to 15:09:59 (10 minutes, ~25 visible assistant turns
editing files across `retired Mercurial plugin` and the `sase_<N>` workspace, including two `just check` runs) before failing.

## Root Cause

The coder prompt is assembled in `src/sase/axe/run_agent_exec_plan.py:401-414`:

```python
resume_prefix = ""
if ctx.agent_name:
    if state.agent_step == 2:
        planner_name = f"{ctx.agent_name}.plan"
    else:
        planner_name = f"{ctx.agent_name}.{state.agent_step - 1}"
    resume_prefix = f"#resume:{planner_name} "

state.current_prompt = (
    f"{model_prefix}{resume_prefix}{vcs_prefix}"
    f"@{plan_data['plan_file']}\n\n"
    "The above plan has been reviewed and approved. "
    f"Implement it now.{coder_extra}\n{embedded_refs}"
)
```

`#resume:<planner>` is expanded by `load_chat_for_resume` in `src/sase/history/chat.py:357-418`, which reads the
planner's saved chat file and inlines every `(prompt, response)` turn as flat `**User:** ... **Assistant:** ...` blocks.
Planner chats typically include:

- the planner's full written response (the plan itself, plus commentary)
- any preceding Q&A rounds' User/Assistant transcripts (recursively, via nested `#resume` refs in the chat file)
- every `## Previous Conversation` section carried forward from earlier resumes

For a moderately involved plan this pastes tens of KB into turn zero of the coder's context — **before the coder has
read a single project file**. The coder's own tool-call stream (file reads, `Edit` confirmations, `just check` stdout,
test output) then piles on top of that, and the window fills up.

The structural issue: **the plan document itself is the artifact the coder is supposed to act on.** The planner's
thinking-out-loud log is redundant with (or noisier than) the plan. Yet we pay for that log twice — once to generate it,
once to replay it into the coder's context.

## Proposed Fix — Minimal Version

**Delete the `resume_prefix` lines from `handle_plan_marker`.** The coder prompt becomes:

```python
state.current_prompt = (
    f"{model_prefix}{vcs_prefix}"
    f"@{plan_data['plan_file']}\n\n"
    "The above plan has been reviewed and approved. "
    f"Implement it now.{coder_extra}\n{embedded_refs}"
)
```

The coder still gets:

- `@{plan_file}` — full plan content via preprocessing `@`-expansion
- `coder_extra` — any "Additional instructions" the user typed in the plan approval modal
- `model_prefix` / `vcs_prefix` / `embedded_refs` — unchanged
- Tier-1 always-loaded memory (AGENTS.md + `memory/short/*.md`) via Claude's `CLAUDE.md` chain
- Tier-2 dynamic memory matches — unchanged

The coder loses access to the planner's raw chat history. This is the whole point: that history is where the token bloat
lives and is already captured in the plan doc that good planners produce.

## The Q&A-Round Path

When the planner asks questions via `#questions` before the plan is approved, the flow becomes:

1. Planner (step 1) writes questions.
2. `handle_questions_marker` appends formatted Q&A to `state.current_prompt` (`run_agent_exec_plan.py:488`) and
   increments `agent_step`.
3. Planner (step 2, `.q` suffix, or `.2`) re-runs with the Q&A appended, writes a plan.
4. Plan approved → coder runs.

The Q&A text is **already inlined** into `state.current_prompt` at step 2, so it was visible to the planner when it
wrote the plan. A competent plan incorporates the answers. The coder does not need to re-read the Q&A transcript as long
as the plan reflects it — which is exactly the contract a plan is supposed to uphold.

→ **Drop `#resume:` for both the `agent_step == 2` and `agent_step > 2` branches.** No special case for Q&A rounds.

## Safety Hatch (Opt-In)

Some users may have plans/workflows that rely on the coder seeing the full planner chat — e.g., if a plan is
deliberately terse and the prose matters. To give them an escape hatch without reverting:

- Add an env var `SASE_CODER_INHERIT_PLANNER_CHAT=1`. When set, preserve the original `#resume:<planner_name>` behavior.
- Default: off (drop the resume).
- Document the env var in `memory/short/gotchas.md` or equivalent.

This is cheap insurance. If nobody sets it within a few weeks, we can remove it.

## Testing

Update `tests/test_axe_run_agent_exec_plan.py`:

1. **Flip** `test_coder_prompt_includes_resume_prefix` → rename to
   `test_coder_prompt_excludes_resume_prefix_by_default`. Assert `#resume:` is NOT in `state.current_prompt`. Assert
   `@{plan_file}` IS present. Assert the prompt still starts with `%model:opus\n` (i.e., the model prefix is still in
   the right position).

2. Keep `test_coder_prompt_no_resume_without_agent_name` as-is — it stays valid.

3. **Add** `test_coder_prompt_preserves_resume_when_env_set` — set `SASE_CODER_INHERIT_PLANNER_CHAT=1`, assert
   `#resume:test_agent.plan ` IS in the prompt. Use `monkeypatch.setenv`.

4. **Add** `test_coder_prompt_qa_round_excludes_resume_by_default` — run the plan marker with `state.agent_step == 3`
   (simulating a prior Q&A round); assert `#resume:test_agent.2` is NOT in the prompt. Assert `@{plan_file}` IS present.

5. Verify that `test_approve_prompt_includes_custom_extra_text` and the other existing coder-prompt tests still pass
   unchanged (they don't assert anything about resume).

No changes needed to `src/sase/history/chat.py` — it remains correct for other callers (`rerun`, explicit
`#resume_by_chat`, etc.).

## Non-Goals (Explicit Follow-Ups)

These are real issues but out of scope for this plan:

- **Dynamic memory eager inlining (commit `02cb7691`).** The switch from lazy `@file` refs to `$(cat ...)` substitution
  may have meaningfully grown every prompt's initial size. Investigate separately: measure whether Claude Code's `-p`
  mode actually defers `@`-expansion, and if so whether reverting saves tokens. Not bundled here.
- **Context compaction during long coder runs.** Even without `#resume:`, a sufficiently large refactor can still fill
  the context. Possible future work: detect usage approaching the window limit via the `stream-json` token counts we
  already parse, and either checkpoint-and-restart or emit a warning. Separate design effort.
- **Tool-call output truncation.** Capturing full `just check` stdout into Claude's context is expensive. A separate
  plan could add a length cap with "see /tmp/sase*check*<uuid>.log for full output" redirection. Not here.
- **Plan file size discipline.** Very long plans (>500 lines) are their own problem. Guidance/review, not code.

## Risks and Mitigations

| Risk                                                                                                          | Mitigation                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A plan is too terse and the coder now lacks context that was previously in the resumed chat                   | The env-var opt-in (`SASE_CODER_INHERIT_PLANNER_CHAT=1`) restores old behavior per-invocation.                                                                                                 |
| Existing chat-linking features depend on the coder chat being chainable back to the planner                   | `save_chat_history` still records the coder's chat; `#resume` is still available in user-written prompts. Only the automatic prepend changes. Existing `saved_chat_paths` wiring is untouched. |
| Regression in SDD spec/plan persistence                                                                       | No changes to `_commit_sdd_files` or `sdd.files.write_sdd_files`. The plan-approval → coder hand-off flow is preserved; only the prompt string changes.                                        |
| Someone relied on the planner's tool-call results (e.g., a `Read` the planner did) being visible to the coder | The plan doc should restate anything the planner learned. If not, this exposes a planning-quality issue that's better addressed upstream than by hauling the whole transcript around.          |

## Files to Change

- `src/sase/axe/run_agent_exec_plan.py` — remove `resume_prefix` build, drop from prompt assembly, add env-var check.
- `tests/test_axe_run_agent_exec_plan.py` — flip/add tests per above.
- `memory/short/gotchas.md` (optional) — one-line note on the env var.

No changes to `src/sase/history/chat.py`, `src/sase/memory/dynamic.py`, or the LLM provider layer.

## Rollout

Single commit. The change is a prompt-construction tweak with tight test coverage; no migration, no config changes
required for default behavior. Users who hit any regression can set `SASE_CODER_INHERIT_PLANNER_CHAT=1`.
