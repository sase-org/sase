# Research: Best Practices for XPrompt YAML Workflows

## Goal

Define practical, high-confidence best practices for `xprompt` YAML workflows in `sase`, based on:

1. How `sase` workflows currently behave.
2. Prior art from mature workflow/orchestration systems.

This focuses on authoring quality, correctness, safety, and long-term maintainability.

## Current `sase` Workflow Capabilities (What We Must Design For)

From `docs/workflow_spec.md` and `src/sase/xprompt/*`:

- Workflows support typed `input`, step-local `output` schemas, `if`, `for`, `repeat`, `while`, and `parallel`.
- Step kinds are mutually exclusive: exactly one of `agent`, `bash`, `python`, `prompt_part`, or `parallel`.
- `prompt_part` has strict constraints (no loops/conditions/output/hitl on that step).
- Loops require explicit bounds (`repeat.max` defaults to 100; `while` also bounded via max iterations).
- Parallel blocks require at least 2 nested steps and unique nested names.
- Outputs are parsed with fallbacks (JSON -> key/value -> raw text), which is flexible but can hide schema drift.

Implication: we should bias toward explicit contracts and deterministic control flow so workflows remain debuggable as
they get more complex.

## Prior Art Findings

### 1. Strong interfaces between workflow units

- GitHub Actions reusable workflows require typed inputs (`boolean`/`number`/`string`) and typed compatibility between
  caller/callee inputs and outputs.
- GitHub also treats outputs as explicit cross-job interfaces.
- LangGraph emphasizes explicit state shape and node boundaries.

Takeaway for xprompt: treat each step output as an API contract; avoid implicit coupling via ad-hoc text.

## 2. Explicit dependency and control-flow semantics

- GitHub Actions `needs` enforces dependency order and failure propagation unless explicitly overridden.
- Concurrency groups in GitHub Actions make cancellation/serialization behavior explicit.
- LangGraph recommends mapping workflows into discrete nodes with explicit edges/routing.

Takeaway for xprompt: keep DAG intent obvious in YAML; avoid hidden dependencies through side effects.

### 3. Idempotency and retry-aware design

- Airflow explicitly recommends treating tasks like DB transactions: no partial outputs, idempotent reruns, avoid
  nondeterministic reads/writes.
- Prefect documents granular retries, backoff, jitter, and scoped retries at task level.
- LangGraph separates transient errors (retry), LLM-recoverable errors (loop with context), user-fixable errors
  (interrupt/HITL), and unexpected errors (bubble up).

Takeaway for xprompt: write steps assuming retries/re-execution can happen; model error classes explicitly.

### 4. Security and trust boundaries in workflow DSLs

- GitHub security guidance emphasizes least privilege, explicit permission scope, pinned dependencies, and careful
  handling of untrusted input in scripts.
- Script-injection guidance favors passing untrusted data via intermediate variables rather than interpolating directly
  into scripts.

Takeaway for xprompt: shell/python steps are trust boundaries; template interpolation should be minimized and
quoted/serialized defensively.

### 5. Human-in-the-loop and observability are first-class

- LangGraph treats interrupts/checkpointed human review as a core orchestration capability.
- Prefect and Airflow both emphasize state visibility and testability.
- `sase` already provides explain/graph/trace tooling (`sase xprompt explain`, `graph`, `expand --trace`).

Takeaway for xprompt: design workflows so humans can inspect state transitions quickly, especially around approvals and
loops.

## Recommended Best Practices for XPrompt YAML

### A. Treat inputs/outputs as contracts

- Always declare `input` types for non-trivial workflows.
- Always declare `output` schemas for `agent`, `bash`, and `python` steps.
- Prefer structured fields over `_raw`/free text for downstream references.
- Keep output field names stable; treat renames as breaking changes.

### B. Keep steps single-purpose and typed

- One step should do one thing: fetch, transform, decide, or act.
- Separate decision steps from side-effect steps.
- For effectful steps (git operations, API writes), include explicit success/error fields in `output`.

### C. Make control flow obvious

