# SASE Agents Sidecar

This repository stores portable bundles for completed SASE agents whose work is associated with commits in the source
repository.

## Privacy and publication

Initializing or syncing this sidecar publishes full agent chat transcripts, including prompts and responses, together
with agent metadata and commit associations. The repository's configured visibility controls who can access that data.
Set the `agents` sidecar visibility to `private` before creation to restrict access, or set `disabled: true` to opt out.

## Bundle layout

- `manifest.json` indexes exported agents by their machine-qualified name.
- `agents/<qualified-name>/meta.json` contains portable agent metadata.
- `agents/<qualified-name>/chat.md` contains the full chat transcript.
- `agents/<qualified-name>/commits.json` contains associated commit metadata.

Run `sase agent sync` to exchange commit-associated agent bundles with the configured sidecar repository.
