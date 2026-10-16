---
title: Bead attachments
description: Attachment storage, visibility, and troubleshooting for bead records.
---

# Bead attachments

This page describes how bead attachments are stored, shared, and inspected.

## Attachments

Inline `@<path>` references in bead note text attach content-addressed file snapshots,
and `sase bead attach` attaches files without prose. Rendering needs no opt-in: a note
written with attachments renders on every machine.

> **`@` in bead notes.** Inside note text, `@<path>` attaches a snapshot of that file.
> The bead keeps the exact bytes on every machine, even after the file is gone. Accepted
> forms: `@./shot.png`, `@~/logs/crash.log`, `@/tmp/trace.json`, `@docs/plan.md`,
> `@"name with spaces.png"`, or a bare `@name.ext` for a known file type. Write `@@`
> where you need a literal `@` that would otherwise start a reference. `me@host`,
> `@large`, and `@research:…` citations never need escaping. A note argument that is
> _only_ `@<file>` still reads the note's text from that file, and any `@<path>` inside
> that text then attaches. To attach files without prose, use `sase bead attach`.

Resolution uses the invocation cwd, including text loaded from a whole-argument `@file`,
with `~` expanded. `Path.resolve()` follows symlinks, then the resolved regular file is
ingested. Sensitive paths use the core policy plus `bead.attachments.sensitive_patterns`
unless `-S/--allow-sensitive`. Directories get the existing `tar czf` hint. FIFOs,
devices, and sockets are refused. Every problem is collected and nothing is written.

| Rule          | Behavior                                                                                                                                                                                                                     |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Boundary      | `@` is significant only at the start of the text or after whitespace, `"`, `'`, `(`, `[`, `{`, `,`, `=`, plus `<`.                                                                                                           |
| Escape        | Boundary `@@` becomes a literal `@`. The next character is _not_ a boundary.                                                                                                                                                 |
| Reuse         | `@attachment:<name>` references an attachment already on this bead, or one attached earlier in the same text by its assigned name. An unknown name is an error.                                                              |
| Citation      | `@<kind>:<arg>` for a registered or known document kind stays literal text, as today.                                                                                                                                        |
| Quoted path   | `@"…"` uses the existing quoted-candidate rules (`\"`, `\\`, never crosses a newline).                                                                                                                                       |
| Path-shaped   | `@/…`, `@~/…`, `@./…`, `@../…`. Also a token containing `/` whose segments match `[A-Za-z0-9._+~-]+`. Also a bare `stem.ext` where `ext` is in the curated core extension table. Trailing `. , ; : ! ? ) ] } >` are trimmed. |
| Anything else | Literal (`@large`, `@dataclass`, `@pytest.mark.asyncio`, bare `@`).                                                                                                                                                          |

Every note-bearing verb accepts attachments:

```bash
sase bead note <id> <text> [-S/--allow-sensitive] [-L/--local-only] [-K/--private] [-W/--public] [-y/--yes]
sase bead close <id> -n <text> [-S/--allow-sensitive] [-L/--local-only] [-K/--private] [-W/--public] [-y/--yes]
sase bead update <id> -n <text> [-S/--allow-sensitive] [-L/--local-only] [-K/--private] [-W/--public] [-y/--yes]
sase bead +1 <id> -n <text> [-S/--allow-sensitive] [-L/--local-only] [-K/--private] [-W/--public] [-y/--yes]
sase bead attach <id> <file|->... [-a/--author NAME] [-n/--note TEXT] [-N/--name NAME] [-S/--allow-sensitive] [-L/--local-only] [-K/--private] [-W/--public] [-y/--yes]
sase bead attachment list [<id>] [-j/--json]
sase bead attachment open <id> [<name>]
sase bead attachment path <id> <name>
sase bead attachment publish <id> <name> [-y/--yes]
sase bead attachment push [<id>]
sase bead attachment purge <id> <name> -r WHY [-y/--yes]
sase bead attachment prune [-y/--yes]
sase bead attachment unpublish <id> <name> [-y/--yes]
```

