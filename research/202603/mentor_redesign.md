# Mentor Redesign: Research & Architecture Recommendation

## Current State

Mentors in sase are automated AI agents that run against ChangeLists to review code. They are configured as **profiles**
with matching criteria (file globs, diff regexes, amend note regexes, first commit flag), and each profile contains one
or more named mentors with their own prompts. The scheduler orchestrates their lifecycle: detect matching profiles, wait
for hooks to complete, spawn background agents, poll for completion, and update status
(RUNNING/PASSED/FAILED/DEAD/KILLED).

Key characteristics of the current system:

- **Trigger-based**: Mentors activate when commits match profile criteria
- **Fire-and-forget**: Each mentor runs independently with no inter-mentor coordination
- **Binary outcome**: PASSED or FAILED, no structured feedback taxonomy
- **No iteration**: Mentors evaluate once; they don't engage in a revise-and-recheck loop
- **No memory**: Each mentor run is stateless; no learning from prior runs on the same CL or codebase

## Prior Art

### 1. Constitutional AI / Self-Critique (Anthropic)

The model generates a response, critiques it against a set of explicit principles (a "constitution"), and revises. Two
phases: supervised self-improvement, then RLAIF.

- **Paper**: Bai et al., "Constitutional AI: Harmlessness from AI Feedback" (arXiv:2212.08073)
- **Takeaway**: Principles should be explicit and auditable. A mentor's review criteria should be a versioned document,
  not baked into a prompt. The self-critique variant (single agent, single pass) is the simplest useful pattern.

### 2. LLM-as-Judge

An LLM evaluates another LLM's output via pointwise scoring, pairwise comparison, or pass/fail assessment.

- **Papers**: "A Survey on LLM-as-a-Judge" (arXiv:2411.15594), "LLMs-as-Judges" (arXiv:2412.05579)
- **Takeaway**: Judges must explain their reasoning -- bare scores are unreliable. Self-enhancement bias (LLMs rate
  their own outputs higher) argues for using a different model or at minimum a different prompt/persona for the reviewer
  vs. the author. Positional bias is a concern for pairwise comparisons.

### 3. Multi-Agent Review (AutoGen, CrewAI, LangGraph)

Frameworks that orchestrate multiple LLM agents with defined roles.

- **CrewAI**: Role-based (role, backstory, goal). Natural QA/review separation.
- **LangGraph**: Graph-based workflow with conditional branching and cycles. Best for review loops with approval gates.
- **AutoGen**: Conversational multi-agent with group decision-making.
- **Takeaway**: Role separation prevents "same brain, same blind spots." LangGraph's conditional branching is
  well-suited for review loops. But role definitions alone don't guarantee better critique -- the rubric matters more
  than the persona.

### 4. Reflexion (Shinn et al.)

Verbal self-reflection stored in episodic memory. After a failed attempt, the agent generates a textual critique, stores
it, and uses it as context for the next attempt. Three components: Actor, Evaluator, Self-Reflection.

- **Paper**: Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement Learning" (NeurIPS 2023,
  arXiv:2303.11366)
- **Takeaway**: Episodic memory across attempts is powerful. A mentor could accumulate observations about a CL's
  evolution: "In the previous revision, the author fixed the null check I flagged but introduced a new race condition."
  This is the closest pattern to the "mentor" metaphor -- a teacher who remembers and guides.

### 5. Chain-of-Verification (CoVe)

Draft response -> generate verification questions -> answer them independently (without seeing the draft) -> revise.

