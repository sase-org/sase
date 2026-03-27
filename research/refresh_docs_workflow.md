# Design Research: `#sase/refresh_docs` Xprompt Workflow

## Goal

Create a workflow invoked as `#sase/refresh_docs` that:

1. Checks how many git commits have been made since its last run
2. If the count is >= 10, runs the existing `#docs` xprompt (which triggers a documentation review and update)
3. If < 10 commits, exits early with no action

## Key Constraints

- **No built-in cross-run state**: Xprompt workflows persist state during execution (`workflow_state.json` in the
  artifacts dir), but there is no built-in mechanism for tracking state _between_ separate invocations of a workflow.
- **`#docs` is a prompt_part**: The `docs` xprompt is defined as a string in `sase.yml`, making it a `prompt_part` (not
  a multi-step workflow). It can be embedded in an `agent` step's prompt.
- **Workflow location**: To be invocable as `#sase/refresh_docs`, the workflow file should be placed at
  `xprompts/refresh_docs.yml` in the project root (CWD-local workflows get namespaced with the project name `sase/`).

## Design Alternatives

### Alternative 1: Marker File with Commit Hash

Store the HEAD commit SHA after each successful run in a file at a well-known path. On the next run, count commits
between the stored SHA and current HEAD using `git rev-list --count`.

```yaml
steps:
  - name: count_commits
    python: |
      import os
      from pathlib import Path
      import subprocess

      marker = Path.home() / ".sase" / "projects" / "sase" / "refresh_docs_marker"
      head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()

      if marker.exists():
          last_sha = marker.read_text().strip()
          # Verify the stored SHA still exists in history (handles force-pushes)
          check = subprocess.run(["git", "cat-file", "-t", last_sha], capture_output=True)
          if check.returncode == 0:
              result = subprocess.check_output(
                  ["git", "rev-list", "--count", f"{last_sha}..HEAD"], text=True
              )
              count = int(result.strip())
          else:
              count = 999  # SHA no longer valid, force a refresh
      else:
          count = 999  # First run, force a refresh

      print(f"count={count}")
      print(f"head={head}")
    output:
      count: int
      head: line

  - name: run_docs
    if: "{{ count_commits.count >= 10 }}"
    agent: |
      #docs

  - name: update_marker
    if: "{{ count_commits.count >= 10 }}"
    python: |
      from pathlib import Path
      marker = Path.home() / ".sase" / "projects" / "sase" / "refresh_docs_marker"
      marker.parent.mkdir(parents=True, exist_ok=True)
      marker.write_text("{{ count_commits.head }}")
      print("updated=true")
    output: { updated: bool }
```

**Pros:**

- Simple and reliable; `git rev-list --count` is a standard operation
- Commit hash is the most precise anchor: exactly matches what was the repo state at last run
- Handles force-pushes gracefully (falls back to "force refresh" if stored SHA is gone)
- State lives in `~/.sase/projects/sase/`, consistent with existing sase state patterns

**Cons:**

- Introduces a new state file outside the repo
- The marker path is hardcoded to the project name `sase` — would need parameterization for reuse in other projects
- If the workflow is interrupted after `run_docs` but before `update_marker`, the marker won't update (though using
  `finally:` could mitigate this)

---

### Alternative 2: Timestamp-Based with `git log --after`

Store a UTC timestamp instead of a commit hash. Count commits using `git log --after=<timestamp> --oneline | wc -l`.

```yaml
steps:
  - name: count_commits
    bash: |
      MARKER="$HOME/.sase/projects/sase/refresh_docs_ts"
      if [ -f "$MARKER" ]; then
        LAST_TS=$(cat "$MARKER")
        COUNT=$(git log --after="$LAST_TS" --oneline | wc -l)
      else
        COUNT=999
      fi
      echo "count=$COUNT"
    output: { count: int }

  - name: run_docs
    if: "{{ count_commits.count >= 10 }}"
    agent: |
      #docs

  - name: update_marker
    if: "{{ count_commits.count >= 10 }}"
    bash: |
      MARKER="$HOME/.sase/projects/sase/refresh_docs_ts"
      mkdir -p "$(dirname "$MARKER")"
      date -u +"%Y-%m-%dT%H:%M:%SZ" > "$MARKER"
      echo "updated=true"
    output: { updated: bool }
```

**Pros:**

- Survives force-pushes and history rewrites (timestamps are independent of commit graph)
- Simpler logic — no need to validate whether a stored SHA still exists

