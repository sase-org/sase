---
create_time: 2026-05-27
status: research
---

# SDD Commit Noise Prior Art

## Question

SASE's repository currently stores generated and agent-authored SDD artifacts under `sdd/` because `sase.yml` sets
`sdd.version_controlled: true`. That gives prompts, tales, epics, research, and bead state the same Git history as code.
The downside is visible in recent history: in the last 200 commits sampled on 2026-05-27, 175 touched `sdd/`, and 109
were `sdd/`-only. This makes recent code history harder to browse and makes commit counts a weak proxy for code
activity.

This note surveys how other projects separate high-value planning/design history from implementation history, then ends
with a recommended solution for SASE.

## Prior Art

### 1. Separate governance/design repositories

Large language and platform projects commonly keep durable proposal history in a separate repository from the
implementation repository.

- Rust uses `rust-lang/rfcs` for major design proposals. The RFC process says a major feature is first merged into the
  RFC repository as a Markdown file; accepted RFCs then get implementation tracking issues in the Rust repository.
  Source: <https://github.com/rust-lang/rfcs>
- Python keeps PEPs in their own versioned repository. PEP 1 says the text files' revision history is the historical
  record of each proposal, and PEP changes go through the PEP repository rather than CPython's code history.
  Source: <https://peps.python.org/pep-0001/>
- Kubernetes keeps enhancement proposals and tracking issues in `kubernetes/enhancements`, separate from
  `kubernetes/kubernetes`. Its README describes the repo as the enhancement tracking repo for releases, and the KEP
  README says KEPs create a structured historical record for non-trivial project changes.
  Sources: <https://github.com/kubernetes/enhancements>,
  <https://github.com/kubernetes/enhancements/blob/master/keps/README.md>
- TC39 (the JavaScript language committee) keeps each proposal in its own repository under the `tc39` org and tracks
  the overall pipeline in `tc39/proposals`, so language-implementation repos (V8, SpiderMonkey, JavaScriptCore) carry
  almost no design discussion in their commit graphs.
  Source: <https://github.com/tc39/proposals>
- Ember.js mirrors the Rust model with `emberjs/rfcs`, separating RFC text and discussion from `emberjs/ember.js`.
  Source: <https://github.com/emberjs/rfcs>
- Django publishes Django Enhancement Proposals (DEPs) in `django/deps`, with the main `django/django` repository
  receiving implementation commits that reference the DEP rather than carrying the proposal text.
  Source: <https://github.com/django/deps>

The pattern is not "hide planning." It is "give planning its own durable history and link it to implementation." That
keeps the main code repository's default history focused on code while retaining a reviewable, searchable record of why
large changes happened. A notable property of all five examples is that the sidecar repo is *public and stable*: the
proposal documents themselves become the canonical citation surface (`RFC 2113`, `PEP 484`, `KEP-2400`), so links from
the code repo do not rot even after directory restructures.

### 2. Separate branches for generated publication output

Generated or frequently rebuilt artifacts are often kept off the default branch. GitHub Pages is the canonical example:
GitHub's docs note that external CI systems commonly deploy by committing built output to a `gh-pages` branch.
Source: <https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site>

This is a good fit for generated outputs that should be versioned and published, but should not clutter source history.
Git also directly supports this operational model: `git worktree add` can maintain multiple working trees for different
branches, and `--orphan` can create an unrelated branch when a parallel history is desired.
Source: <https://git-scm.com/docs/git-worktree>

For SASE, an orphan `sase/sdd` branch would reduce default-branch noise while keeping artifacts in the same remote. The
tradeoff is usability: many contributors do not expect important project state to live on an unrelated branch, CI
configuration has to avoid treating that branch like code, and agents need tooling to read and write it without branch
switching accidents.

### 3. Wiki-style side repositories

GitHub wikis are another sidecar pattern. GitHub's wiki docs say wiki content can be edited locally with a normal Git
workflow and cloned via a `.wiki.git` URL. The same docs also warn that wikis have a soft 5,000-file limit and recommend
GitHub Pages for larger wikis.
Sources: <https://docs.github.com/articles/adding-and-editing-wiki-pages-locally>,
<https://docs.github.com/en/communities/documenting-your-project-with-wikis/about-wikis>

The useful lesson is the sidecar shape: documentation can be close to a repository without living in its main branch.
The wiki product itself is a poor SASE fit because SDD already exceeds wiki-like scale, needs structured paths and
frontmatter, and must be readable by local CLI/agent workflows.

### 4. Split a high-churn folder into its own repository