- Use explicit step names (`resolve_conflicts`, `publish_report`) instead of generic (`step1`).
- Keep `if` conditions simple and data-driven.
- Prefer short, bounded loops with clear stop conditions and explicit max.
- Use `join` intentionally:
  - `array` for aggregation
  - `object` for keyed fan-in
  - `lastOf` only when "latest wins" is truly intended

### D. Engineer for retries and replay safety

- Avoid nondeterministic behavior in critical logic (time-dependent branching, mutable global state).
- Make external writes idempotent where possible (upsert-style semantics, dedup keys).
- Ensure partial failures are representable (e.g., `success=false`, `error=...`) and handled by later steps.

### E. Harden shell/python boundaries

- Prefer `tojson` when embedding values into `python` steps.
- In `bash`, pass dynamic values through environment variables or robust quoting, not raw string interpolation.
- Never embed secrets in workflow text or outputs; keep secret material outside prompt-visible channels.

### F. Use HITL deliberately

- Add `hitl: true` only at high-leverage review points (before irreversible actions).
- Include enough structured context in prior step outputs so a reviewer can decide quickly.
- Avoid HITL inside noisy loops; gate once per phase when possible.

### G. Optimize for debuggability

- Keep hidden steps (`hidden: true`) for setup/plumbing only.
- Ensure every major phase leaves a clear, typed artifact in context.
- Validate new workflows with:
  - `sase xprompt explain <workflow>`
  - `sase xprompt graph <workflow>`
  - targeted end-to-end runs in agent mode.

## Suggested Authoring Template

```yaml
name: example_workflow
input:
  task: line
  dry_run: { type: bool, default: true }

steps:
  - name: plan
    agent: |
      Create a concise execution plan for: {{ task }}
    output: { summary: text, risk_level: word }

  - name: approve_plan
    if: "{{ not dry_run }}"
    hitl: true
    agent: |
      Review plan:
      {{ plan.summary }}
    output: { approved: bool, notes: text }

  - name: execute
    if: "{{ dry_run or approve_plan.approved }}"
    python: |
      # Execute idempotently; return explicit status
      print("success=true")
      print("result=done")
    output: { success: bool, result: line }

  - name: report
    agent: |
      Summarize outcome.
      success={{ execute.success }}
      result={{ execute.result }}
    output: { summary: text }
```

## Gaps Worth Addressing in `sase` (Future Improvements)

1. Strict output mode: option to fail if declared schema is not satisfied exactly (no permissive text fallback).
2. Native retry/backoff policy per step (especially `bash`/`python`/network-heavy `agent` calls).
3. Step timeouts and cancellation policy.
4. First-class secret/input sensitivity annotations to prevent accidental prompt/log leakage.
5. Optional lint rules for workflow style (naming, explicit outputs, bounded loops, side-effect gating).

## Source Notes

### `sase` internals and docs

- `docs/workflow_spec.md`
- `docs/xprompt.md`
- `src/sase/xprompt/workflow_loader_parse.py`
- `src/sase/xprompt/workflow_models.py`
- `src/sase/xprompts/sync.yml`
- `src/sase/xprompts/git.yml`

### External prior art

- GitHub Actions workflow syntax:
  - https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- GitHub Actions secure use guidance:
  - https://docs.github.com/en/actions/reference/security/secure-use
- Apache Airflow best practices:
  - https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html
- Prefect workflow retries:
  - https://docs.prefect.io/v3/how-to-guides/workflows/retries
- Prefect task caching:
  - https://docs.prefect.io/v3/how-to-guides/workflows/cache-workflow-steps
- LangGraph overview:
  - https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph workflow patterns:
  - https://docs.langchain.com/oss/python/langgraph/workflows-agents
- LangGraph "Thinking in LangGraph":
  - https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph

## Bottom Line

For `xprompt` YAML workflows, the winning pattern is: explicit contracts, bounded control flow, idempotent side effects,
hardened interpolation boundaries, and sparse/high-value HITL checkpoints. This is the common thread across mature
workflow systems and aligns with `sase`'s current execution model.