**Cons:**

- Time zones and clock skew can cause off-by-one issues (commit timestamps ≠ author dates ≠ wall clock)
- `git log --after` uses _author date_ by default, which may not match chronological commit order
- Less precise than commit hash — a rebase that replays old commits with old author dates could produce misleading
  counts

---

### Alternative 3: Lightweight Git Tag

Create a lightweight tag (e.g., `_docs-refresh-marker`) pointing to HEAD after each run. Count commits between the tag
and HEAD.

```yaml
steps:
  - name: count_commits
    bash: |
      if git rev-parse _docs-refresh-marker >/dev/null 2>&1; then
        COUNT=$(git rev-list --count _docs-refresh-marker..HEAD)
      else
        COUNT=999
      fi
      echo "count=$COUNT"
    output: { count: int }

  - name: run_docs
    if: "{{ count_commits.count >= 10 }}"
    agent: |
      #docs

  - name: update_marker
    if: "{{ count_commits.count >= 10 }}"
    bash: |
      git tag -f _docs-refresh-marker HEAD
      echo "updated=true"
    output: { updated: bool }
```

**Pros:**

- State lives _inside_ the repo — no external files to manage
- Can be pushed to remote (`git push origin _docs-refresh-marker`) so it's shared across clones
- Very clean implementation: just 3 git commands total

**Cons:**