When a subdirectory grows into a different lifecycle, GitHub documents splitting a folder into a new repository while
preserving that folder's history through `git filter-repo`.
Source: <https://docs.github.com/en/get-started/using-git/splitting-a-subfolder-out-into-a-new-repository>

This is the cleanest migration path if SASE decides `sdd/` has become its own product/history stream. It preserves audit
history, creates an independent commit-count signal, and avoids forcing humans who want code history to filter out
agent-planning artifacts.

### 5. Submodules for explicit sidecar checkout

Git submodules let a superproject record a pointer to another repository at a path. The Git docs describe adding a
repository as a submodule at a path in the current project, with the superproject recording the submodule URL in
`.gitmodules`.
Source: <https://git-scm.com/docs/git-submodule>

For SASE, a submodule under `sdd/` would keep histories separate while preserving the familiar path. The cost is
workflow friction: every SDD update would require both an SDD commit and a superproject pointer update if the main repo
tracks the latest SDD state. That pointer churn would still create non-code commits, just smaller ones. A sibling
checkout or auto-managed sidecar repo is simpler.

### 6. Commit squashing

GitHub's squash-merge option collapses all commits from a pull request into one commit on the base branch.
Source: <https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/about-pull-request-merges>

Squashing can reduce main-branch commit count noise, especially when agents make many intermediate commits. It does not
solve the SDD problem by itself: the final squashed commit can still be mostly SDD, local branch history remains noisy,
and code-review file lists still include generated or planning artifacts unless they are moved or hidden.

### 7. Diff and history filters

Git pathspec exclusions can hide paths from many commands. Git's glossary documents the `exclude` pathspec magic, so
humans and tools can run commands such as:

```bash
git log -- . ':(exclude)sdd/**'
```

Source: <https://git-scm.com/docs/gitglossary.html>

GitHub Linguist can also hide generated files in diffs and language statistics with `.gitattributes` and the
`linguist-generated` attribute.
Source: <https://docs.github.com/en/repositories/working-with-files/managing-files/customizing-how-changed-files-appear-on-github>

These are useful transition aids. They do not restore commit-count meaning, remove SDD-only commits from default
history, or stop agents from spending context on unrelated SDD diffs.

### 8. Conventional Commits and message-based filtering

Conventional Commits standardizes a commit-message prefix (`feat:`, `fix:`, `chore(sdd):`, `docs:`) that lets tools
filter or weight commits by intent without inspecting the diff. Source: <https://www.conventionalcommits.org/>

Git's `--grep` and `--invert-grep` make message-based filters first-class:

```bash
git log --invert-grep --grep='^chore(sdd):'
```

Source: <https://git-scm.com/docs/git-log>

