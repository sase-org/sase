---
create_time: 2026-05-09 04:30:12
bead_id: sase-2h
tier: epic
status: done
prompt: sdd/prompts/202605/gai_org_ideas_research.md
---
# Plan: Mine `~/org` GAI Notes for SASE Product Ideas

## Goal

Review every likely `gai` reference under `~/org` and produce one concise, polished research note in
`sdd/research/202605/`. The note should identify the strongest old GAI ideas that are still useful for SASE, group them
by product/theme, and recommend a focused set of next implementations.

The target output is a single markdown file, not a large archive dump. It should be useful as a product/design research
input for future epics and tales.

## Scope

Primary source corpus:

- All files under `/home/bryan/org` matching the old GAI naming patterns:
  - exact-ish references to `gai`
  - `#gai`
  - `now_gai`
  - `gai_` ids, filenames, and tags
- Current first pass found 463 likely-relevant files using:
  - `rg -il --hidden --glob '!**/.git/**' '(^|[^A-Za-z])gai([^A-Za-z]|$)|now_gai|gai_' /home/bryan/org`

High-signal files and directories to prioritize:

- `/home/bryan/org/now_gai.zo`
- `/home/bryan/org/gai_ideas.zo`
- `/home/bryan/org/prompts/gai_*.md`
- `/home/bryan/org/text/gai_*`
- `/home/bryan/org/plans/gai_*`
- dated `2025/` and `2026/` daily, poms, and done logs containing `#gai`
- related `lib/chat`, `lib/code`, and `lib/docs` notes that explicitly mention GAI/SASE workflow design

Out of scope:

- Renaming old org notes.
- Implementing product changes.
- Creating multiple research files or a full issue backlog.
- Treating unrelated substrings like "again", "against", or "GaiaMint" as product evidence unless they occur in a
  genuinely relevant file.

## Multi-Agent Work Plan

### Phase 1: Build the corpus map

Produce a durable inventory from `rg` output with file path, rough category, match count, and priority. This phase
should separate likely product sources from incidental references.

Categories:

- Core backlog/design notes: `now_gai.zo`, `gai_ideas.zo`, plans, text snapshots.
- Prompt/workflow sources: `prompts/gai_*.md`, `chat/gai_*`, prompt references in logs.
- Dated execution history: `2025/`, `2026/`, older dated logs.
- External/lit/reference notes: `lib/chat`, `lib/docs`, `lib/code`, `claude_code_ref.zo`, etc.

### Phase 2: Parallel source review

Run multiple agents with disjoint read scopes.

Agent A: Core backlog and idea files.

- Review `now_gai.zo`, `gai_ideas.zo`, and direct `text/gai_*` / `plans/gai_*` sources.
- Extract candidate ideas, original evidence paths, and whether each idea appears still relevant to SASE.
- Emphasize TODOs, `ID::gai_*` entries, BUG pain points, and architectural/product themes.

Agent B: Prompt and workflow sources.

- Review `/home/bryan/org/prompts/gai_*.md`, `/home/bryan/org/chat/gai_*`, and explicit workflow prompt references.
- Extract reusable prompt/workflow patterns, missing workflow primitives, test/commit/review automation ideas, and
  interaction patterns that should influence SASE xprompts/skills/hooks.

Agent C: Dated logs and completion history.

- Review dated `2025/` and `2026/` files from the corpus.
- Mine repeated pain points, already-completed ideas that imply missing polish, ideas that were attempted multiple
  times, and regressions that deserve product hardening.
- Avoid over-weighting one-off pomodoro lines; look for recurrence.

Agent D: Literature/reference cross-check.

- Review `lib/chat`, `lib/code`, `lib/docs`, and related reference notes in the corpus.
- Extract external concepts that map to SASE, especially multi-agent planning, agent review, structured context,
  ChangeSpec/bead workflows, and coding-agent UX.

The main agent will synthesize rather than duplicate all agent work. It will inspect enough primary sources directly to
validate the top claims and check that the final document does not overstate evidence.

### Phase 3: Synthesis and ranking

Cluster extracted ideas into a small number of themes:

- Agent orchestration and multi-agent workflow control.
- ChangeSpec/bead lifecycle and VCS/commit automation.
- Hooks, mentors, reviewers, and quality gates.
- XPrompt/workflow language and reusable prompt assets.
- TUI/ACE interaction design and agent history/revival.
- Testing, flaky failure handling, and evidence capture.
- Project/context memory and structured inputs.

For each candidate idea, score:

- Product value for current SASE.
- Evidence strength in the org corpus.
- Implementation leverage from existing SASE architecture.
- Risk/complexity.
- Whether it is already implemented, partially implemented, or obsolete after the GAI-to-SASE migration.

Keep the final recommendation list short. Prefer fewer stronger ideas with concrete rationale over a broad backlog.

### Phase 4: Write the research note

Create one markdown file:

- Proposed path: `sdd/research/202605/gai_org_ideas_for_sase.md`

Suggested structure:

1. Title and date.
2. Research question.
3. Corpus and method.
4. Executive summary.
5. Top recommendations.
6. Thematic findings.
7. Ideas not recommended now.
8. Source index / evidence notes.

Style constraints:

- Polished but not too large.
- Cite local source paths inline.
- Do not paste large excerpts from private org files.
- Use old `gai` only when referring to source material; translate recommendations into current SASE names.

### Phase 5: Verification

Before finishing:

- Re-run the corpus search and confirm the final doc accounts for every source category.
- Check that all cited paths exist.
- Run `just install` if needed, then `just check` because the repo guidance asks for it after non-bead file changes.
- If `just check` is not feasible or fails for unrelated reasons, report exactly what happened.

## Acceptance Criteria

- The plan is submitted via `sase plan`.
- The final output is exactly one new or updated research markdown file under `sdd/research/202605/`.
- The review uses multiple agents with disjoint source scopes.
- The final note is concise, ranked, and actionable.
- The note includes enough source references for follow-up without becoming a raw dump.
- Existing unrelated worktree changes are not reverted.