- Pollutes the tag namespace — visible in `git tag -l`, UIs, and CI
- Tags can be accidentally deleted or overwritten by anyone with push access
- `git tag -f` is a force operation (though it's on a marker tag, not a release tag)
- Force-pushes that rewrite history past the tagged commit break `rev-list` (same as Alternative 1)
- Underscore-prefixed tag is a convention, not a guarantee of isolation

---

### Alternative 4: Git Notes

Use `git notes` to annotate the commit where docs were last refreshed. Search for the most recent note to find the
anchor point.

```yaml
steps:
  - name: count_commits
    bash: |
      LAST=$(git log --notes=refs/notes/docs-refresh --format='%H' \
             --grep='docs-refreshed' --all -1 2>/dev/null || true)
      if [ -n "$LAST" ]; then
        COUNT=$(git rev-list --count "$LAST"..HEAD)
      else
        COUNT=999
      fi
      echo "count=$COUNT"
    output: { count: int }

  - name: run_docs
    if: "{{ count_commits.count >= 10 }}"
    agent: |
      #docs

  - name: update_marker
    if: "{{ count_commits.count >= 10 }}"
    bash: |
      git notes --ref=refs/notes/docs-refresh add -f -m "docs-refreshed" HEAD
      echo "updated=true"
    output: { updated: bool }
```

**Pros:**

- Metadata lives in the git object store — semantically clean
- Notes are per-ref namespace, so `docs-refresh` won't collide with other notes
- Can be pushed: `git push origin refs/notes/docs-refresh`

**Cons:**

- Git notes are obscure — most developers rarely use them, making debugging harder
- Notes are not fetched by default (`git fetch` ignores notes unless configured)
- Notes are fragile across rebases: if the annotated commit is rewritten, the note is orphaned
- More complex to query than a simple tag or file

---

### Alternative 5: Axe Chop (Scheduled Background Task)

Instead of a standalone workflow, implement this as a chop in the axe scheduler. Axe already tracks
`chop_timestamps.json` per lumberjack, providing built-in "last run" tracking.

```yaml
# In sase config, under a lumberjack definition:
chops:
  - name: refresh_docs
    run_every: 3600 # Check every hour
    bash: |
      COUNT=$(git rev-list --count HEAD~10..HEAD 2>/dev/null || echo 0)
      if [ "$COUNT" -ge 10 ]; then
        sase xprompt expand docs | sase agent run --stdin
      fi
```

**Pros:**

- Leverages existing axe scheduler infrastructure and timestamp tracking
- Runs automatically without manual invocation
- `run_every` provides natural rate limiting

**Cons:**

- Not invocable as `#sase/refresh_docs` — changes the UX model entirely
- Ties documentation refresh to the axe scheduler being running
- Loses the "check since last docs refresh" semantic — just checks "are there 10 recent commits?" which is different
- The chop model is designed for lightweight background tasks, not full agent-driven doc rewrites
- Would need significant changes to work as a standalone invocable workflow

---

### Alternative 6: Hybrid — Workflow with Configurable State Backend

Design the workflow to accept an optional input specifying where to store state, defaulting to the `~/.sase/` path. This
makes it reusable across projects.

```yaml
input:
  - name: threshold
    type: int
    default: 10
  - name: marker_path
    type: path
    default: UNSET # Auto-detected from project

steps:
  - name: resolve_marker
    python: |
      import os
      from pathlib import Path
      from sase.config import detect_project

      marker_path = os.environ.get("MARKER_PATH", "")
      if not marker_path or marker_path == "UNSET":
          project = detect_project() or "default"
          marker_path = str(Path.home() / ".sase" / "projects" / project / "refresh_docs_marker")

      print(f"marker_path={marker_path}")
    output: { marker_path: path }

  - name: count_commits
    python: |
      # ... (same as Alt 1, but using {{ resolve_marker.marker_path }})
    output:
      count: int
      head: line

  - name: run_docs
    if: "{{ count_commits.count >= threshold }}"
    agent: |
      #docs

  - name: update_marker
    if: "{{ count_commits.count >= threshold }}"
    python: |
      from pathlib import Path
      marker = Path("{{ resolve_marker.marker_path }}")
      marker.parent.mkdir(parents=True, exist_ok=True)
      marker.write_text("{{ count_commits.head }}")
      print("updated=true")
    output: { updated: bool }
```

**Pros:**

- Reusable across projects without modification
- Configurable threshold
- Auto-detects project name for state path

**Cons:**

- More complex than necessary if this is only for the sase project
- Extra step for marker resolution adds overhead
- The `detect_project()` import couples the workflow to sase internals

---

## Comparison Matrix

| Criterion                     | Alt 1: Commit Hash | Alt 2: Timestamp | Alt 3: Git Tag | Alt 4: Git Notes | Alt 5: Axe Chop | Alt 6: Hybrid |
| ----------------------------- | :----------------: | :--------------: | :------------: | :--------------: | :-------------: | :-----------: |
| Precision                     |        High        |      Medium      |      High      |       High       |       Low       |     High      |
| Simplicity                    |        High        |       High       |      High      |       Low        |     Medium      |      Low      |
| Survives force-push           | Graceful fallback  |       Yes        |       No       |        No        |       N/A       |   Graceful    |
| No external state             |         No         |        No        |      Yes       |       Yes        |       Yes       |      No       |
| Invocable as `#sase/...`      |        Yes         |       Yes        |      Yes       |       Yes        |       No        |      Yes      |
| Reusable across projects      |       Manual       |      Manual      |     Manual     |      Manual      |     Manual      |      Yes      |
| Familiar git patterns         |        Yes         |       Yes        |      Yes       |        No        |       N/A       |      Yes      |
| Consistent with sase codebase |        Yes         |       Yes        |       No       |        No        |       Yes       |      Yes      |

## Recommendation

**Alternative 1 (Marker File with Commit Hash)** is the best fit, for these reasons:

1. **Precision**: Commit hash counting via `git rev-list --count` gives an exact, unambiguous count. No timezone issues
   (Alt 2), no orphaned metadata (Alt 4), no namespace pollution (Alt 3).

2. **Consistency**: Storing state in `~/.sase/projects/{project}/` aligns with existing sase conventions (axe state,
   workflow artifacts, sync cache all live under `~/.sase/`).

3. **Simplicity**: Three steps, no unusual git features, no infrastructure dependencies. Easy to understand, debug, and
   modify.

4. **Robustness**: The stored-SHA validation (`git cat-file -t`) handles history rewrites gracefully by falling back to
   a forced refresh rather than failing or producing wrong counts.

5. **Invocation model**: Works naturally as `#sase/refresh_docs` — placed in `xprompts/refresh_docs.yml` and
   auto-namespaced.

### Minor refinements to consider for implementation

- **Use `finally:` on `update_marker`**: If the agent step fails partway through, we may still want to update the marker
  to avoid re-triggering on the same stale count. Or, we may _not_ want to update it so it retries next time. This is a
  policy decision — defaulting to "only update on success" (i.e., keeping the `if:` guard) seems safer.

- **Threshold as an input**: Even with Alt 1, consider adding `threshold` as an input with `default: 10` so it can be
  overridden per invocation: `#sase/refresh_docs 5`.

- **Dry-run output**: Consider having `count_commits` also emit a human-readable message (e.g.,
  `"23 commits since last docs refresh"`) so the agent can report it even when below threshold. This would make the
  workflow useful for quick status checks too.
