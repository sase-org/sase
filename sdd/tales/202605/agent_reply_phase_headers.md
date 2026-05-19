---
create_time: 2026-05-19 11:39:53
status: done
prompt: sdd/prompts/202605/agent_reply_phase_headers.md
---
# Fix Agent Reply Phase Headers After Agent Families

## Context

The Agents tab detail panel renders an `AGENT REPLY` section for agents with follow-up phases. Under that section, each
phase gets a divider label from `get_phase_label()` in the prompt-panel rendering helpers. Since the agent-family
migration, new plan-chain artifacts use canonical hyphenated role suffixes such as `-plan`, `-code`, `-q`, `-epic`, and
numeric feedback suffixes like `-2`. The existing display helper still recognizes only the older dotted suffixes such as
`.plan`, `.code`, `.q`, `.epic`, and `.2`.

That mismatch explains the observed symptom: family phase dividers fall through to the generic `AGENT` label even though
the model already carries the right `role_suffix` metadata.

## Plan

1. Confirm the rendering path and regression surface.
   - Keep the fix in the ACE TUI prompt-panel presentation layer.
   - Do not change agent-family metadata generation or loader semantics unless tests reveal missing metadata.

2. Update phase-label resolution to use the shared plan-chain suffix normalizer.
   - Import `canonical_plan_chain_suffix()` and the canonical suffix constants from `sase.plan_chain`.
   - Map both canonical hyphenated suffixes and legacy dotted suffixes through the same path.
   - Preserve the existing fallback behavior for unknown or missing suffixes.
   - Include any newer canonical phase roles that already exist in the plan-chain contract, notably `-legend` and
     `-commit`, so the display helper remains aligned with the family contract.

3. Add focused regression tests.
   - Extend `TestGetPhaseLabel` to cover `-plan`, `-code`, `-q`, `-epic`, and hyphenated feedback rounds.
   - Keep existing legacy dotted suffix tests to protect backward compatibility for older artifacts.
   - Add coverage for any newly displayed canonical roles if the mapping is added.

4. Verify.
   - Run the focused widget metadata tests first.
   - Because this repo requires full validation after source changes, run `just install` if needed and then
     `just check`.

## Expected Outcome

Agent-family reply subsections in the Agents tab detail panel will display role-specific headers such as `PLANNER`,
`CODER`, `QUESTIONS`, and `PLANNER (round N)` instead of falling back to `AGENT`, while older dotted artifacts continue
to render as before.
