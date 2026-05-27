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

The pattern is not "hide planning." It is "give planning its own durable history and link it to implementation." That
keeps the main code repository's default history focused on code while retaining a reviewable, searchable record of why
large changes happened.

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

### 8. Git notes

Git notes attach extra blobs to objects without modifying the objects themselves. The Git docs describe notes as a way
to supplement commit messages, with notes stored in separate refs.
Source: <https://git-scm.com/docs/git-notes.html>

This is attractive for small commit annotations, but not for SDD. Notes are per-object, poorly surfaced by most hosting
UIs, require custom fetch/push refspecs in practice, and do not model a large structured artifact tree.

### 9. Transient change fragments

Tools such as Changesets intentionally commit small release-note fragments near code, then consume them during the
versioning step into package versions and changelogs. Its docs describe the loop as adding changesets with each change,
running a version command at release time, and publishing afterward.
Source: <https://github.com/changesets/changesets/blob/main/docs/intro-to-using-changesets.md>

That model works because the fragments are low-volume release metadata with a clear consumption point. SDD artifacts
are broader: many are prompts, operational plans, bead events, exploratory research, and images. Treating all of them
as transient release fragments would lose the audit trail SDD exists to preserve.

## What This Means For SASE

The prior art separates artifacts by lifecycle and audience:

| Pattern | Good for | Bad for |
| --- | --- | --- |
| Separate design/proposal repo | durable planning history linked to code | artifacts that must be edited atomically with code |
| Orphan branch / `gh-pages` style branch | generated output with independent history | contributor discoverability without tooling |
| Wiki sidecar | lightweight docs near a repo | large, structured, agent-written corpora |
| Submodule | explicit dependency on a separate repo | high-frequency updates if the pointer is kept current |
| Squash merge | reducing landed commit count | removing SDD from branch diffs or file history |
| Path filters / Linguist | better browsing during transition | restoring code-history signal |
| Git notes | small commit annotations | structured, searchable SDD artifacts |

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

This matches Rust/Python/Kubernetes' separation of durable proposal history from implementation history, GitHub Pages'
separation of generated output from source history, and SASE's own existing local-mode storage model. It preserves the
SDD audit trail while making the main SASE commit graph useful again as a signal for code activity.
