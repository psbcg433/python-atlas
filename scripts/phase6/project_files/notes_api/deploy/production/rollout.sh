#!/usr/bin/env bash
# Zero-downtime deploy of the Notes API on one server. CI runs it over SSH after every push to
# main; you run it by hand to roll back.
#   NOTES_IMAGE=ghcr.io/<owner>/notes-api deploy/production/rollout.sh <tag>   deploy a tag
#   SKIP_PULL=1 deploy/production/rollout.sh rollback          the release before the current one
# Steps: pull; back up; migrate (one-off container); pin Caddy to the running api replicas;
# start new replicas next to them and wait until Docker reports them healthy; pin Caddy to the
# new ones (drain); stop the old ones gracefully; replace the worker; apply the rest of the
# stack and let Caddy discover every replica again. No request reaches a replica that is still
# starting or already stopping. If the new replicas never become healthy they are removed and
# the old ones keep serving.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
replicas=${API_REPLICAS:-2}
history="$state_dir/history.log"

target=${1:?usage: rollout.sh <image tag> | rollback}
if [[ $target == rollback ]]; then
    if [[ ! -f $history || $(wc -l <"$history") -lt 2 ]]; then
        log "rollback needs two recorded deploys in $history"
        exit 1
    fi
    target=$(tail -n 2 "$history" | head -n 1 | cut -d ' ' -f 2)
    log "rolling back to $target"
fi
if [[ -z ${NOTES_IMAGE:-} && -f $state_dir/release.env ]]; then
    NOTES_IMAGE=$(sed -n 's/^NOTES_IMAGE=//p' "$state_dir/release.env")
fi
export NOTES_IMAGE=${NOTES_IMAGE:?NOTES_IMAGE is not set (CI passes it; release.env keeps it)}
export TAG=$target


if [[ ${SKIP_PULL:-0} != 1 ]]; then
    log "pulling the images ($NOTES_IMAGE:$TAG and the pinned services)"
    "${compose[@]}" pull --quiet
fi

log "database and redis"
"${compose[@]}" up --detach --wait db redis
deploy/production/backup.sh "pre-$TAG"

log "migrations: alembic upgrade head (old replicas keep serving: expand/contract)"
"${compose[@]}" run --rm --no-deps migrate


pin_upstreams() { # Caddy sends new requests only to these containers (ids) until the next reload
    local names
    names=$(docker inspect --format '{{.Name}}:8000' "$@" | sed 's|^/||' | tr '\n' ' ')
    "${compose[@]}" exec -T --env NOTES_UPSTREAM_MODE=static --env NOTES_UPSTREAMS="$names" \
        proxy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1
}

mapfile -t old < <("${compose[@]}" ps --quiet api)
proxy_running=$("${compose[@]}" ps --quiet --status running proxy)
if ((${#old[@]} > 0)) && [[ -n $proxy_running ]]; then
    log "pin: Caddy keeps sending requests to the ${#old[@]} running replicas only"
    pin_upstreams "${old[@]}"
fi
log "starting $replicas new api replicas next to ${#old[@]} running"
if ! "${compose[@]}" up --detach --no-deps --no-recreate --wait --wait-timeout 120 \
    --scale "api=$((${#old[@]} + replicas))" api; then
    log "the new replicas did not become healthy: removing them; the old ones keep serving"
    mapfile -t failed < <(comm -13 <(printf '%s\n' "${old[@]}" | sort) \
        <("${compose[@]}" ps --all --quiet api | sort))
    if ((${#failed[@]} > 0)); then
        docker rm --force "${failed[@]}" >/dev/null
    fi
    exit 1
fi

if ((${#old[@]} > 0)); then
    mapfile -t new < <(comm -13 <(printf '%s\n' "${old[@]}" | sort) \
        <("${compose[@]}" ps --quiet api | sort))
    if [[ -n $proxy_running ]]; then
        log "drain: Caddy now sends new requests only to the ${#new[@]} new replicas"
        pin_upstreams "${new[@]}"
        sleep "${DRAIN_SECONDS:-2}" # requests already sent to the old replicas finish
    fi
    log "stopping ${#old[@]} old replicas (SIGTERM; up to 30 s to finish requests in flight)"
    docker stop --timeout 30 "${old[@]}" >/dev/null
    docker rm "${old[@]}" >/dev/null
fi


log "worker"
"${compose[@]}" up --detach --no-deps --wait worker
log "the rest of the stack; Caddy back to discovering every replica"
"${compose[@]}" up --detach --wait --remove-orphans
"${compose[@]}" exec -T proxy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1
"${compose[@]}" kill --signal HUP prometheus >/dev/null 2>&1 # re-read prometheus.yml, alerts.yml

mapfile -t images < <("${compose[@]}" ps --format '{{.Image}}' api | sort -u)
if [[ ${#images[@]} -ne 1 || ${images[0]} != "$NOTES_IMAGE:$TAG" ]]; then
    log "expected every api replica on $NOTES_IMAGE:$TAG, found: ${images[*]}"
    exit 1
fi
printf 'NOTES_IMAGE=%s\nTAG=%s\n' "$NOTES_IMAGE" "$TAG" >"$state_dir/release.env"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$TAG" >>"$history"


if [[ ${PRUNE_IMAGES:-1} == 1 ]]; then # keep the 5 newest releases for quick rollbacks
    docker images "$NOTES_IMAGE" --format '{{.Tag}}' | tail -n +6 | { grep -vx "$TAG" || true; } |
        sed "s|^|$NOTES_IMAGE:|" | xargs -r docker rmi >/dev/null 2>&1 || true
    docker image prune --force >/dev/null
fi
log "deployed $TAG: ${#images[@]} image, $("${compose[@]}" ps --quiet api | wc -l) healthy api replicas"
