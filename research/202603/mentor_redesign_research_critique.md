# Mentor Redesign v2: Critique and Improved Recommendation

## Executive Summary

The original research in `mentor_redesign.md` is strong on prior art and directionally correct on moving from binary
outcomes to structured review feedback. The largest weakness is that it recommends a broad rename and a new verdict
model without fully accounting for how mentors currently work in sase:

- Mentors are both reviewers and optional automated code modifiers (via embedded `#propose`).
- `PASSED` vs `FAILED` is currently overloaded to mean both runtime success and whether a proposal was created.
- Scheduler and TUI behavior depend heavily on existing status-line semantics, suffix types, and proposal references.

The best improved approach is not a hard rename or big-bang rewrite. It is a staged redesign that:

1. Keeps the public concept as **Mentor** (for continuity), but introduces **role modes** (`review`, `fix`, `hybrid`) so
   behavior is explicit.
2. Adds a **structured finding artifact** first, while preserving existing status lines for compatibility.
3. Splits status into **execution status** and **review outcome** so proposal creation no longer masquerades as failure.
4. Adds optional rubric and tier support in config, but with defaults that keep current profiles working unchanged.

## What the Existing Research Gets Right

- Correctly emphasizes explicit, versioned criteria (rubrics) over prompt-only behavior.
- Correctly identifies noise control and actionability as core trust drivers.
- Correctly recommends separating infrastructure failure from review judgment.
- Correctly proposes incremental migration instead of trying to ship all advanced features at once.

## Key Gaps in the Existing Recommendation

## 1) Rename-first strategy is too expensive for current codebase

The recommendation to rename `mentor` -> `reviewer` everywhere is clean conceptually but high churn operationally:

- `MENTORS` is a persisted ChangeSpec field.
- Many modules/tests assume mentor terminology and file layout.
- Existing xprompts and workflows are already named around mentor semantics.

A rename-first approach will spend significant effort on plumbing before improving review quality.

## 2) Proposed verdict model conflates with current proposal workflow

The suggested `APPROVED | CHANGES_REQUESTED | COMMENTED` model is good, but incomplete for current behavior:

- Today, a mentor can produce a code proposal; this is currently encoded as `FAILED` + `entry_ref` suffix.
- This is not a review failure; it is an actionable output.

Without separating execution and review domains, the new model will remain ambiguous.

## 3) Tiering is useful but needs clearer scheduler contract

Tier 1/2 is directionally good, but current scheduler gating is based on hook readiness and profile matching. To avoid
scheduler complexity drift, tiering needs explicit runtime contract:

- Tier decides context budget and model tier.
- Prerequisite policy decides when to run (`immediate`, `after_hooks_ready`, etc.).

Mixing these concerns leads to brittle behavior.

## 4) Advanced loops/memory are premature as first-class features

Iterative loops and episodic memory are promising, but they should be layered after core signal quality is stabilized.
The biggest current issue is schema and semantics clarity, not multi-round autonomy.

## Improved Architecture (Pragmatic v2)

## A. Keep "Mentor" as top-level object, add explicit role

Keep current naming in code/storage (`mentor_profiles`, `MENTORS`) for compatibility, but define mentor behavior
explicitly:

```yaml
mentor_profiles:
  - profile_name: python_security
    role: review # review | fix | hybrid (default: hybrid for backward compatibility)
```

Semantics:

- `review`: Finds issues; does not create proposals.
- `fix`: Focuses on generating code changes/proposals.
- `hybrid`: Can do both (matches current behavior most closely).

This resolves user-facing ambiguity (mentor vs reviewer vs critic) without expensive rename churn.

## B. Introduce dual-status model

Add structured state per mentor run:

- `execution_status`: `QUEUED | STARTING | RUNNING | SUCCEEDED | FAILED | KILLED | DEAD`
- `review_outcome`: `NONE | APPROVED | COMMENTED | CHANGES_REQUESTED | PROPOSAL_CREATED`

Mapping guidance:

- Infrastructure/runtime errors update `execution_status` only.
- Review judgment and proposal behavior update `review_outcome`.
- Legacy `status` line can be derived for backward compatibility during migration.

