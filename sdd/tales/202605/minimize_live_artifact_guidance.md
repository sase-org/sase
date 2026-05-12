---
create_time: 2026-05-12 11:31:07
status: done
prompt: sdd/prompts/202605/minimize_live_artifact_guidance.md
---
# Minimize Live Artifact Guidance Changes

## Context

Commit `4b7e0a92` ("fix: add live artifact fallback guidance to skills") added cross-skill citation guidance for live
artifacts plus phrase-level rendering tests. The behavioral contract it captures is genuinely useful — both skills
should cite artifact paths and label draft/live versus stable/completed evidence — but the implementation introduced
redundant prose and test assertions that bloat the skill files and the shipped-source test without adding coverage.

The skill bodies are loaded into agent context every time these skills trigger. Anything that restates information
already adjacent in the same file is pure context tax. The test assertions are similarly load-bearing for the
cross-skill contract, but stacking three assertions against the same one-line addition does not strengthen the contract
— it just couples the test to surface wording.

## Goals

1. Cut the new "### Reviews and comparisons" subsection in `sase_agents_status.md` down to the one non-obvious idea it
   carries, without losing that idea.
2. Trim the test phrase lists for `sase_agents_status` and `sase_chats` to the minimum that still pins the cross-skill
   contract (handoff direction + live/stable labeling vocabulary).
3. Keep `sase_chats.md` as-is (its addition is already one sentence; on review there is no genuine redundancy to cut
   without losing the cross-skill labeling vocabulary that the test row asserts against).

## Plan

### 1. `src/sase/xprompts/skills/sase_agents_status.md`

Today the file ends the "Stable vs streaming" section with the rule of thumb, then adds a 2-line citation rule, then a
5-line "### Reviews and comparisons" subsection.

Replace the citation rule and the entire subsection with a single short paragraph that keeps two ideas:

- cite artifact paths and label draft/live versus stable/completed when using live state to answer;
- when comparing or reviewing multiple active agents, do not treat the absence of a completed transcript as the absence
  of useful evidence.

Drop the "### Reviews and comparisons" heading entirely — it was the only new heading in this section and its content
collapses to one sentence. Drop the middle sentence ("Distinguish partial draft evidence from final evidence") because
the "Stable vs streaming" rule of thumb immediately above already says exactly that.

Resulting net change for this file: roughly +3 lines of prose instead of +9, and one fewer heading in the skill's
outline.

### 2. `tests/main/test_init_skills_sources.py`

Tighten the two new/expanded rows.

For `sase_agents_status`, keep three phrases:

- `sase agents status -j` (anchors the primary command — unchanged contract)
- `artifacts_dir` (anchors the artifacts section — unchanged contract)
- `cite the artifact paths` (anchors the new citation rule)

Drop `"review, comparison, or selection questions"` and `"absence of a completed transcript"` — the review/comparison
sentence is being rewritten anyway, and pinning two surface phrases against a single rewritten paragraph couples the
test to wording rather than contract.

For `sase_chats`, keep four phrases:

- `sase chats list -j` (primary command)
- `sase chats show` (primary command)
- `/sase_agents_status` (cross-skill handoff — the unique cross-skill contract)
- `draft/live` (live-artifact labeling vocabulary — pins the new citation rule)

Drop `"walk this fallback chain"`, `"sase agents status -a -j"`, and `"stable/completed"`. The first two are covered
transitively by `/sase_agents_status` (the handoff sentence references it directly), and `"stable/completed"` lives on
the same line as `"draft/live"`, so testing both is one assertion's worth of coverage spread across two assertions.

Leave the `expected_examples` → `expected_phrases` rename in place; it is accurate now that the assertions are
phrase-level rather than CLI example strings, and reverting it would be churn.

### 3. `src/sase/xprompts/skills/sase_chats.md`

No change. The previous edit appended a single sentence to the existing fallback paragraph and is already minimal. The
parenthetical examples (`live_reply.md`, `done.json`) duplicate content in `sase_agents_status.md` but that duplication
is load-bearing: this skill only reaches `sase_agents_status` via handoff, and an agent answering a chat question may
not have the other skill loaded.

### 4. Verification

- `just install` (workspace memory requires this before other `just` commands in an ephemeral workspace).
- `.venv/bin/python -m pytest tests/main/test_init_skills_sources.py -x` to confirm the trimmed phrase lists still
  resolve in every rendered provider target.
- `just check` for the full lint + format + test gate.

## Out of scope

- Do not regenerate or hand-edit installed skill files under `~/.claude/` or sibling provider directories. Source
  templates remain the source of truth.
- Do not revisit the `sase_chats.md` fallback paragraph beyond what is described above.
- Do not touch the SDD tale or prompt files; the previous commit already marked the tale `status: done`.