- **Paper**: Dhuliawala et al., "Chain-of-Verification Reduces Hallucination" (ACL 2024, arXiv:2309.11495)
- **Takeaway**: The factored design (verification answers don't condition on the draft) avoids confirmation bias. A
  reviewer should re-examine code fresh rather than just re-reading the author's rationale. This suggests that mentor
  prompts should encourage independent reasoning, not parrot back the CL description.

### 6. Debate / Adversarial Review

Two agents argue opposing sides; a judge decides. Rooted in complexity theory (debate can resolve PSPACE-hard problems
with polynomial-time judges).

- **Papers**: Irving et al., "AI safety via debate" (arXiv:1805.00899); "RedDebate" (arXiv:2506.11083)
- **Takeaway**: Most useful for security review or architectural decisions where an adversarial framing surfaces issues
  that cooperative review misses. Too expensive for routine review. Could be a specialized mentor mode for
  security-critical changes.

### 7. Code Review Agents (CodeRabbit, Qodo/PR-Agent, Cursor)

Purpose-built AI tools for PR review combining LLM analysis with static analysis.

- **CodeRabbit**: Most installed AI app on GitHub. 10M+ PRs processed. Per-line comments.
- **Qodo 2.0**: Multi-agent review architecture. Scans for bugs, logic gaps, missing tests, security.
- **Cursor**: AI review in editor + PR review in GitHub.
- **Takeaway**: (1) Review at the diff level, not the whole file. (2) Combine LLM judgment with deterministic checks.
  (3) Make comments actionable. (4) Allow developers to dismiss individual findings. The "talkative" problem (CodeRabbit
  leaves the most comments of any tool) is real -- noise erodes trust.

### 8. Generate-then-Critique Loop (Inner/Outer Loop)

A Writer generates; a Critic evaluates; the loop iterates until approval or max iterations.

- **References**: Google ADK LoopAgent, CGI framework (arXiv:2503.16024), Actor-Critic patterns
- **Takeaway**: 3-5 rounds is the empirical sweet spot. The critic needs a clear rubric and a "STOP" signal. Risk of
  oscillation if the critic keeps finding new issues. Two levels: inner loop for tactical fixes, outer loop for
  strategic concerns.

### 9. Rubric-Based Evaluation

Structured, multi-dimensional scoring criteria rather than single holistic scores.

- **References**: "Rubric Is All You Need" (ACM ICER 2025), PEARL framework, AutoSCORE, Promptfoo LLM Rubric
- **Takeaway**: Decomposing evaluation into dimensions (correctness, security, style, performance, testability,
  maintainability) reduces inconsistency and forces thorough coverage. Multi-agent rubric scoring (one agent per
  dimension) improves reliability. Rubrics should be versioned alongside code standards.

### 10. Naming Conventions

| Name      | Connotation                            | Best fit                             |
| --------- | -------------------------------------- | ------------------------------------ |
| Critic    | Adversarial, flaw-finding              | Security review, adversarial testing |
| Reviewer  | Collaborative improvement              | Routine code review                  |
| Judge     | Authoritative pass/fail                | Gate-keeping, merge decisions        |
| Validator | Correctness-focused, binary            | Schema/contract validation           |
| Evaluator | Scoring, quantitative                  | Benchmarks, metrics                  |
| Mentor    | Teaching, developmental                | Learning loops, episodic feedback    |
| Auditor   | Thorough, checklist-oriented           | Compliance, security                 |
| Verifier  | Proof-oriented, checks specific claims | Formal verification                  |
| Advisor   | Suggestive, non-authoritative          | Optional recommendations             |

## Architecture Recommendation

### Naming: Keep "Reviewer"

"Mentor" implies teaching the _agent_, which isn't the primary function -- these review the _developer's_ code.
"Reviewer" is the most natural term for developers and maps to existing vocabulary (code review, PR review). It's
collaborative without being authoritative, and it's what CodeRabbit, Qodo, and Cursor all use. Reserve "critic" for an
optional adversarial mode, and "judge" for future gate-keeping scenarios.

If the developmental/teaching connotation is important (e.g., you want reviewers to provide explanations that help
developers learn, not just point out issues), then "mentor" remains defensible. But for the core role of "evaluate this
diff and provide feedback," "reviewer" is clearer.

### Structured Output

Replace the current binary PASSED/FAILED with structured review output:

```
ReviewResult:
  verdict: APPROVED | CHANGES_REQUESTED | COMMENTED
  findings: list[Finding]

Finding:
  dimension: str          # e.g., "correctness", "security", "style"
  severity: ERROR | WARNING | INFO
  file: str | None        # file path, if applicable
  line_range: tuple | None
  summary: str            # one-line description
  detail: str             # explanation and suggestion
  actionable: bool        # can the author fix this?
```

This gives developers structured, filterable feedback rather than a monolithic pass/fail. The `dimension` field comes
from the rubric; the `severity` field allows filtering noise.

### Rubric-Driven Review

Each reviewer profile should declare a **rubric** -- an explicit set of dimensions it evaluates, with descriptions of
what constitutes each severity level. This replaces free-form prompts with structured criteria:

```yaml
reviewer_profiles:
  - profile_name: security
    file_globs: ["**/*.py"]
    rubric:
      - dimension: injection
        description: "SQL injection, command injection, template injection"
        error_if: "User input reaches a query/command without sanitization"
        warning_if: "Sanitization exists but is non-standard"
      - dimension: secrets
        description: "Hardcoded credentials, API keys, tokens"
        error_if: "Any hardcoded secret in source code"
    reviewers:
      - name: security_reviewer
        prompt: "#review/security"
```

Benefits: criteria are auditable and versioned, reviewers can be evaluated against their rubric for consistency, and
different profiles can have different rubrics (security review vs. style review vs. correctness review).

### Two-Tier Review Architecture

Separate **fast checks** from **deep review**:

1. **Tier 1 -- Fast Checks** (run immediately, no workspace needed):
   - Diff-level analysis only (no checkout required)
   - Style, naming, obvious bugs, security patterns
   - Uses a smaller/faster model (haiku-tier)
   - Completes in seconds, provides early signal
   - Analogous to linting -- fast, cheap, high-confidence

2. **Tier 2 -- Deep Review** (run after hooks pass, needs workspace):
   - Full codebase context (checks out the code)
   - Correctness, architecture, test coverage, integration concerns
   - Uses a larger model (opus-tier)
   - Takes minutes, provides thorough analysis
   - Analogous to senior engineer review -- slow, expensive, catches subtle issues

This maps naturally to the existing hook prerequisite system: Tier 1 runs in parallel with hooks; Tier 2 waits for hooks
to pass.

### Optional: Iterative Review Loop

For CLs that request it (or for specific profiles), support a generate-then-critique loop:

1. Reviewer evaluates the diff and produces findings
2. If findings include ERRORs, the reviewer (or a paired agent) can propose fixes
3. The author (or automated system) applies fixes and re-triggers review
4. Loop terminates on approval or max iterations (default: 3)

This is opt-in because most reviews should be single-pass (the developer acts on feedback). But for automated
refactoring or AI-generated code, an iterative loop catches more issues.

### Optional: Episodic Memory (Reflexion-Inspired)

Track reviewer observations across revisions of the same CL:

```
ReviewMemory:
  cl_name: str
  observations: list[Observation]

Observation:
  revision: int
  finding: Finding
  resolution: FIXED | WONTFIX | NEW_ISSUE_INTRODUCED
```

This lets the reviewer say "In v1, I flagged a race condition in `process_batch()`. In v2, the author added a lock but
introduced a deadlock risk." This is the "mentor" value-add: continuity across revisions.

### Status Lifecycle

Expand the status set to reflect the richer lifecycle:

```
QUEUED -> RUNNING -> APPROVED | CHANGES_REQUESTED | COMMENTED | FAILED | KILLED
                                                                  ^
                                                                  |
                                                          (infrastructure failure,
                                                           not a review judgment)
```

- **QUEUED**: Profile matched, waiting for prerequisites
- **RUNNING**: Reviewer agent is active
- **APPROVED**: No ERROR-level findings
- **CHANGES_REQUESTED**: At least one ERROR-level finding
- **COMMENTED**: Only WARNING/INFO findings (no blockers)
- **FAILED**: Infrastructure failure (agent crashed, timeout)
- **KILLED**: Superseded by new revision

This distinguishes between "the reviewer found problems" (CHANGES_REQUESTED) and "the reviewer itself failed" (FAILED),
which the current PASSED/FAILED conflates.

### Configuration Schema

```yaml
reviewer_profiles:
  - profile_name: python_style
    tier: 1 # fast check (diff-only)
    model_tier: small # haiku-class
    file_globs: ["**/*.py"]
    rubric:
      - dimension: style
        description: "PEP 8, project conventions"
      - dimension: naming
        description: "Clear, consistent naming"
    reviewers:
      - name: style_check
        prompt: "#review/python_style"

  - profile_name: security
    tier: 2 # deep review (workspace)
    model_tier: large # opus-class
    file_globs: ["**/*.py"]
    diff_regexes: ["subprocess", "eval\\(", "exec\\(", "sql", "query"]
    rubric:
      - dimension: injection
      - dimension: secrets
      - dimension: auth
    reviewers:
      - name: security_review
        prompt: "#review/security"

  - profile_name: architecture
    tier: 2
    model_tier: large
    first_commit: true # only on initial CL creation
    iterative: false # single-pass only
    reviewers:
      - name: arch_review
        prompt: "#review/architecture"
```

### Migration Path

1. **Rename**: `mentor` -> `reviewer` across the codebase (config, models, scheduler, TUI, xprompts)
2. **Add structured output**: Introduce `ReviewResult`/`Finding` models alongside current status lines
3. **Add rubric support**: Extend profile config with rubric definitions
4. **Add tier support**: Split into Tier 1 (diff-only) and Tier 2 (workspace) with separate scheduling
5. **Expand statuses**: QUEUED, APPROVED, CHANGES_REQUESTED, COMMENTED
6. **Optional**: Add episodic memory for cross-revision continuity
7. **Optional**: Add iterative review loop for automated code

Steps 1-3 can be done incrementally without breaking the existing system. Steps 4-5 require scheduler changes. Steps 6-7
are additive features.