### Storage tiers and privacy

Bytes never enter the bead store: note events carry only location-free descriptors
(`name`, `sha256`, `size_bytes`, `mime_type`, image dimensions, machine origin), which
are as public as the bead itself. Bytes live in a local content-addressed cache first,
then in shared stores picked deterministically by size:

- The **git tier** holds objects up to `bead.attachments.git_max_bytes` (default 50 MiB)
  in a `<project>--attachments-private` sidecar repo, one per project. Its local copy is
  a bare partial clone at `~/.sase/projects/<project_key>/repos/attachments-private`.
  Public attachments live in a `<project>--attachments` sidecar repo with the same bare
  layout at `~/.sase/projects/<project_key>/repos/attachments`. SASE requests private
  visibility when creating the remote, but does not check the visibility of an existing
  remote; verify that before using it for attachment bytes. The role is hidden from
  agent instructions, and descriptors contain no local file paths. `sase repo init` asks
  before creating a missing remote. Declining does not create a git store on that
  machine; `repos.sidecar.builtin.attachments-private.disabled: true` prevents sidecar
  setup and hides the role even when a clone already exists. Use `-L/--local-only` for
  an individual attachment that must stay on this machine. See
  [Repository initialization](../../init.md#repository-initialization).
- The optional **rclone large tier** (`bead.attachments.large_store`) takes larger
  objects; see below.
- `-L/--local-only` keeps an object on this machine only, badged `⚠ only on <machine>`.
  It is an explicit, visible choice, and `sase bead attachment push` promotes local-only
  objects later without editing any note.

Uploads never run under the bead lock: the event is appended first, then bytes upload
pre-publication, so other machines never see a note before its bytes. A failed upload
lands in a durable outbox, badged `⇡ pending upload`, and drains on the next push, bead
sync, or worker launch. `bead.attachments.require_upload: true` uploads before the event
instead and aborts with nothing written when the upload fails. An explicit
`-L/--local-only` still keeps the bytes local in that mode.

### Attachment visibility

Every attachment gets a SASE audience decision: `🌐 public` means readable by anyone who
can read the bead store — treat it as irreversible publication — and `🔒 private` stays
on the private attachments sidecar. Use `-K/--private` to force private and
`-W/--public` to request public (a human confirms on a TTY, or passes `-y/--yes`).
Agents can only narrow; only humans widen. Files over
`bead.attachments.public_max_bytes` (default 25 MiB) never go public. Private protects
bytes, not names or prose: filenames and note text stay as public as the bead itself.

SASE decides in the Rust core from an ordered rule table, and uncertainty resolves to
private. In order: a private bead store forces private; sensitive paths and known-secret
values never go public; an explicit `-K`, `-W`, or `-L` is honored subject to the
widening rules below; files over the public cap stay private; secret-scan hits, private
provenance (owner-only files, ignored files, private or unknown remotes, personal and
config zones), opaque types, and unverified media stay private; tracked files already
public on a public remote, and scan-clean workspace text or self-produced media, go
public; everything else — including stdin — stays private.

Widening a policy-private result with `-W/--public` refuses for agents (the error names
the exact `sase bead attachment publish` command to offer through `/sase_gate`), asks a
human to confirm on a TTY (`-y` skips the prompt), and always refuses sensitive paths,
known-secret values, over-cap sizes, and private bead stores.

### From the Beads pane

Select a bead in the Beads pane and press `N` to open the add-note editor. Earlier notes
remain in place. Add `@<path>` to capture a file snapshot on save: `Tab` completes
paths, pasting a single existing file path inserts an attachment reference, and `@@`
inserts a literal `@`. Relative paths use the selected bead project's workspace when
available, otherwise the TUI's working directory. Press `Ctrl+S` or **Add note** to
save.

Before saving, use `Ctrl+T` to cycle the audience request through automatic
(`Attachments: automatic (SASE decides)`), private (`🔒 private (narrows freely)`), and
public (`🌐 public (confirms on save)`). Automatic applies the audience policy above;
private requests private storage; public requests publication for the note's new
attachments. Existing attachments keep their audience. This key is configurable as
`beads_toggle_note_audience`.

Saving with public selected opens **Publish attachments**. Choose **Publish** to confirm
or cancel to return to the editor. Confirmation does not override policy: an attachment
that cannot be made public rejects the whole note and reopens the editor with an error.
The dialog currently says policy-blocked files stay private, but the save path refuses
the public request instead. Select automatic or private and save again to avoid
requesting publication; sensitive-path restrictions still apply. Publication is
irreversible. The audience cycle belongs to this add-note modal; outside it, the
Beads-pane action reports `Open a bead note (N) first to toggle attachment audience`.

The pane's note body lists each attachment with the audience chip from its stored
descriptor (`🌐` for public, `🔒` for private or for a descriptor that has no visibility
field). The pane does not probe the content store, so availability badges and thumbnails
stay in `sase bead show` and the attachment viewer. On save, SASE prepares attachment
uploads before appending the note, then registers uploads for the post-commit outbox,
using the same path as `sase bead note`. Notes without attachments skip these steps. The
audience policy applies to both interfaces, and agents cannot widen an audience.

Old readers treat every attachment as private: a pre-visibility descriptor (no
`visibility` field) is always private, which is safe for mixed fleets.

`sase bead attachment publish <id> <name> [-y/--yes]` widens one note attachment to
public. It is human-only: inside an agent run it is refused unless it runs as an
approved gate option (the `/sase_gate` path that offers the publish command). It fetches
the bytes, rescans with the current scanner rules, refuses a private bead store,
over-cap sizes, and stored `sensitive_path` or known-secret-value metadata, previews
exactly what becomes public, warns that publication is irreversible, uploads to the
public `<project>--attachments` sidecar, and appends `NoteEdited` with
`visibility: public` and the note text unchanged. `+1` evidence is refused: its manifest
is immutable.

`sase bead attachment unpublish <id> <name> [-y/--yes]` narrows one note attachment to
private, so agents may run it. It ensures a private copy exists (uploading to the
private store, or keeping the bytes local with a `⚠ only on <origin>` warning), removes
the object from the public tree with a `chore(attachments): withdraw <sha>` commit (no
tombstone, so the private copy stays readable), and appends `NoteEdited` with
`visibility: private`. It prints the caveat that forks, clones, caches, and GitHub's
retention of unreachable objects persist, plus the `git filter-repo` runbook for the
attachments repo only.

### Viewing

`sase bead show` draws image previews on a TTY; `read`, JSON, and piped `show` never
draw and print absolute, extension-preserving view paths instead. Previews degrade
without ever failing the command: kitty inline pixels, then subpixel cell thumbnails (≤
10 rows), then text cards (≤ 5 dim lines), then chips. Control the mode with
`show -i/--images auto|cells|kitty|never` or the permanent `bead.show.images` config
(default `auto`). `sase bead attachment open <id> [<name>]` opens one attachment in the
terminal viewer (fetches from the shared store when needed, like `path`; with no name it
opens the only available attachment). Attachment chips are labeled pager links into the
existing viewer, and `attachment:<bead-id>/<name>` refs resolve wherever artifact refs
do.

### Troubleshooting badges

Prose always renders; a preview or fetch failure never fails `show`/`read`. Every
attachment line carries an audience badge: `🌐` means public (readable by anyone who can
read the bead store) and `🔒` means private (or a pre-visibility descriptor, which is
always private). Each attachment also carries one availability badge: no badge means
`cached`, `⇣ not downloaded` means above the `bead.attachments.auto_fetch_max_bytes` cap
(25 MiB; `-d/--download` lifts it for one invocation, `attachment path` and
`attachment open` always fetch), `⇡ pending upload` means the bytes have not reached the
shared store yet, `⚠ only on <machine>` means local-only, `⧉ on <machine>` means
local-only and larger than `bead.attachments.git_max_bytes`, so it can only be fetched
from that machine (see the `%dispatch:<machine>` hint), `🔒 no access (<repo>)` means
the shared store denied the fetch (no grant on that machine),
`⛔ blocked by secret scanning` means the push was rejected and the object stays local,
`✕ unavailable offline` means no reachable copy, `(purged)` means the bytes were purged
behind a tombstone, and `‼ digest mismatch` means the cached bytes failed verification
and were quarantined.

### Mixed-fleet upgrades

Attachment manifests ride on optional event fields, so old readers ignore them: upgrade
every machine to a build with the attachment wire before writing notes with attachments.
Otherwise an older writer regenerates `issues.jsonl` without manifests (the event store
stays authoritative); repair the projection with `sase bead doctor --fix-projection`.

### Large-object store (rclone)

Objects above `bead.attachments.git_max_bytes` (default 50 MiB) need the optional rclone
large tier: set `bead.attachments.large_store` to
`{remote: "<rclone remote:path>", max_bytes: 2147483648}` (default cap 2 GiB). Placement
is deterministic by size — at exactly `git_max_bytes` the object still takes the git
tier; one byte over moves to the large tier. Without a tier that accepts the size, the
command fails before writing unless `-L/--local-only` is given. Uploads stage to a
`.partial-<uuid>` name, move into place, then verify the remote size (and SHA-256 when
the backend reports one).

Objects at or above `bead.attachments.background_upload_min_bytes` (default 64 MiB)
upload in the background: the command queues them in the durable outbox, launches a
detached drain worker, and echoes
`⇡ uploading in background (1.8 GiB) — sase bead attachment push`. The outbox is the
crash recovery — entries left by a dead worker drain on the next `push`, bead sync, or
worker launch. `sase bead attachment push` drains every tier with live per-object
progress; `require_upload: true` stays synchronous instead.

Transfers above 8 MiB draw a Rich progress bar on stderr on a TTY; agents and pipes get
only the final echo line.

Remote setup is per machine, in that machine's `rclone.conf` (`RCLONE_CONFIG` overrides
the path when set):

