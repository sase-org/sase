# Research: Best Practices for XPrompt YAML Workflows

## Motivation

XPrompt workflows are the primary orchestration primitive in SASE. They let you compose multi-step agent interactions
with bash/python automation, control flow, data passing, and human-in-the-loop checkpoints -- all in declarative YAML.
Getting the workflow design right matters disproportionately: workflows are the unit of reuse, the interface between
humans and agents, and the thing that determines whether a complex task succeeds or fails silently. This document
examines our current patterns, surveys prior art, and distills best practices.

---

## Current State: Patterns in Existing Workflows

### What We Have Today

| Workflow       | Steps | Pattern                                   | Notable Features                            |
| -------------- | ----- | ----------------------------------------- | ------------------------------------------- |
| `gcommit.yml`  | 5     | Embedded (prompt_part + post-steps)       | Conditional chains, VCS detection           |
| `gchange.yml`  | 7     | Embedded (prompt_part + post-steps)       | Branch creation, push, changespec creation  |
| `gpropose.yml` | 5     | Embedded (prompt_part + post-steps)       | PR creation, branch detection               |
| `sync.yml`     | 4     | Standalone with agent step                | repeat/until loop for conflict resolution   |
| `git.yml`      | 5     | wraps_all workspace setup                 | Checkout, stash, release, diff              |
| `file.yml`     | 3     | Embedded (prompt_part for file output)    | Path generation, post-verification          |
| `resume.yml`   | 3     | Embedded (prompt_part for history replay) | Agent name resolution, chat history loading |
| `eval_*.yml`   | 3-5   | Test/eval harnesses                       | Demonstrate control flow primitives         |

### Recurring Patterns

**1. The "embedded wrapper" pattern** (gcommit, gchange, gpropose, file, resume): A `prompt_part` step injects
instructions into the agent prompt, pre-steps gather context, and post-steps act on the agent's work. This is the most
common pattern and the one most workflow authors will reach for.

**2. The "infrastructure wrapper" pattern** (git.yml): Uses `wraps_all: true` to set up and tear down workspace state
around all other embedded workflows. The `prompt_part` is empty -- it exists purely to establish the pre/post boundary.

**3. The "autonomous agent" pattern** (sync.yml): Uses `agent:` steps with structured output and control flow (repeat
loops) to let an agent work autonomously until a condition is met.

**4. The "check-then-act" idiom**: Nearly every workflow follows `check_changes → if has_changes → do_thing`. This is
defensive and good.

### Current Pain Points

1. **Boilerplate in VCS detection**: The `check_changes` python step is copy-pasted across gcommit, gchange, and
   gpropose with identical code. This violates DRY within the workflow system.

2. **sys.path manipulation**: Several python steps manually insert `~/lib/sase/src` into sys.path. This is fragile and
   should be unnecessary if the workflow executor sets up the environment correctly.

3. **Long inline scripts**: `gchange.yml` has a 40-line python step for changespec creation. At this length, the logic
   should live in a proper Python module (like sync.yml does with `sase.scripts.sync_setup`).

4. **No type safety across step boundaries**: When step A outputs `{path: path}` and step B uses `{{ A.path }}`, there
   is no compile-time check that the referenced field exists in A's output schema.

---

## Prior Art: How Other Systems Approach Workflows

### GitHub Actions

GitHub Actions is the most widely-used YAML workflow system. Key design decisions:

- **Explicit dependency via `needs:`** — Steps (jobs) declare which other jobs they depend on. No implicit ordering from
  position in the file. This makes data flow explicit but adds verbosity.
- **Expressions with `${{ }}`** — Similar to our Jinja2 `{{ }}` syntax. References like `${{ steps.build.outputs.tag }}`
  mirror our `{{ build.tag }}` pattern.
- **Matrix strategies** — Declarative fan-out (`matrix: {os: [ubuntu, macos], python: [3.11, 3.12]}`). We have `for:`
  loops and `parallel:` but no matrix equivalent.
- **Reusable workflows** — Workflows can call other workflows with `uses:`. Our `#name` embedding is analogous but more
  tightly integrated (xprompts can be both standalone and embedded).
- **Conditionals with `if:`** — Same pattern as ours. They allow any expression, we use Jinja2.

**Lessons**: The `needs:` pattern for explicit dependencies is worth considering for complex workflows where step
ordering matters for correctness, not just convenience. However, for most agent workflows (which are inherently
sequential), implicit ordering from position is simpler and correct.

