---
create_time: 2026-05-09 14:50:52
status: done
prompt: sdd/prompts/202605/pdf_wrangler_v4_pin.md
---
# Plan: Pin Wrangler v4 So The Worker Deploy Actually Ships The Handbook PDF

## Problem

Downloading `https://sase.sh/downloads/sase-handbook.pdf` from any browser fails. Chrome reports `ERR_INVALID_RESPONSE`
because Cloudflare returns:

```
HTTP/2 404
content-type: application/pdf
content-length: 0
cache-control: public, max-age=3600, must-revalidate
server: cloudflare
```

The `application/pdf` content-type comes from `docs/_headers` matching `/downloads/*.pdf`, but the asset itself is
missing — the response has zero bytes.

The previous fix (commit `6d587b18 fix: deploy docs through Cloudflare Worker`) switched the deploy from a Cloudflare
Pages project (which had been deleted) to a Worker with Static Assets, configured by `wrangler.jsonc`:

```jsonc
{
  "name": "sase",
  "compatibility_date": "2026-05-09",
  "assets": { "directory": "site" },
  "compatibility_flags": ["nodejs_compat"],
}
```

This is an **assets-only Worker** — no `main` entry-point script. Workers with Static Assets shipped behind that exact
shape, but only Wrangler v4 supports it. Wrangler v3 requires a script entry-point and rejects this config.

The `Deploy Docs` workflow uses `cloudflare/wrangler-action@v3` with no `wranglerVersion` input. The action's
compatibility check probes for a locally installed `wrangler@4.86.0`; when it can't find it, it falls back to its
hardcoded default `wrangler@3.90.0` and runs `npx wrangler deploy`. That fails with:

```
✘ [ERROR] Missing entry-point: The entry-point should be specified via the command line
  (e.g. `wrangler deploy path/to/script`) or the `main` config field.
##[error]The process '/usr/local/bin/npx' failed with exit code 1
```

Every `Deploy Docs` run on `master` since the Pages→Worker switch — including the fix commit's own run (`25608256088`)
and every commit after it through the latest at HEAD — has failed at this step. Production therefore still serves
whatever was last successfully deployed before the switch, which never contained `site/downloads/sase-handbook.pdf`.

## Root Cause

The deploy-side toolchain version is incompatible with the deploy-side config:

- `wrangler.jsonc` describes an assets-only Worker (Wrangler v4-only feature).
- `cloudflare/wrangler-action@v3` defaults to installing Wrangler v3 when no version is pinned.

The two halves were committed independently — `wrangler.jsonc` came in via PR #98
(`Add Cloudflare Workers configuration`), and the workflow was switched to `wrangler deploy` later by the deploy-fix
commit, without pinning a Wrangler version compatible with the config.

## Implementation

### 1. Pin Wrangler v4 in the deploy step

Edit `.github/workflows/docs-deploy.yml`, in the `Deploy to Cloudflare Worker` step, add `wranglerVersion` to the
`cloudflare/wrangler-action@v3` `with:` block so the action installs a current v4 release instead of falling back to its
3.90.0 default. Pin to a specific minor (e.g. `"4.30.0"`) rather than the floating major to keep CI deterministic; the
exact patch can be refreshed later.

No other config files need to change. `wrangler.jsonc` is already correct for Workers with Static Assets, and
`docs/_headers` / `docs/_redirects` carry over.

### 2. Verify the deploy on master

After the fix lands, confirm:

- The `Deploy Docs` run for the fix commit succeeds (`gh run view <id>`).
- `curl -I https://sase.sh/downloads/sase-handbook.pdf` returns `HTTP/2 200` with `content-length` matching the built
  artifact (~16 MiB) and `content-type: application/pdf`.
- The PDF magic check in the workflow's existing `Smoke deployed PDF` step passes against
  `https://sase.sh/downloads/sase-handbook.pdf`.

The smoke step in the workflow already polls the production URL after deploy, so a green run is itself the verification
— no separate scripting required.

## Out of Scope

- No changes to `wrangler.jsonc`, `docs/_headers`, the PDF build pipeline, or any docs content. The PDF is being built
  correctly (`just docs-pdf-check` passed on the fix commit's run, producing a 267-page, 16.6 MiB file). The only broken
  link in the chain is the wrangler version used at deploy time.
- No revert of the Pages→Worker switch. Workers with Static Assets is the intended deploy model going forward; the
  existing `wrangler.jsonc` is correct.
- No change to `cloudflare/wrangler-action` major version. v3 of the action supports v4 wrangler via the
  `wranglerVersion` input; bumping the action itself is unnecessary and adds churn.

## Risks & Mitigations

- **Risk:** Wrangler v4 changes deploy-output behavior such that the existing `steps.deploy.outputs.deployment-url`
  lookup in the smoke step returns empty. **Mitigation:** the smoke step already falls back to the canonical
  `https://sase.sh/downloads/sase-handbook.pdf` URL when `DEPLOYMENT_URL` is unset, so a missing output is harmless.
- **Risk:** A pinned Wrangler v4 patch carries a surprise breaking change. **Mitigation:** pin to a known-good minor
  (`4.30.x`) and bump deliberately later, rather than tracking `latest`.
- **Risk:** Cloudflare API token scope was sufficient for Pages but not for Worker deploys. **Mitigation:** the prior
  run reached the deploy step and only failed on the entry-point check — i.e. authentication already succeeded with the
  current token. No token rotation needed.