```ini
# Example: SFTP to a machine you control (private to that host).
[attachments-sftp]
type = sftp
host = attachments.example
user = sase
key_file = ~/.ssh/id_ed25519
shell_type = unix
```

```yaml
# Project config (checked in): points at that remote.
bead:
  attachments:
    large_store: { remote: "attachments-sftp:attachments", max_bytes: 2147483648 }
```

```ini
# Alternative: Cloudflare R2 (S3-compatible, needs credentials).
[r2-attachments]
type = s3
provider = Cloudflare
access_key_id = <R2 token key>
secret_access_key = <R2 token secret>
endpoint = https://<account-id>.r2.cloudflarestorage.com
```

A local directory path also works as the remote (the acceptance tests use one).
`sase doctor -C project.attachment_store` (alias `attachments.store`) warns when the git
sidecar cannot be fetched or the upload outbox still has queued uploads
(`sase bead attachment push` drains them). When a large tier is configured, the same
check warns if `rclone` is missing or that remote is unreachable. No current project
skips the check. No attachments-private clone and no large tier also skips it, and
attachments then stay on this machine unless `bead.attachments.require_upload: true`
rejects the write.

Text viewing rules: prose replaces each `@attachment:<name>` token with `[name]`
(filenames stripped of control and bidi characters). The note label gains `📎 N` when
that note has attachments. Under the prose, an `ATTACHMENTS` block lists
`name · mime · dims · size · sha256:<12 hex>` and, when cached, the absolute view path;
unavailable objects render `✕ unavailable offline` and no path. `show` and `read` both
use this plain form. Compact list/search rows gain a `📎N` suffix only when the total
attachment count is non-zero. Public JSON (`issue_to_wire_dict`) adds `availability`
and, when cached, `local_path` onto each attachment object; the store codec never
carries those keys. JSON contains no bytes and no escape codes. `sase bead history` full
output joins `@attachment:` tokens to the bead's current manifests, printing
`name (not on the current bead)` for a token that is gone.

## Related

- [Beads](beads.md)
- [Bead artifacts](bead-artifacts.md)
