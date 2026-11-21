#!/usr/bin/env bash
# Zero-downtime deploy of the Notes API on one server. CI runs it over SSH (through the
# ci-command wrapper); you run it by hand to roll back.
#   NOTES_IMAGE=ghcr.io/<owner>/notes-api deploy/production/rollout.sh <tag>   deploy a tag
#   SKIP_PULL=1 deploy/production/rollout.sh rollback   back to the newest known-good release
#   deploy/production/rollout.sh mark-good              the current release passed its smoke test
# Steps: pull; back up; migrate (one-off container) unless this is a rollback or the image is
# older than the database; pin Caddy to the running api replicas; start new replicas next to
# them and wait until Docker reports them healthy; pin Caddy to the new ones (drain); stop the
# old ones gracefully; replace the worker; apply the rest of the stack and let Caddy discover
# every replica again. No request reaches a replica that is still starting or already
# stopping. If the new replicas never become healthy they are removed and the old ones serve.
set -euo pipefail
source "$(dirname "$0")/lib.sh"
replicas=${API_REPLICAS:-2}
history="$state_dir/history.log" # every deploy: time, tag (and "rollback")
good="$state_dir/known-good.log" # releases that passed the smoke test (mark-good)
bad="$state_dir/rolled-back.log" # releases a rollback left: never a rollback target again

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
current_tag() { sed -n 's/^TAG=//p' "$state_dir/release.env" 2>/dev/null || true; }
rolled_back_from() { [[ -f $bad ]] && cut -d ' ' -f 2 "$bad" | grep -qxF "$1"; }

rollback_target() { # the newest known-good release that is not $1 and was never rolled back
    local tag
    [[ -f $good ]] || return 1
    while read -r _ tag; do
        if [[ $tag != "$1" ]] && ! rolled_back_from "$tag"; then
            echo "$tag"
            return 0
        fi
    done < <(tac "$good")
    return 1
}


target=${1:?usage: rollout.sh <image tag> | rollback | mark-good}
mode=deploy
if [[ $target == mark-good ]]; then
    tag=$(current_tag)
    [[ -n $tag ]] || { log "no release recorded in $state_dir/release.env"; exit 1; }
    if [[ -f $bad ]]; then # a release that passes the smoke test again is a candidate again
        { grep -v " $tag\$" "$bad" || true; } >"$bad.new" && mv "$bad.new" "$bad"
    fi
    printf '%s %s\n' "$(stamp)" "$tag" >>"$good"
    log "$tag is known good"
    exit 0
fi
if [[ $target == rollback ]]; then
    mode=rollback
    current=$(current_tag)
    if ! target=$(rollback_target "$current"); then
        log "no known-good release other than ${current:-none} in $good (CI runs mark-good)"
        exit 1
    fi
    if [[ -n $current ]]; then
        printf '%s %s\n' "$(stamp)" "$current" >>"$bad"
    fi
    log "rolling back from ${current:-none} to $target (known good)"
fi
if [[ -z ${NOTES_IMAGE:-} && -f $state_dir/release.env ]]; then
    NOTES_IMAGE=$(sed -n 's/^NOTES_IMAGE=//p' "$state_dir/release.env")
fi
export NOTES_IMAGE=${NOTES_IMAGE:?NOTES_IMAGE is not set (CI passes it; release.env keeps it)}
export TAG=$target


database_revision() { # the Alembic revision of the database ("" before the first migration)
    "${compose[@]}" exec -T db psql -U notes -d notes -tAc \
        "SELECT version_num FROM alembic_version" 2>/dev/null | tr -d '[:space:]' || true
}

image_knows() { # 0 if this image's migrations include revision $1, 1 if it is older
    local output
    if output=$("${compose[@]}" run --rm --no-deps -T migrate alembic show "$1" 2>&1); then
        return 0
    fi
    if [[ $output == *"Can't locate revision"* ]]; then
        return 1
    fi
    log "alembic show $1 failed: $output"
    exit 1
}

if [[ ${SKIP_PULL:-0} != 1 ]]; then
    log "pulling the images ($NOTES_IMAGE:$TAG and the pinned services)"
    "${compose[@]}" pull --quiet
fi
log "database and redis"
"${compose[@]}" up --detach --wait db redis
deploy/production/backup.sh "pre-$TAG"

revision=$(database_revision)
if [[ $mode == rollback ]]; then
    log "migrations: skipped (a rollback never migrates; the database keeps its schema)"
elif [[ -n $revision ]] && ! image_knows "$revision"; then
    log "migrations: skipped (the database is at $revision, newer than this image)"
else
    log "migrations: alembic upgrade head (old replicas keep serving: expand/contract)"
    "${compose[@]}" run --rm --no-deps migrate
fi


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
# every service but the one-off migrate job (a plain "up" would run it, and after a rollback
# the older image's "alembic upgrade head" fails on the newer schema)
mapfile -t services < <("${compose[@]}" config --services | grep -vx migrate)
"${compose[@]}" up --detach --wait --remove-orphans --no-deps "${services[@]}"
"${compose[@]}" exec -T proxy caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1
"${compose[@]}" kill --signal HUP prometheus >/dev/null 2>&1 # re-read prometheus.yml, alerts.yml

mapfile -t images < <("${compose[@]}" ps --format '{{.Image}}' api | sort -u)
if [[ ${#images[@]} -ne 1 || ${images[0]} != "$NOTES_IMAGE:$TAG" ]]; then
    log "expected every api replica on $NOTES_IMAGE:$TAG, found: ${images[*]}"
    exit 1
fi
printf 'NOTES_IMAGE=%s\nTAG=%s\n' "$NOTES_IMAGE" "$TAG" >"$state_dir/release.env"
entry="$(stamp) $TAG"
[[ $mode == deploy ]] || entry+=" $mode"
echo "$entry" >>"$history"


if [[ ${PRUNE_IMAGES:-1} == 1 ]]; then # keep the 5 newest images and the rollback targets
    keep=$({ echo "$TAG"; tail -n 3 "$good" 2>/dev/null | cut -d ' ' -f 2; } | sort -u)
    docker images "$NOTES_IMAGE" --format '{{.Tag}}' | tail -n +6 |
        { grep -vxF "$keep" || true; } | sed "s|^|$NOTES_IMAGE:|" |
        xargs -r docker rmi >/dev/null 2>&1 || true
    docker image prune --force >/dev/null
fi
log "deployed $TAG: ${#images[@]} image, $("${compose[@]}" ps --quiet api | wc -l) healthy api replicas"
