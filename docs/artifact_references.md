# Artifact References

Artifact references are typed `@<kind>:<argument>` citations in launch prompts. They are
not xprompts: SASE resolves them late in prompt preprocessing, after xprompt expansion
and command substitution, using the project context for that prompt segment. Each
successful reference expands to prompt text, records a per-agent use row, and can
publish as a numbered Markdown reference link.

## Prompt Grammar

Use the unquoted form when the argument contains no spaces:

```text
@plan:202608/artifact_ref_contract.md
@bead:sase-js.9
@stitch:sase@f499469
```

Use quotes when the argument contains spaces:

```text
@patch:"artifact references adoption"
@file:"~/bob/Research Inbox.md"
```

Fragments such as `#L10-L20`, `#page=2`, and `#t=30` stay attached to the reference when
the target kind supports them. Inline code, fenced code, and disabled xprompt regions
stay literal. Unknown `@kind:` text remains prose; malformed or missing references for a
known kind stop launch with a diagnostic.

## Live Kinds

Canonical live categories are:

| Form                           | Meaning                                                                 |
| ------------------------------ | ----------------------------------------------------------------------- |
| `@stitch:<sha>`                | Commit in the prompt segment's project repository                       |
| `@stitch:<repo>@<sha>`         | Commit in a named primary, linked, or sidecar repo                      |
| `@patch:<name>`                | Patch in the prompt segment's project                                   |
| `@bead:<id>`                   | Bead by full id or unambiguous shorthand                                |
| `@agent:<name>`                | Published agent page and related transcript context                     |
| `@file:<path>`                 | Allow-listed local file captured by content digest                      |
| `@file:<source>:<digest>`      | Indexed file, where source is `explicit` or `default`                   |
| `@<document-kind>:<repo-path>` | Document in a configured artifact sidecar, such as `plan` or `research` |

The built-in plans sidecar exposes `@plan:<path>` through `ref: {use: builtin@plan}`.
The `sase-research-artifacts` plugin exposes `@research:<path>` for the research content
sidecar. Other artifact sidecars can add their own document kind with an inline `ref:`
spec or with `ref.use: <plugin>@<provider>` from an installed provider plugin.

Compatibility readers preserve older persisted references. `@commit:` canonicalizes to
`@stitch:` permanently. `@plans:` and the bare `plans:` machine-field spelling used by
SDD plan references are both read-only compatibility spellings of `plan` — kept because
commit trailers and bead event streams that already carry them are immutable — and
neither is ever emitted again; new references always render as `@plan:` in prose and
`plan:` in machine fields. Historical `@chat:` and `@bug:` references remain archive
readers and are not offered for new authoring. The retired `#ref/<kind>:<argument>`
xprompt renderer syntax is not accepted.

## Project Context

Short references resolve from the prompt segment, not from the current working
directory. A segment's leading `#git:`, `#gh:`, or other VCS workflow tag supplies the
project context. If a segment has no explicit tag, the caller's launch identity supplies
it.

Context affects ambiguity:

- `@stitch:<sha>` searches the selected project's primary repo; qualify with
  `@stitch:<repo>@<sha>` when needed.
- `@patch:<name>` searches the selected project's active Patch store, then its archive.
- A short `@bead:<suffix>` searches the selected project first, then rejects
  cross-project collisions instead of guessing.
- `@agent:<local-name>` canonicalizes to the durable global agent identity.

### On-demand document sidecars