This cleanly fixes the current `FAILED == proposal created` semantic bug.

## C. Add structured findings artifact before changing ChangeSpec format

Do not immediately redesign `MENTORS` line grammar. First, write per-run JSON artifacts and link them from existing
mentor status lines.

Proposed artifact path:

- `~/.sase/mentors/<cl>-<profile>-<mentor>-<timestamp>.review.json`

Schema:

```json
{
  "schema_version": 1,
  "profile": "python_security",
  "mentor": "injection_guard",
  "entry_id": "7",
  "execution_status": "SUCCEEDED",
  "review_outcome": "CHANGES_REQUESTED",
  "summary": "2 high-confidence security findings",
  "findings": [
    {
      "id": "inj-001",
      "dimension": "injection",
      "severity": "error",
      "confidence": "high",
      "file": "src/foo.py",
      "line": 42,
      "title": "User input reaches shell command",
      "detail": "...",
      "suggestion": "Use subprocess.run([...], shell=False)",
      "actionable": true
    }
  ],
  "proposal_id": "7a"
}
```

Benefits:

- Keeps parser/TUI stable initially.
- Enables filtering/aggregation and future UI improvements.
- Gives testable contract for mentor outputs.

## D. Rubric support with compatibility defaults

Add optional rubric to `mentor_profiles`; when absent, behavior remains prompt-driven.

```yaml
mentor_profiles:
  - profile_name: python_security
    role: review
    tier: deep
    run_when: after_hooks_ready
    rubric:
      - dimension: injection
        severity_policy:
          error_if: "unsanitized input reaches command/query"
      - dimension: secrets
        severity_policy:
          error_if: "hardcoded credentials or tokens"
```

Compatibility rules:

- Existing profiles with only `mentors + match criteria` remain valid.
- `role`, `tier`, `run_when`, `rubric` are optional in v1 migration.

## E. Make tiering scheduler-safe

Define tier as execution strategy only:

- `tier: fast` => diff-focused, smaller model, tighter timeout.
- `tier: deep` => workspace-aware, larger model, broader context.

Define run timing separately:

- `run_when: immediate | after_hooks_ready`.

This keeps scheduler logic composable and avoids hidden coupling.

## F. Optional advanced features after core rollout

After the above ships and metrics are healthy:

- Add `max_iterations` loop for `fix`/`hybrid` roles.
- Add per-CL memory summary artifact (`mentor_memory.json`) rather than immediate in-band prompt stuffing.

## Migration Plan (Low Risk)

1. Add new config fields as optional (`role`, `tier`, `run_when`, `rubric`), no behavior change by default.
2. Add review artifact writer in `MentorWorkflow` / `axe/mentor_runner.py`.
3. Add dual-status internal model and mapping from legacy status.
4. Update scheduler checks to use `execution_status` for liveness and `review_outcome` for judgment display.
5. Add TUI read path for artifact summaries (non-breaking enhancement).
6. Only then consider aliasing UI wording (`Mentors` label -> `Reviews`) if desired.

## Naming Recommendation

Use this naming policy:

- Keep internal entity name: **Mentor** (backward compatibility).
- Expose role vocabulary in docs/UI:
  - "Review mentor" for routine analysis.
  - "Fix mentor" for auto-proposal behavior.
  - "Critic mode" as an optional adversarial profile style.

This gives conceptual clarity without disruptive renames.

## Acceptance Criteria for the Redesign

A redesign should be considered successful only if these are true:

- A proposal-creating mentor run is no longer reported as execution failure.
- At least 90% of mentor runs produce a parseable structured artifact.
- Developers can filter findings by severity and dimension.
- Existing `mentor_profiles` configs continue to run unchanged.
- Scheduler concurrency and stale-process handling behavior remain unchanged or better.

## Final Recommendation

Proceed with a **schema-first, compatibility-preserving redesign**:

- Do **not** start with global renaming.
- Do **first** split execution vs review semantics and emit structured findings artifacts.
- Add rubric/tier/role as optional config features.
- Defer iterative loops and episodic memory until baseline signal quality and UX are validated.

This approach preserves working behavior, reduces migration risk, and directly addresses the highest-value architectural
flaw in the current system.