### Temporal Workflows

Temporal is a workflow orchestration engine used for durable, long-running workflows:

- **Activities vs Workflows** — Clean separation between orchestration logic (workflows) and side-effectful work
  (activities). Our `agent:`/`bash:`/`python:` step types serve a similar role to activities.
- **Durable execution** — Workflows survive process crashes via event sourcing. We have `WorkflowState` serialization
  but no automatic recovery from mid-workflow failures.
- **Signals and queries** — External systems can send data into running workflows. Our `hitl:` is a limited version
  (human sends approve/reject). There's no general mechanism for injecting data mid-workflow.
- **Child workflows** — Workflows can spawn sub-workflows. We have xprompt embedding but not runtime sub-workflow
  spawning.
- **Retry policies** — Per-activity retry configuration. Our `repeat:` loop is manual retry; there's no declarative
  retry-on-failure.

**Lessons**: The activity/workflow separation suggests that our python/bash steps that grow long should be refactored
into proper modules (activities) that are merely invoked from the workflow. Temporal's retry policies suggest we could
benefit from a `retry:` config on steps (distinct from `repeat:`, which is for logical loops, not failure recovery).

### Argo Workflows (Kubernetes)

Argo is a Kubernetes-native workflow engine:

- **DAG mode** — Steps declare dependencies and the engine figures out parallelism. More powerful than our explicit
  `parallel:` blocks but harder to read.
- **Artifacts** — First-class file passing between steps. Steps produce artifacts (files) that other steps consume. We
  pass data via `key=value` stdout parsing, which works for small values but breaks down for large outputs.
- **Templates** — Reusable step definitions parameterized by inputs. Our `xprompts:` (workflow-local) serve a similar
  role but are limited to content injection, not full step reuse.
- **Exit handlers** — Steps that run regardless of workflow success/failure. We have no equivalent; a workflow that
  fails mid-way leaves no cleanup opportunity.

**Lessons**: Exit/cleanup handlers would be valuable for workflows like `git.yml` that modify workspace state. If the
agent step fails, the stash is never popped and the branch is never restored. An `on_failure:` or `finally:` block would
address this.

### Prefect / Dagster (Data Pipelines)

Modern data pipeline orchestrators:

- **Task decorators** — Define tasks as annotated Python functions, compose them in a flow function. The workflow is
  Python code, not YAML. This is more flexible but less declarative.
- **Typed inputs/outputs** — Full Python type system for task I/O, with runtime validation. Our type system
  (word/line/text/path/int/bool/float) is simpler but sufficient for agent-oriented workflows.
- **Caching** — Tasks can be cached by input hash. Repeated runs skip completed steps. We have implicit step inputs
  (provide `step_name=@file.json` to skip), which is a manual version of this.
- **Observability** — Rich UI for monitoring running workflows, viewing logs, retrying failed tasks. Our TUI shows
  workflow progress but lacks deep observability (no per-step logs, timing, or retry history).

**Lessons**: The implicit step input pattern (skip a step by providing its output directly) is already a form of
caching. Making this more discoverable and documenting it as a pattern would help workflow authors build more debuggable
workflows.

### LangGraph / CrewAI (Agent Orchestration)

These are the closest prior art -- agent orchestration frameworks:

- **LangGraph** — Models agent workflows as state machines with typed state. Nodes are functions that transform state,
  edges are conditional transitions. More explicit about state shape than our context dict.
- **CrewAI** — Defines agents with roles and tasks. Tasks have expected outputs, tools, and delegation rules. Higher
  abstraction level than our step-based model.
- **AutoGen** — Multi-agent conversations where agents take turns. The conversation itself is the orchestration
  primitive. Different paradigm from our sequential step model.

**Lessons**: LangGraph's typed state is the strongest signal. Our workflow context is an untyped dict that accumulates
step outputs. Making the context shape explicit (what keys exist after step N) would catch more errors at validation
time. The validator already checks variable references; extending it to check field-level references against output
schemas would be the next step.

---

## Best Practices

### 1. Keep Steps Small and Focused

Each step should do one thing. If a step is more than ~15 lines of inline code, extract it into a Python module and call
it:

