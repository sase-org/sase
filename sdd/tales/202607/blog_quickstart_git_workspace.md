---
create_time: 2026-07-02 15:38:11
status: done
prompt: sdd/prompts/202607/blog_quickstart_git_workspace.md
---
# Plan: Fix the quickstart blog's workspace-isolation narrative by switching to `#git`

## Problem / Context

`sdd/research/202607/blog_launch_readiness_audit.md` (Concern #1, safety-critical) found that the published quickstart
post `docs/blog/posts/hello-sase-your-first-15-minutes.md` makes a false safety claim: Steps 3 and 5 use `#cd:$(pwd)`
while telling the reader the run happens in "an isolated **workspace** — a sibling clone of the repo named `sase_<N>`"
and that Step 5's editable diff lands "in its isolated workspace." In reality `#cd` deliberately runs **in place** with
no workspace allocation (`src/sase/workspace_provider/plugins/cd_workspace.py`, `docs/workspace.md:128-136`), so the
very first editable command the post hands a reader modifies their real checkout while claiming it won't.

The fix chosen (per the audit's recommendation and explicit user direction): **rewrite the post's examples around `#git`
runs, which genuinely allocate isolated workspaces, and explicitly mention that `#git:home` is the default applied when
a prompt contains no VCS/workspace workflow reference.**

## Verified behavior the rewrite must reflect (all confirmed against code)

1. **`#git:home` is the default for bare prompts.** `DEFAULT_VCS_WORKFLOW_PREFIX = "#git:home"`
   (`src/sase/xprompt/_parsing_vcs_tags.py:12`). The `sase run` CLI path enables this normalization:
   `src/sase/main/query_handler/_launch.py` → `launch_agents_from_cwd` →
   `src/sase/agent/launch_cwd_agents.py:208,216,348` (`default_bare_segments_to_home=True`,
   `normalize_default_vcs_workflow`) → `src/sase/agent/multi_prompt_launcher.py:261-263`. Normalization is applied **per
   multi-prompt segment**: any segment with no registered workspace reference gets prefixed with `#git:home`. Documented
   at `docs/workspace.md:135-136` and `157-161`.
2. **`#git:home` bootstraps a managed project on first use.** If the `home` ProjectSpec is missing, SASE initializes a
   bare repo at `~/.sase/repos/home.git` and a primary checkout at `~/projects/git/home/`, with SDD scaffolding and an
   initial commit (`src/sase/workspace_provider/plugins/bare_git_ref.py:95-127` →
   `bare_git_init.py:init_bare_git_project`; documented at `docs/workspace.md:157-161`). So a brand-new reader can run
   `#git:home` with zero setup — this is the ideal quickstart sandbox.
3. **`#git` runs allocate a real isolated numbered workspace.** Non-wait launches allocate the next numbered workspace
   for the project (`docs/workspace.md:187-194`). The naming/location claim in the current post is stale even for
   `#git`: the default `workspace.root` is the platform state directory (e.g. `~/.local/state/sase/workspaces/...` on
   Linux), with directories named `<project>_<N>`; the `sase_<N>`-style _sibling_ layout is the legacy opt-in
   (`workspace.root: adjacent`) (`src/sase/workspace_provider/store.py:177-198`, `docs/workspace.md:267`, `README.md`
   workspace-root section). The rewrite should say "isolated numbered workspace managed by SASE" and avoid promising a
   specific path shape.
4. **ChangeSpecs are created by the commit workflow**, not at launch (`docs/change_spec.md:116`). A read-only `#git` run
   produces an agent record but no ChangeSpec; an editable run produces a ChangeSpec (visible on ACE's PRs tab) once the
   agent commits. Step 5's "review the resulting workspace or ChangeSpec" becomes _true_ under `#git`, but the prose
   should sequence it correctly ("when the agent commits its work, a ChangeSpec appears on the PRs tab").
5. **CWD xprompt discovery is a launch-time concern**, independent of the workspace workflow: `xprompts/*.md` and
   `.xprompts/*.md` under the directory where `sase run` is invoked are discovered at expansion time
   (`src/sase/xprompt/loader_sources.py:166-171,192-203`). So Step 6's "create `xprompts/<name>.md` where you run
   `sase`" mechanic keeps working under `#git` runs.
6. **The published [00] post has the same flaw in miniature.**
   `docs/blog/posts/why-coding-agents-need-orchestration.md:290` uses
   `sase run '%n:design #cd:$(pwd) propose a small architecture improvement'` (an editable prompt), and line 294 then
   claims "The forked agent gets a new record and a new workspace" — false for `#cd`.

## Design decisions

- **Reframe the quickstart's first runs around the `home` project sandbox instead of "the repo you're standing in".**
  The current Step 3 premise ("run in the directory you want the agent to inspect") is what forced `#cd` in the first
  place. The rewrite makes the safe on-ramp the managed `home` project: genuinely isolated, zero setup, and it showcases
  the actual SASE workspace model (numbered workspaces, ChangeSpecs, PRs tab) instead of bypassing it.
- **Teach the default explicitly.** Use the explicit `#git:home` tag in the first example, then immediately state that
  `#git:home` is the default whenever a prompt contains no VCS/workspace workflow reference — so the bare form
  `sase run "<prompt>"` is equivalent. (Terminology: use "workspace reference" / "VCS workflow" consistently with
  `docs/workspace.md`.)
- **Keep an honest, brief pointer for "your own repos".** A short paragraph (not a new step) covering: `#git:<name>`
  creates/targets managed projects; `#git:<bare-repo-path>` registers an existing bare repo; provider plugins add refs
  like `#gh:<owner>/<repo>` for GitHub; and `#cd:<path>` exists for one-off **in-place** runs with _no_ isolation —
  stated plainly as the opposite of the sandbox story. Link to `docs/workspace.md` for depth.
- **Example prompts must make sense in a freshly bootstrapped, nearly-empty home repo** (it contains SDD scaffolding and
  little else). "Summarize what this repository does" no longer fits; pick prompts that work in a scratch repo.

## File changes

### 1. `docs/blog/posts/hello-sase-your-first-15-minutes.md` (primary)

- **Step 3 (lines ~64-82):** Replace `#cd:$(pwd)` with `#git:home`; drop the "in the directory you want the agent to
  inspect" premise. Suggested command shape:
  `sase run "#git:home summarize this workspace's layout; do not change files"`. Rewrite the explanation paragraph to
  cover: (a) what `#git:home` is (the managed home project, bootstrapped on first use); (b) that the run happens in an
  isolated numbered workspace managed by SASE (no `sase_<N>` naming, no "sibling clone" claim); (c) the default rule — a
  prompt with no workspace reference is normalized to `#git:home` automatically, so the bare form is equivalent; (d) the
  isolation benefits (parallel agents, safe retries) which are now actually true.
- **Step 4 (lines ~84-106):** Minor touch-ups only; the "find the run's workspace path" narrative is now accurate.
  Optionally note that a read-only run shows no ChangeSpec yet — that arrives in Step 5.
- **Step 5 (lines ~108-121):** Replace `#cd:$(pwd)` with `#git:home` (or the bare form, reinforcing the default).
  Suggested shape: `sase run "#git:home add a short note about SASE workspaces to notes.md"`. Rewrite the isolation
  paragraph to be truthful and sequenced: the diff lives in the run's isolated workspace; the reader's own repos and the
  home primary checkout are untouched; when the agent commits, the commit workflow records a **ChangeSpec** reviewable
  on the PRs tab. Add the "your own repos" pointer paragraph here (or at the end of Step 3 — implementer's call on
  flow), including the honest one-line `#cd` framing.
- **Step 6 (lines ~123-145):** Keep the "smallest XPrompt shape" teaching point and the CWD `xprompts/` mechanic, but
  replace the docstring example (which needs a real code repo) with one that fits the home project — e.g.
  `xprompts/til.md` containing an "append a Today-I-Learned entry to `til.md`" prompt, run as `sase run "#til"` with a
  note that the default `#git:home` kicks in because the prompt has no workspace reference (this doubles as a second
  demonstration of the default rule).
- **Component map (lines ~178-179):** Fix the Workspaces bullet: "isolated numbered clones managed by SASE so agents can
  work in parallel without touching your primary checkout" (drop `sase_<N>`).
- **Frontmatter description (lines ~4-6):** Only touch if the rewritten steps make it inaccurate; "launch a safe first
  agent run" remains true.
- Sweep the whole post for residual "sibling clone", `sase_<N>`, and `#cd` mentions after the rewrite.

### 2. `docs/blog/posts/why-coding-agents-need-orchestration.md` (secondary, same class of bug)

- Line ~290: change the fork example's first command to drop `#cd:$(pwd)` — either bare
  (`sase run '%n:design propose a small architecture improvement'`, letting the `#git:home` default apply) or explicit
  `#git:home`. This makes line ~294's "the forked agent gets a new record and a new workspace" claim true.
- Quick sweep of this post for other `#cd`-plus-isolation pairings (line 47's "launch in isolated workspaces" claim
  becomes consistent once the example is fixed).

## Verification

1. **Fact-check the Step 5 commit story before finalizing prose:** confirm what an editable `#git:home` run actually
   leaves behind (agent commit → ChangeSpec on the PRs tab) by reading the commit-workflow/finalizer path (e.g.
   `src/sase/workflows/commit/`, `src/sase/ace/hooks/defaults.py`) — or ideally by executing a real
   `sase run "#git:home ..."` editable run end-to-end and checking `sase agent list` + ACE. Adjust wording to match
   observed behavior rather than aspiration.
2. **Dry-run the reader path for Step 3** the same way if feasible (fresh/absent `home` project → bootstrap → read-only
   run) to confirm the bootstrap story reads correctly.
3. `just check` (required — these are tracked doc files, not `sdd/research/` markdown; run `just install` first in a
   fresh workspace).
4. `just docs-check` (mkdocs build validation) — confirms links/anchors still resolve.
5. Markdown formatting via the repo's prettier setup (`just fmt`), since blog posts are prettier-formatted.

## Out of scope

- Concerns #2 (silent xprompt failures) and #3 (Agents-tab visual/golden issues) from the audit.
- The unpublished `xprompts-in-depth.md` draft and the announcement post itself (not in this repo's scope yet); the
  announcement should describe isolation the same way once written.
- Any code changes — this is a docs-only plan; `#cd` semantics and the `#git:home` default are correct as implemented
  and already accurately documented in `docs/workspace.md`.
