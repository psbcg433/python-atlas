# Sourced by dc, backup.sh and rollout.sh: move to the project folder (the one holding
# compose.yaml: /srv/notes on the server), find the state folder, build the compose command.
# shellcheck shell=bash

cd "$(dirname "${BASH_SOURCE[0]}")/../.." || exit 1
state_dir=${NOTES_STATE_DIR:-state} # release.env, history.log, backups/ (never committed)
mkdir -p "$state_dir/backups"

compose=(docker compose -f compose.yaml -f compose.prod.yaml)
for env_file in .env "$state_dir/release.env"; do # later files win; the shell's own wins over both
    if [[ -f $env_file ]]; then
        compose+=(--env-file "$env_file")
    fi
done


log() {
    printf '%s %s: %s\n' "$(date -u +%H:%M:%S)" "$(basename "$0")" "$*"
}