```yaml
# Bad: 40 lines of inline Python
- name: create_changespec
  python: |
    import json
    import os
    import subprocess
    # ... 37 more lines ...

# Good: delegate to a module
- name: create_changespec
  python: |
    from sase.scripts.create_changespec import main
    main(
        project_name={{ setup.project_name | tojson }},
        branch_name={{ create_branch.branch | tojson }},
    )
  output: { success: bool, changespec_name: word, error: text }
```

This mirrors Temporal's activity/workflow separation. The YAML defines orchestration; Python modules do the work.

### 2. Use the Check-Then-Act Pattern

Guard side-effectful steps with conditions. Don't assume prior steps succeeded:

```yaml
- name: check
  bash: echo "ready={{ 'true' if condition else 'false' }}"
  output: { ready: bool }

- name: act
  if: "{{ check.ready }}"
  bash: do_the_thing
```

This is already the dominant pattern in our workflows (check_changes → commit → push). Codify it as the standard.

### 3. Design Output Schemas as Contracts

Every step with side effects should declare an output schema. The schema is the contract between steps:

```yaml
# Good: explicit contract
- name: build
  bash: ...
  output: { artifact_path: path, version: word, success: bool }

# Bad: no output, downstream steps can't depend on it
- name: build
  bash: ...
```

Include `success: bool` and `error: text` fields in any step that can fail. This gives downstream `if:` conditions
something to check.

### 4. Prefer `hidden: true` for Infrastructure Steps

Steps that exist for plumbing (checking state, saving temp files, generating paths) should be `hidden: true`. This keeps
the TUI agent view clean, showing only the steps that matter to the user:

```yaml
- name: check_changes
  hidden: true # User doesn't need to see this
  python: ...
  output: { has_changes: bool }
```

The general rule: if a step doesn't involve agent interaction or produce user-visible output, hide it.

### 5. Use Workflow-Local XPrompts for Repeated Content

When multiple agent steps in a workflow share instructions, define them as workflow-local xprompts rather than
duplicating text:

```yaml
xprompts:
  _output_format: |
    Format your response as:
    - summary: one-line summary
    - details: full explanation

steps:
  - name: analyze
    agent: |
      Analyze the code in {{ file_path }}.
      #_output_format
    output: { summary: line, details: text }
```

Workflow-local xprompt names must start with `_` (enforced by the validator).

### 6. Structure Data Flow Explicitly

Avoid passing large blobs of unstructured text between steps. Use typed output fields:

```yaml
# Bad: passing raw text and hoping downstream can parse it
- name: gather
  bash: git log --oneline -10
  output: { log: text }

# Good: structured output
- name: gather
  python: |
    import subprocess
    result = subprocess.run(["git", "log", "--oneline", "-5"], capture_output=True, text=True)
    lines = result.stdout.strip().split("\n")
    print(f"count={len(lines)}")
    print(f"latest_sha={lines[0].split()[0] if lines else ''}")
  output: { count: int, latest_sha: word }
```

The rule of thumb: if downstream steps only need specific fields, extract those fields rather than passing the raw
output.

### 7. Use `repeat:` for Convergence, Not Retry

The `repeat:` loop is for agent tasks that iteratively converge on a solution (like conflict resolution in sync.yml).
For retrying failed operations, use explicit error checking:

```yaml
# Good use of repeat: convergence loop
- name: resolve_conflicts
  repeat:
    until: "{{ resolve_conflicts.all_resolved }}"
    max: 20
  agent: |
    Resolve the remaining merge conflicts...
  output: { all_resolved: bool }
# For retry-on-failure, use if + manual loop
# (Consider proposing a retry: primitive if this becomes common)
```

### 8. Document Workflow Intent, Not Mechanics

Add a comment at the top of the workflow explaining what it does and when to use it -- not how each step works (that
should be self-evident from the YAML):

```yaml
# Commits changes made by an embedded agent prompt.
# Embeddable: yes (prompt_part injects "don't commit" instruction)
# Inputs: who (committer), note (commit message annotation)
input:
  - name: who
    type: line
    default: "man"
```

### 9. Leverage Implicit Step Inputs for Debugging

Steps with output schemas automatically generate optional workflow inputs. This means you can skip expensive steps by
providing their output directly:

```bash
# Skip the setup step by providing its output
sase run my_workflow --setup '{"vcs_type": "git", "branch_name": "main", "cwd": "/tmp/test"}'
```

Design output schemas with this in mind. If a step's output is self-contained and serializable, it can be mocked for
testing.

### 10. Avoid sys.path Hacks in Python Steps

