#!/usr/bin/env bash
set -uo pipefail
host=athena
project=sase
key=gh_sase-org__sase
src="$HOME/.sase/projects/$key/agents-publication-outbox.json"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$HOME/.sase/recovery-backups/sase-1nv.5/athena-sase-$stamp"
backup="$backup_dir/agents-publication-outbox.json"
printf 'host=%s\nproject=%s\nsource=%s\nbackup=%s\n' "$host" "$project" "$src" "$backup" >&2
if [ ! -f "$src" ]; then printf 'error=missing_source\n' >&2; exit 41; fi
mkdir -p "$backup_dir" || exit 42
before="$(sha256sum "$src" | awk '{print $1}')"
cp -p -- "$src" "$backup" || exit 43
backup_hash="$(sha256sum "$backup" | awk '{print $1}')"
after_backup="$(sha256sum "$src" | awk '{print $1}')"
printf 'backup_started_utc=%s\nsource_before_sha256=%s\nbackup_sha256=%s\nsource_after_backup_sha256=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$before" "$backup_hash" "$after_backup" >&2
if [ "$before" != "$backup_hash" ] || [ "$after_backup" != "$backup_hash" ]; then printf 'backup_preflight=FAILED\n' >&2; exit 44; fi
printf 'backup_preflight=PASSED\n' >&2
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
sase agent sync --repair-revisions --project sase --json
rc=$?
set -e
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
post="$(sha256sum "$src" | awk '{print $1}')"
printf 'report_started_utc=%s\nreport_finished_utc=%s\nreport_exit_code=%s\npost_source_sha256=%s\nreport_matches_backup=%s\n' "$started" "$finished" "$rc" "$post" "$([ "$post" = "$backup_hash" ] && echo yes || echo no)" >&2
exit "$rc"
