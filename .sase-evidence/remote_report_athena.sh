#!/usr/bin/env bash
set -u
host=athena
project=sase
src="$HOME/.sase/projects/gh_sase-org__sase/agents-publication-outbox.json"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$HOME/.sase/recovery-backups/sase-1nv.5/athena-sase-$stamp"
backup="$backup_dir/agents-publication-outbox.json"
printf 'host=%s\nproject=%s\nsource=%s\nbackup=%s\n' "$host" "$project" "$src" "$backup" >&2
printf 'remote_started_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
if [ ! -f "$src" ]; then
  printf 'error=missing_source\n' >&2
  exit 41
fi
mkdir -p "$backup_dir" || exit 42
cp -p "$src" "$backup" || exit 43
pre_source_sha="$(sha256sum "$src" | awk '{print $1}')"
backup_sha="$(sha256sum "$backup" | awk '{print $1}')"
printf 'pre_source_sha256=%s\nbackup_sha256=%s\n' "$pre_source_sha" "$backup_sha" >&2
if [ "$pre_source_sha" != "$backup_sha" ]; then
  printf 'backup_preflight=FAILED\n' >&2
  exit 44
fi
printf 'backup_preflight=PASSED\n' >&2
set +e
sase agent sync --repair-revisions --project sase --json
rc=$?
set -e
post_source_sha="$(sha256sum "$src" | awk '{print $1}')"
printf 'report_exit_code=%s\npost_source_sha256=%s\nremote_finished_utc=%s\n' "$rc" "$post_source_sha" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
exit "$rc"
