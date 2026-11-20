#!/usr/bin/env bash
# Dump the Notes API database into state/backups/ (pg_dump custom format: compressed, restorable
# table by table with pg_restore). Keeps BACKUP_KEEP_DAYS days (14 by default).
#   deploy/production/backup.sh [label]
# rollout.sh runs it before every migration; cron runs it nightly (see bootstrap.sh).
set -euo pipefail
source "$(dirname "$0")/lib.sh"
label=${1:-manual}

if [[ -z $("${compose[@]}" ps --quiet --status running db) ]]; then
    log "the database is not running yet: nothing to back up"
    exit 0
fi

file="$state_dir/backups/notes-$(date -u +%Y%m%dT%H%M%SZ)-$label.dump"
"${compose[@]}" exec -T db pg_dump --username notes --format custom notes >"$file.part"
mv "$file.part" "$file"
find "$state_dir/backups" -name 'notes-*.dump' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
log "wrote $file ($(du -h "$file" | cut -f1))"