If you need to import sase modules, they should be available without sys.path manipulation. If they're not, that's a bug
in the executor environment, not something to work around in the workflow:

```yaml
# Bad
- name: check
  python: |
    import sys, os
    sys.path.insert(0, os.path.join(os.path.expanduser('~'), 'lib', 'sase', 'src'))
    from sase.vcs_provider import get_vcs_provider
    ...

# Good (executor should set up the environment)
- name: check
  python: |
    from sase.vcs_provider import get_vcs_provider
    ...
```

---

## Design Gaps and Potential Improvements

### 1. Step Reuse / Shared Steps

The most obvious gap: the `check_changes` python step is duplicated verbatim across gcommit, gchange, and gpropose.
There's no mechanism to define a reusable step that multiple workflows can share.

**Possible solutions**:

- **Step imports**: `- use: shared/check_changes` syntax that inlines a step definition from another file
- **Workflow composition**: Allow workflows to call other workflows as steps (not just embed via prompt_part)
- **Workflow-local xprompts for python**: Allow xprompts to define step behavior, not just content

The simplest fix that fits the current model: extract shared steps into standalone workflows with only bash/python steps
(no prompt_part), and call them as sub-workflows.

### 2. Error Handling / Cleanup

There's no `finally:` or `on_failure:` mechanism. If `git.yml`'s agent step fails, the stash is never popped. Options:

```yaml
# Proposed: finally block
steps:
  - name: setup
    bash: git stash push -m "workflow"

  - name: inject
    prompt_part: ""

  - name: cleanup # Runs even if agent step fails
    finally: true
    bash: git stash pop
```

### 3. Retry vs. Repeat Distinction

`repeat:` is a do-while loop for convergence. There's no declarative retry-on-failure:

```yaml
# Proposed: retry primitive
- name: flaky_api_call
  retry:
    max: 3
    backoff: exponential
  bash: curl https://api.example.com/deploy
  output: { status: word }
```

This would be distinct from `repeat:` (which re-runs the step body with a new condition check) -- `retry:` would re-run
the step only if it fails (non-zero exit / exception).

### 4. Cross-Step Type Checking

The validator checks that referenced step names exist but doesn't verify that referenced fields exist in the step's
output schema. This would catch typos:

```yaml
- name: build
  output: { artifact_path: path }

- name: deploy
  bash: deploy {{ build.atrifact_path }} # Typo! Should be artifact_path
  # Validator should catch this ^^^
```

### 5. Artifact Passing

The `key=value` stdout protocol works for small structured values but doesn't handle binary data, large files, or
multi-line values gracefully. Steps that produce files currently use temp files and pass paths:

```yaml
- name: generate
  bash: |
    tmpfile=$(mktemp)
    generate_report > "$tmpfile"
    echo "report_path=$tmpfile"
  output: { report_path: path }
```

A first-class artifact mechanism could simplify this:

```yaml
- name: generate
  bash: generate_report
  artifacts:
    report: stdout # Capture stdout as named artifact
```

---

## Summary of Recommendations

| Priority | Practice                                    | Status in Codebase      |
| -------- | ------------------------------------------- | ----------------------- |
| P0       | Keep steps small, extract to Python modules | Partially followed      |
| P0       | Check-then-act pattern for side effects     | Consistently followed   |
| P0       | Declare output schemas as contracts         | Consistently followed   |
| P1       | Use `hidden: true` for infrastructure steps | Consistently followed   |
| P1       | Avoid sys.path hacks                        | Not followed (3 files)  |
| P1       | Structure data flow with typed fields       | Mostly followed         |
| P2       | Workflow-local xprompts for shared content  | Available but underused |
| P2       | Document workflow intent at top of file     | Not currently done      |
| P2       | Design outputs for implicit input / mocking | Implicitly done         |

### Design Improvements to Consider

| Priority | Improvement                  | Effort | Impact                                      |
| -------- | ---------------------------- | ------ | ------------------------------------------- |
| P1       | Step reuse / shared steps    | Medium | Eliminates duplication across git workflows |
| P1       | finally/on_failure blocks    | Medium | Prevents resource leaks on failure          |
| P2       | Cross-step field validation  | Small  | Catches typos at compile time               |
| P2       | retry: primitive             | Small  | Cleaner failure recovery than manual loops  |
| P3       | First-class artifact passing | Large  | Better for file-heavy workflows             |
| P3       | DAG-based step ordering      | Large  | Only needed if workflows get more complex   |