During final preprocessing of each agent prompt at launch, a well-formed reference for a
**path-bound** document kind (see [Expansion](#expansion)) in a workspace-backed prompt
segment can materialize its configured sidecar when that role has a recorded remote but
no local clone. For example, the first live `@plan:...` reference for a `plans` sidecar
that is not yet cloned can clone it, refresh that segment's project context, and then
resolve the document. SASE prints the role it is materializing. A clone failure stops
launch with the remote's error and an explicit `sase repo path <role> --ensure` retry
command.

Pointer document kinds, such as `@research:...`, never trigger this: their expansion
does not depend on a local checkout, so citing one never clones its sidecar.

This write is launch-only. Validation, xprompt display and expansion previews, editor
catalogs, and other discovery paths remain read-only and never clone a missing sidecar.
Materialize the role explicitly when one of those surfaces needs a local inventory.
References inside inline code, fenced code, or disabled xprompt regions stay literal and
do not trigger materialization.

## Allow-Listed Files

Path-backed `@file:` references are opt-in. Configure roots in `sase.yml`:

```yaml
artifact_refs:
  file:
    roots:
      - name: bob
        path: ~/bob
        path_globs: ["**/*.md"]
```

The root name becomes the portable logical identity in published metadata. `path` must
be absolute or `~/` rooted. `path_globs` are root-relative POSIX globs with `!`
exclusions. SASE accepts regular files that stay under exactly one effective root, pass
the glob policy, and fit the configured capture size limit.

At launch, SASE reads the bytes once, hashes them with SHA-256, stores the captured
object, and expands the prompt to that immutable copy. Later source edits do not change
what the agent received.

## Provider Specs

Document artifact providers are declarative. A project can start from an installed
provider:

```yaml
repos:
  sidecar:
    custom:
      research:
        ref:
          use: sase-research-artifacts@research
```

or define the same policy inline:

```yaml
repos:
  sidecar:
    custom:
      design:
        ref:
          kind: design
          icon: ◆
          expansion_format:
            "the {checkout_path} file in the {sidecar_role} artifact repo"
          properties: {}
          detail: {}
          identity: {}
          inventory:
            globs: ["**/*.md", "!drafts/**"]
          publication:
            link: vcs_permalink
            referenced_by: markdown_table
```

`use` and inline fields normalize to the same spec. An assembled reference provider spec
must include `ref.icon`, the Artifacts tab mark; installed providers supply it, and
inline specs declare it directly. Scalar values replace, mappings deep-merge, and lists
replace. Missing providers fail soft during launch and surface as
`sase doctor -C config.repos` findings. A linked repo or cloned sidecar is not an
installed Python distribution; the provider package must be installed so its entry
points are visible.

A sidecar's reference kind is independent of its role name. `ref.kind` (or the kind
inherited through `ref.use`) is the `@<kind>:` prefix agents author; the sidecar role is
storage identity only — the repo checkout path, `sase repo open <role>`, and similar
plumbing. The builtin roles ship with kinds that differ from their role names on
purpose: role `plans` writes kind `plan`, role `beads` writes kind `bead`, and role
`agents` writes kind `agent`. Any sidecar, builtin or custom, can set its own `ref.kind`
independently of its role.

### Expansion

A document reference expands through its provider spec's `expansion_format`, a template
drawn from a subset of the shared placeholder vocabulary:

| Placeholder          | Value                                                     |
| -------------------- | --------------------------------------------------------- |
| `kind`               | The reference's kind, such as `research`.                 |
| `argument`           | The authored argument, fragment stripped.                 |
| `canonical_argument` | The canonical `<kind>:<argument>` reference text.         |
| `repo_relative_path` | The sidecar-relative POSIX path; identical to `argument`. |
| `display_label`      | The argument's filename.                                  |
| `sidecar_role`       | The sidecar role backing this document kind.              |
| `checkout_path`      | The resolved absolute path in a local checkout.           |

A format that uses `checkout_path` is **path-bound**: expansion resolves the reference
to a local file, materializing a missing `auto_clone` sidecar when needed, and fails the
launch with a diagnostic when the document cannot be found there. `@plan:` and every
unconfigured document sidecar use the default path-bound format, `@{checkout_path}`.

A format that uses no path placeholder is a **pointer**: expansion renders straight from
the reference itself, with no resolution dependency. A pointer reference never clones
its sidecar and never fails a launch — an unresolvable pointer still expands, using
whatever prose the format declares. `@research:<path>` is a pointer, declaring
`"the {repo_relative_path} file in the {sidecar_role} sidecar repo"`, so
`@research:202608/report/report.md` expands to "the 202608/report/report.md file in the
research sidecar repo" whether or not the `research` sidecar is cloned.

## Publication

Published prompts rewrite live references as stable Markdown reference links:

```markdown
Read [@research:202608/report.md][1] and [@file:~/bob/gtd.md][2].

[1]: https://github.com/sase-org/sase--research/blob/<revision>/202608/report.md
[2]: ../../files/objects/sha256/ab/<sha256>
```

Clean repository-backed documents link to the captured revision. Dirty or untracked
documents and local files link to the captured object. Tracking does not depend on
linkability: an unlinkable reference still records a use row and remains visible in the
published prompt metadata. A pointer document reference that never resolved to a local
file — no clone of its sidecar was ever made — publishes the same way: unlinked, but
with its use row intact.

Artifact repos that opt into `referenced_by: markdown_table` get a managed
`Referenced By` section at the bottom of cited Markdown documents. That section is a
projection of recorded use rows, not part of the document's semantic content version.
Each row names the publishing agent, project, canonical reference, publication date, and
use count; the agent name links to its published page when SASE can build that URL.
Repeated publication of the same agent revision and document is idempotent, while
multiple citations of the document in that prompt increase the row's use count.

The write-back workflow runs in this order:

1. SASE finishes prompt-archive publication in the agents sidecar, including its push
   when the sidecar has changes or is ahead of its remote.
2. It queues one durable request per cited provider document, then synchronously tries
   to drain the project's queue before the publishing command returns.
3. The drain groups requests by sidecar role, pulls each artifact repository with
   rebase, updates only the managed Markdown block and its `.sase/referenced-by/` index,
   and prepares any changed document and index files.
4. When the refresh changes files, SASE creates a local
   `Update Referenced By projections` commit and starts a detached push. A successful
   refresh, including an idempotent no-op, acknowledges the request without waiting for
   that push to finish.

A failure before a successful local artifact-sidecar refresh leaves the request queued
for a later mutating `sase agent sync`. The same `--retry-quarantined` and
`--drop-retired` controls used for agent publication also operate on queued Referenced
By requests; see [Agent Hood Synchronization](agents_sidecar.md#commands-and-status).
Once the local refresh succeeds, however, the request is no longer in that outbox. A
later detached-push failure is recorded in the managed SDD sync log and is not retried
from the Referenced By outbox.

The write-back attempt can delay the publishing command's return, but it begins only
after the prompt archive has been pushed and cannot roll that publication back. Because
the managed block is stripped when SASE hashes a clean Markdown input, adding a
back-reference does not make the original citation appear to have changed. These commits
use the non-user file-hook cause `referenced_by`, so ordinary file hooks ignore the
managed write unless they explicitly opt in with `filters.causes`.