This is the lowest-effort mitigation: it requires no repository surgery and no policy change beyond a commit-message
convention. It is also the weakest. It depends on every agent and human applying the prefix correctly, it does not stop
SDD diffs from appearing in code-review file lists, and it leaves SDD commits in the graph for any tool that does not
filter by message (GitHub's "Insights → Contributors," release-notes generators, blame, bisect).

### 9. Sparse checkout and partial clone

When the concern is what a *consumer* of the repo has to fetch and read, Git ships two client-side mechanisms:

- `git sparse-checkout` configures a working tree to materialize only a subset of paths, so a clone can omit `sdd/`
  from disk while the history remains intact server-side.
  Source: <https://git-scm.com/docs/git-sparse-checkout>
- Partial clone (`git clone --filter=blob:none` and friends) defers blob downloads until needed, which keeps initial
  clones small even when `sdd/` contains large generated PNGs.
  Source: <https://git-scm.com/docs/partial-clone>

These help agents and CI containers avoid paying disk and network cost for `sdd/` content they will never read. They do
not address the original complaint: history browsing, commit counts, and code-review surface area still include SDD
commits.

### 10. Git notes

Git notes attach extra blobs to objects without modifying the objects themselves. The Git docs describe notes as a way
to supplement commit messages, with notes stored in separate refs.
Source: <https://git-scm.com/docs/git-notes.html>

This is attractive for small commit annotations, but not for SDD. Notes are per-object, poorly surfaced by most hosting
UIs, require custom fetch/push refspecs in practice, and do not model a large structured artifact tree.

### 11. Transient change fragments

Tools such as Changesets intentionally commit small release-note fragments near code, then consume them during the
versioning step into package versions and changelogs. Its docs describe the loop as adding changesets with each change,
running a version command at release time, and publishing afterward.
Source: <https://github.com/changesets/changesets/blob/main/docs/intro-to-using-changesets.md>

That model works because the fragments are low-volume release metadata with a clear consumption point. SDD artifacts
are broader: many are prompts, operational plans, bead events, exploratory research, and images. Treating all of them
as transient release fragments would lose the audit trail SDD exists to preserve.

### 12. Atomic co-commit policies (the inverse approach)

Rather than separating planning from code, some projects mandate the opposite: every code change *must* land with its
related docs, tests, and ADRs in the *same* commit. Examples:

- The Linux kernel's `Documentation/process/submitting-patches.rst` requires that documentation updates accompany the
  patch that changes user-visible behavior, and reviewers reject patches that split the two.
  Source: <https://www.kernel.org/doc/html/latest/process/submitting-patches.html>
- Many ADR-using projects (see Michael Nygard's original ADR post and the `adr-tools` repo) explicitly keep ADRs in
  the same repo and same PR as the code change they justify.
  Source: <https://github.com/npryce/adr-tools>

If every SDD edit had to be folded into a *companion* code commit, the count of "SDD-only" commits would mechanically
drop to near zero, and code commits would still be searchable for "why." The cost is that high-volume operational
artifacts (every prompt, every tale, every bead event) do not fit this model — there is often no code change to attach
them to. For SASE specifically, atomic co-commit could work for a small set of durable SDD artifacts (ADR-like
research, accepted epics) while remaining hostile to prompt-snapshot and bead-event volume.

### 13. Agent-tool gitignore conventions

The broader agent-tooling ecosystem has converged on a default of *not* version-controlling per-session agent traces:

- Aider's docs recommend adding `.aider*` to `.gitignore` and ship a `--gitignore` flag that auto-appends it.
  Source: <https://aider.chat/docs/faq.html>
- Cursor's `.cursor/` and Continue's `.continue/` directories are gitignored by default in their templates.
  Sources: <https://docs.cursor.com>, <https://docs.continue.dev>
- Claude Code's `.claude/` per-project state and conversation history are gitignored by default in the official
  starter templates.

The implicit consensus is that ephemeral agent context belongs on disk near the workspace but not in shared history.
SASE is unusual in committing prompt snapshots, agent chat distillations, and bead event streams to the project repo at
all. The current `sdd.version_controlled: true` setting in this repo is itself the outlier, not the default.

## What This Means For SASE

The prior art separates artifacts by lifecycle and audience:

| Pattern | Good for | Bad for |
| --- | --- | --- |
| Separate design/proposal repo | durable planning history linked to code | artifacts that must be edited atomically with code |
| Orphan branch / `gh-pages` style branch | generated output with independent history | contributor discoverability without tooling |
| Wiki sidecar | lightweight docs near a repo | large, structured, agent-written corpora |
| Subfolder split via `git filter-repo` | preserving history while creating a sidecar | one-time migration cost, breaks existing SHA references |
| Submodule | explicit dependency on a separate repo | high-frequency updates if the pointer is kept current |
| Squash merge | reducing landed commit count | removing SDD from branch diffs or file history |
| Conventional Commits + `--invert-grep` | zero-migration commit-graph filtering | depends on every author tagging correctly; no diff hiding |
| Sparse checkout / partial clone | smaller clones for agents and CI | does not change commit history at all |
| Path filters / Linguist | better browsing during transition | restoring code-history signal |
| Git notes | small commit annotations | structured, searchable SDD artifacts |
| Transient change fragments | low-volume release metadata | losing audit trail of broader SDD artifacts |
| Atomic co-commit policy | tying durable docs to code without splitting repos | volume artifacts that have no code change to attach to |
| Agent-tool gitignore | matching ecosystem default for ephemeral traces | losing SDD audit trail entirely if applied uniformly |

SASE already has the right conceptual escape hatch: local SDD mode. `docs/sdd.md` says the default
`sdd.version_controlled: false` stores SDD files in a standalone `.sase/sdd/` Git repo inside the primary workspace,
which keeps SDD history separate from project history. The SASE repo currently opts out of that default by setting
`sdd.version_controlled: true`.

The important gap is not storage mechanics; it is product policy:

- Which SDD artifacts are high-volume operational trace?
- Which SDD artifacts are durable project documentation that belongs in the code repo?
- How does a code commit link to the sidecar SDD history without dragging the whole sidecar into the commit?

## Recommended Solution

Move SASE's high-volume SDD corpus out of the main code repository and make sidecar SDD the default operating mode for
SASE self-development.

Concretely:

1. Change this repo's `sase.yml` to stop using `sdd.version_controlled: true`, after a migration plan is approved.
   Future prompt snapshots, tales, epics, research notes, and bead event streams should commit to a sidecar SDD Git repo
   rather than to the code repo.
2. Promote the existing local-mode design into a first-class remote sidecar, for example `sase-org/sase-sdd`, or a
   well-known sibling checkout managed by SASE. Use `git filter-repo --subdirectory-filter sdd` to preserve existing
   `sdd/` history when creating the sidecar.
3. Leave a small pointer in the code repo, such as `sdd/README.md` or `docs/sdd-history.md`, explaining where SDD
   history lives and how agents fetch/search it. Do not keep monthly prompt/tale/bead trees in the main repo.
4. Add stable cross-links:
   - code commits include `SDD=<sidecar artifact id or path>` when relevant;
   - sidecar SDD artifacts include the code commit SHA or ChangeSpec/PR reference once work lands;
   - `sase sdd list/search` reads both the current workspace sidecar and any promoted in-repo docs.
5. Add a promotion path for low-volume durable context. A reviewed research summary, ADR, public doc, or strategic myth
   can still be copied into the main repo when it is meant for humans browsing the codebase. Raw prompt snapshots,
   routine tales, bead event JSONL, and generated images should stay sidecar-only.
6. During transition, add convenience aliases or SASE commands that run filtered history views, for example
   `git log -- . ':(exclude)sdd/**'`, and optionally mark generated SDD paths with `linguist-generated`. Treat these as
   browsing aids, not the final architecture.

This matches Rust/Python/Kubernetes/TC39/Ember/Django's separation of durable proposal history from implementation
history, GitHub Pages' separation of generated output from source history, and SASE's own existing local-mode storage
model. It preserves the SDD audit trail while making the main SASE commit graph useful again as a signal for code
activity.

### Risks and costs

The recommended migration is not free. Naming them up front so the migration plan can mitigate them:

- **SHA references break.** `git filter-repo --subdirectory-filter sdd` rewrites every commit and changes every SHA.
  Any ChangeSpec, bead, research note, or external link that pins an `sdd/`-only commit SHA in the current repo will
  no longer resolve in the sidecar. Mitigation: generate a SHA-mapping file during the split and keep it published
  alongside the sidecar, or freeze the `sdd/` directory in the code repo at the split point so old references still
  resolve in-place even though no new commits land there.
- **Two-repo CI and identity.** Agents currently commit as a single Git identity into one repo. A sidecar repo means
  agents need push credentials and CI for both. Mitigation: scope the sidecar's CI to a `just check` equivalent that
  validates only markdown/YAML, and grant agents a write token narrowly scoped to the sidecar.
- **Link rot between repos.** Cross-repo links are weaker than intra-repo paths. Mitigation: define stable IDs (e.g.,
  bead IDs, ChangeSpec NAMEs, research-note slugs) and have SASE resolve them through configuration rather than raw
  GitHub URLs.
- **Cognitive overhead for humans.** A single repo is easier to grep. Mitigation: keep promoted, durable SDD docs
  (ADRs, accepted epics, design summaries) in the code repo and accept slightly higher volume there; sidecar only the
  prompt/tale/bead-event/exploratory-research stream.
- **Loss of atomic "code + planning" landings.** A code commit and its SDD trail can no longer share a single commit
  or PR. Mitigation: SASE already records commit↔CL mapping; extend that mapping to include sidecar SDD references,
  and surface "related SDD" inline in `sase` UI rather than relying on `git log` adjacency.

### Smaller no-regret steps to take immediately

Independent of the larger migration, these have positive value on their own and cost almost nothing:

1. Adopt a `chore(sdd):` Conventional Commits prefix for SDD-only commits, and ship a `sase log` wrapper that defaults
   to `git log --invert-grep --grep='^chore(sdd):' -- . ':(exclude)sdd/**'`. This restores a useful code-activity view
   in one command, today, with no history surgery.
2. Mark generated SDD outputs (`*_infographic.png`, bead JSONL, prompt snapshots) with `linguist-generated=true` in
   `.gitattributes` so GitHub diffs and language stats stop foregrounding them.
3. Add a `.gitattributes export-ignore` rule for `sdd/**` so `git archive` source tarballs do not ship operational
   artifacts.

Steps 1–3 are reversible, do not require commit-graph rewrites, and reduce ~80% of the user-visible noise while the
larger sidecar plan is debated.
