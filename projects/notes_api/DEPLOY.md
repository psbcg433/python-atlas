# Deploying the Notes API to a Hetzner Cloud server

A step-by-step runbook for the steps that need you: accounts, keys, secrets, the first
deploy, checking HTTPS, monitoring, the live load test and rollback. Everything else is
already in the repository:

| In the repository | What it does |
| --- | --- |
| `compose.yaml` + `compose.prod.yaml` | the production stack: Caddy (HTTPS), 2 API replicas, worker, PostgreSQL, Redis, Prometheus, Grafana; only ports 80 and 443 are public |
| `deploy/production/bootstrap.sh` | one-time server setup: Docker, the `deploy` user, swap, security updates, nightly backups, then SSH locked down (keys only, only `deploy`, no root) |
| `deploy/production/ci-command` | the only commands the CI key may run on the server (installed by `bootstrap.sh`) |
| `deploy/production/rollout.sh` | a zero-downtime deploy: backup, migrations, new replicas, drain, swap; also `mark-good` and `rollback` (to the last known-good release, without migrating) |
| `deploy/production/backup.sh`, `dc` | database dumps; `docker compose` with the production files |
| `deploy/production/Caddyfile` | automatic Let's Encrypt certificate, HTTP→HTTPS, HSTS, load balancing |
| `deploy/production/prometheus.yml`, `alerts.yml`, `grafana/` | metrics, alert rules, a provisioned dashboard |
| `.github/workflows/notes-api.yml` | CI/CD: lint, types, tests, build, scan, push to GHCR, **deploy on every push to `main`** |
| `.github/workflows/notes-api-uptime.yml` | an HTTPS uptime and certificate check every 15 minutes |

**Cost:** roughly €4–8 per month for a small server; Hetzner bills by the hour up to a monthly
cap and stops billing when you delete the server. Check current prices before you start.
**Time:** about 45 minutes, plus one CI run (about 10 minutes).

## The secrets you will create

| Name | Where it lives | What it is |
| --- | --- | --- |
| `DEPLOY_SSH_KEY` | GitHub → environment `production` → secret | private key CI uses to log in as `deploy` (step 2) |
| `DEPLOY_KNOWN_HOSTS` | GitHub → environment `production` → secret | the server's SSH host key, so CI can detect a man-in-the-middle (step 9) |
| `NOTES_HOST` | GitHub → repository **variable** (not secret) | the hostname, e.g. `203-0-113-10.sslip.io` |
| `POSTGRES_PASSWORD` | server: `/srv/notes/.env` | database password (step 8) |
| `GRAFANA_ADMIN_PASSWORD` | server: `/srv/notes/.env` | Grafana `admin` password (step 8) |
| `NOTES_SITE`, `ACME_EMAIL` | server: `/srv/notes/.env` | hostname for the certificate, Let's Encrypt e-mail (not secret) |
| JWT signing key | server: `/srv/notes/.secrets/notes_jwt_secret` | signs access tokens (step 8) |
| Redis password | server: `/srv/notes/.secrets/notes_redis_password` | Redis `requirepass`; the app adds it to its Redis URL (step 8) |

Nothing secret is committed, and the image registry needs no extra token: the deploy job logs
the server in to GHCR with the job's own short-lived `GITHUB_TOKEN`, and logs it out again.

## 1. Check your tools

On your machine you need `git`, `ssh`, `curl`, `openssl` and `uv`. The GitHub CLI `gh` is
optional, but steps 9–10 show its commands (`gh auth login` once). Each command prints a
version; a missing tool prints an error and the others still run:

```bash
ssh -V; openssl version; curl --version | head -1; gh --version | head -1
```

## 2. Create two SSH keys

Your own key logs you in. A separate key, with no passphrase, is for CI only, so you can
revoke it on its own:

```bash
ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519 -C "you@laptop"     # your key (keep a passphrase)
ssh-keygen -t ed25519 -f ~/.ssh/notes_deploy -N "" -C "notes-deploy-ci" # the CI key
```

## 3. Create the Hetzner account and project

1. Sign up at <https://accounts.hetzner.com/signUp>, confirm the e-mail and add a payment
   method. Hetzner may ask for identity verification before the first server.
2. Open the [Cloud Console](https://console.hetzner.cloud/) → **New project** → name it
   `notes`.
3. In the project: **Security → SSH keys → Add SSH key**. Paste the output of
   `cat ~/.ssh/id_ed25519.pub` (your key, not the CI key).

## 4. Create a firewall

**Firewalls → Create firewall**, name `notes-web`, inbound rules (delete nothing else):

| Protocol | Port | Source | Why |
| --- | --- | --- | --- |
| TCP | 22 | Any IPv4, Any IPv6 | SSH (you and CI) |
| TCP | 80 | Any IPv4, Any IPv6 | Let's Encrypt HTTP challenge, redirect to HTTPS |
| TCP | 443 | Any IPv4, Any IPv6 | HTTPS |
| UDP | 443 | Any IPv4, Any IPv6 | HTTP/3 |
| ICMP | — | Any IPv4, Any IPv6 | ping |

The Hetzner firewall filters traffic before it reaches the server, so Docker's own port
rules cannot bypass it.

## 5. Create the server

**Servers → Add server**:

- **Location:** the one closest to you and your users (for example Singapore for South Asia,
  Helsinki or Nuremberg for Europe). Network distance shows up directly in the load test.
- **Image:** Ubuntu 24.04 (or a newer LTS).
- **Type:** shared vCPU, x86, **2 vCPU / 4 GB RAM** (the smallest plan with 4 GB; plan names
  such as CX22/CX23 change over time).
- **Networking:** public IPv4 on, IPv6 on.
- **SSH keys:** select yours. **Firewalls:** select `notes-web`.
- **Backups:** optional (+20% of the server price): whole-server snapshots, in addition to the
  nightly database dumps that `bootstrap.sh` sets up.
- **Name:** `notes-prod` → **Create & Buy now**. Copy the IPv4 address.

## 6. Pick the hostname

[sslip.io](https://sslip.io) turns an IP address written with dashes into a hostname that
resolves to it. You need no account, and Let's Encrypt issues certificates for it. Set two
shell variables (replace the address) and keep this terminal open for the following steps:

```bash
export NOTES_IP=203.0.113.10
export NOTES_HOST="${NOTES_IP//./-}.sslip.io"     # 203-0-113-10.sslip.io
getent hosts "$NOTES_HOST" || nslookup "$NOTES_HOST"  # must print $NOTES_IP
```

## 7. Bootstrap the server

```bash
cd projects/notes_api
scp deploy/production/bootstrap.sh deploy/production/ci-command "root@$NOTES_HOST:"
ssh "root@$NOTES_HOST" bash bootstrap.sh "\"$(cat ~/.ssh/notes_deploy.pub)\""
ssh "deploy@$NOTES_HOST" 'docker compose version && ls -ld /srv/notes'
```

The first `scp` asks you to confirm the server's host key. That is the moment to trust it.
The inner `\"…\"` keep the CI key one argument on the server (without them the remote shell
splits it into three words and the script refuses it).

What the script sets up, besides Docker:

- **The `deploy` user** gets your key (copied from root's) and the CI key. The CI key is
  bound to `/usr/local/sbin/notes-ci-command` (`restrict,command="…"`): whatever CI asks for,
  sshd runs that wrapper, which allows only `rsync` into `/srv/notes`, `registry-login`,
  `registry-logout`, `rollout <image> <sha>`, `rollback` and `mark-good`. No shell, no Docker
  commands, no port forwarding.
- **SSH is locked down last**: `/etc/ssh/sshd_config.d/00-notes.conf` sets
  `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`,
  `AllowUsers deploy` and `MaxAuthTries 3`. sshd keeps the first value it reads, and `00-`
  sorts before cloud-init's `50-cloud-init.conf`. The script checks the file with `sshd -t`
  before the reload and verifies the effective settings with `sshd -T` after it. It stops,
  without changing SSH, if `deploy` would have no key of yours.

From now on, log in as `deploy`; **root can no longer log in over SSH**. `deploy` may run one
root command without a password, `sudo reboot`. For anything else that needs root, use the
Hetzner Cloud Console (server → **Console**, or **Rescue**). `deploy` is in the `docker`
group, which is root-equivalent: keep your key safe.

## 8. Put the secrets on the server

The values are generated on your machine and written straight into a file that only `deploy`
can read. Replace the e-mail address:

```bash
ssh "deploy@$NOTES_HOST" 'umask 077 && cat > /srv/notes/.env' <<EOF
NOTES_SITE=$NOTES_HOST
ACME_EMAIL=you@example.com
POSTGRES_PASSWORD=$(openssl rand -hex 32)
GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 24)
EOF
ssh "deploy@$NOTES_HOST" 'cd /srv/notes/.secrets \
    && openssl rand -base64 48 | tr -d "\n" > notes_jwt_secret \
    && openssl rand -hex 32 | tr -d "\n" > notes_redis_password \
    && chmod 444 notes_jwt_secret notes_redis_password && ls -l /srv/notes/.env /srv/notes/.secrets'
ssh "deploy@$NOTES_HOST" 'grep GRAFANA_ADMIN_PASSWORD /srv/notes/.env'  # save it in your password manager
```

The two secret files are world-readable inside a folder only `deploy` can open, because the
containers' users (the app's uid 10001, Redis's own user) must read them. Redis starts with
`requirepass` from its file, and the app adds the same password to its Redis URL. Admins
are not configured here: you promote your account with a command in step 11. `POSTGRES_PASSWORD` takes effect when the database is
first created. To change it later, use `ALTER USER notes PASSWORD '…'` as well as `.env`.

## 9. Configure GitHub

Run from the repository folder (the commands find the repository from `git remote`). In the
web interface, the same settings are under **Settings → Environments** and
**Settings → Secrets and variables → Actions**.

```bash
gh api --method PUT "repos/{owner}/{repo}/environments/production" > /dev/null   # the environment
gh secret set DEPLOY_SSH_KEY --env production < ~/.ssh/notes_deploy               # the CI private key
ssh-keyscan -t ed25519 "$NOTES_HOST" 2> /dev/null | gh secret set DEPLOY_KNOWN_HOSTS --env production
gh variable set NOTES_HOST --body "$NOTES_HOST"                                   # repository variable
gh secret list --env production && gh variable list
```

Check that the scanned host key is the one you trusted in step 7: both commands must print
the same fingerprint:

```bash
ssh-keyscan -t ed25519 "$NOTES_HOST" 2> /dev/null | ssh-keygen -lf -
ssh-keygen -lF "$NOTES_HOST" | grep -i ed25519
```

**Required, not optional: protect the `production` environment.** The CI key can do little
on the server (step 7), but it can still deploy, and a deploy runs the scripts it copies.
Make every deploy wait for your approval and allow only `main` to deploy:

```bash
gh api --method PUT "repos/{owner}/{repo}/environments/production" \
    -F "reviewers[][type]=User" -F "reviewers[][id]=$(gh api user --jq .id)" \
    -F "deployment_branch_policy[protected_branches]=false" \
    -F "deployment_branch_policy[custom_branch_policies]=true" > /dev/null
gh api --method POST "repos/{owner}/{repo}/environments/production/deployment-branch-policies" \
    -f name=main -f type=branch > /dev/null
gh api "repos/{owner}/{repo}/environments/production" \
    --jq '[.protection_rules[].type], .deployment_branch_policy'   # required_reviewers, custom: true
gh api "repos/{owner}/{repo}/environments/production/deployment-branch-policies" \
    --jq '[.branch_policies[].name]'                                # ["main"]
```

In the web interface: **Settings → Environments → production** → *Required reviewers*: you;
*Deployment branches and tags*: *Selected branches and tags*, rule `main`. Required
reviewers are free on public repositories; a private one needs a paid GitHub plan. From now
on each run of the `deploy` job waits under **Review deployments** until you approve it.

## 10. First deploy

The commit with this setup is on your local `main`. Pushing it runs the whole pipeline. The
`deploy` job runs only on `main`, only after lint, types, tests, build and scan pass, and only
after you approve it (**Actions** → the run → **Review deployments** → **Approve and deploy**):

```bash
git push origin main
gh run watch "$(gh run list --workflow notes-api.yml --branch main --limit 1 --json databaseId --jq '.[0].databaseId')"
```

If `main` was pushed before the variable existed, start a run by hand:
`gh workflow run notes-api.yml --ref main`.

The deploy job copies `compose.yaml`, `compose.prod.yaml`, `deploy/Caddyfile` and
`deploy/production/` to `/srv/notes` (`rsync --delete`: files removed from the repository
disappear from the server; `.env`, `.secrets/` and `state/` are never touched) and runs
`rollout.sh <commit sha>`. On the first run, Caddy obtains the certificate in the first
seconds. The job ends with an HTTPS smoke test; when it passes, the job marks the release
*known good* (`rollout.sh mark-good`) and writes the URL into the run summary.

If the job fails with `denied` while pulling from GHCR: open the `notes-api` package
(your GitHub profile → **Packages**) → **Package settings → Manage Actions access**. Add this
repository with the **Read** role, then re-run the job.

## 11. Verify HTTPS

```bash
curl -sI "http://$NOTES_HOST/health/live" | head -3                  # 308 Permanent Redirect → https://
curl -s "https://$NOTES_HOST/health/ready"; echo                    # {"status":"ok","checks":{"database":"ok","redis":"ok"}}
curl -s -o /dev/null -w '%{http_code}\n' "https://$NOTES_HOST/openapi.json"  # 404: no schema in production
curl -s "https://$NOTES_HOST/health/startup"; echo                  # migrations: ok
curl -sI "https://$NOTES_HOST/health/live" | grep -i strict-transport  # HSTS
curl -s -o /dev/null -w '%{http_code}\n' "https://$NOTES_HOST/metrics"  # 404: internal only
openssl s_client -connect "$NOTES_HOST:443" -servername "$NOTES_HOST" < /dev/null 2> /dev/null \
    | openssl x509 -noout -issuer -subject -dates                   # issuer: Let's Encrypt
```

Then create your account. Every account starts as an ordinary user (`"role": "user"`);
make yours an admin with the operator command, which runs in a one-off container of the
current image on the server, never over HTTP:

```bash
curl -s "https://$NOTES_HOST/api/v1/auth/register" -H 'Content-Type: application/json' \
    -d '{"email": "you@example.com", "password": "<a long passphrase>"}'; echo
ssh "deploy@$NOTES_HOST" '/srv/notes/deploy/production/dc run --rm --no-deps migrate \
    python -m notes_api.manage promote-admin you@example.com'          # you@example.com: role admin
```

Log in again afterwards: tokens issued before the promotion do not carry the `admin` scope.
`demote-admin <email>` takes the role away (effective on the next request).

## 12. Monitoring

**Dashboards** (Grafana and Prometheus listen on the server's localhost only). Open an SSH
tunnel, then browse:

```bash
ssh -N -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 "deploy@$NOTES_HOST"
```

- Grafana: <http://localhost:3000>, user `admin`, the password from step 8 → **Dashboards →
  Notes API → Notes API**. It shows request rate, 5xx ratio, p50/p95/p99, requests in
  progress, replicas up, writes, and cache hit ratio.
- Prometheus: <http://localhost:9090/targets> (both API replicas `UP`) and
  <http://localhost:9090/alerts> (`NotesApiDown`, `NotesApiHighErrorRate`, `NotesApiSlowP95`).

**Uptime check:** the `notes-api-uptime` workflow runs every 15 minutes. Run it once now, and
make sure GitHub e-mails you about failed runs (**Settings → Notifications → System →
Actions → Email, failed workflows only**):

```bash
gh workflow run notes-api-uptime.yml && sleep 20 && gh run list --workflow notes-api-uptime.yml --limit 1
```

**Logs** are JSON lines, rotated at 5 × 10 MB per container:

```bash
ssh "deploy@$NOTES_HOST" '/srv/notes/deploy/production/dc ps'
ssh "deploy@$NOTES_HOST" '/srv/notes/deploy/production/dc logs --since 1h --no-log-prefix api' \
    | jq -c 'select(.level == "error" or .level == "warning")'
ssh "deploy@$NOTES_HOST" '/srv/notes/deploy/production/dc logs --since 10m --no-log-prefix proxy' \
    | jq -c 'select(.status >= 500) | {ts, status, uri: .request.uri}'
```

## 13. Live load test

Ask Claude to run it ("run the load test against the live URL and fill in LOAD_TEST.md"), or
follow *How to run it* in [LOAD_TEST.md](LOAD_TEST.md). It fills the *Results — live*
section. The test registers its own pool of `load-…@example.com` accounts first (about five
minutes, at the pace the registration limit allows) and deletes them when it stops
(`DELETE /api/v1/users/me`; their notes, tokens and events cascade). Only if a run was
killed before it could clean up, delete what is left:

```bash
ssh "deploy@$NOTES_HOST" "/srv/notes/deploy/production/dc exec -T db psql -U notes -c \
    \"DELETE FROM users WHERE email LIKE 'load-%@example.com'\""   # notes, tokens, events cascade
```

## 14. Rollback

**How it chooses the release.** After a deploy's smoke test passes, the workflow runs
`rollout.sh mark-good`, which appends the release to `state/known-good.log`. A rollback goes
to the newest known-good release that is neither the current one nor one a rollback left
(those are recorded in `state/rolled-back.log`). So after A (good), B (bad) and a rollback
to A, a second rollback goes further back to the good release before A, never to B; with
nothing older it stops with *no known-good release other than A*.

**A rollback never migrates.** The database keeps the newer release's schema, and the older
code runs on it: migrations follow expand/contract (step 7 of the course project), and the
startup probe accepts a database *ahead* of the code (`"migrations": "ok"`). The same goes
for a deploy of an older tag by name: when the database is at a revision the image does not
know, `rollout.sh` logs *migrations: skipped (the database is at …, newer than this image)*.

**Automatic:** if the smoke test after a deploy fails, the workflow runs the rollback
itself (through the CI key's `rollback` command).

**By hand** (the image is still on the server; the replicas are replaced the same
zero-downtime way):

```bash
ssh "deploy@$NOTES_HOST" 'SKIP_PULL=1 /srv/notes/deploy/production/rollout.sh rollback'
ssh "deploy@$NOTES_HOST" 'cd /srv/notes/state && tail -5 history.log known-good.log rolled-back.log'
```

**To a specific commit:** `SKIP_PULL=1 /srv/notes/deploy/production/rollout.sh <sha>` (the
server keeps the five newest images and the three newest known-good ones). Then
`rollout.sh mark-good` once you have checked it, so that it can be a rollback target.
**The lasting fix:** `git revert` the bad commit and push; CI deploys the result.

**The database is never rolled back automatically.** Rolling back the schema
(`alembic downgrade`) is a separate, deliberate decision. A destructive restore from a
backup is the last resort. It loses every write since the dump:

```bash
ssh "deploy@$NOTES_HOST"
cd /srv/notes && ls -lt state/backups | head            # pre-<sha> dumps are taken before each deploy
deploy/production/dc stop api worker
deploy/production/dc exec -T db pg_restore -U notes -d notes --clean --if-exists < state/backups/<file>.dump
deploy/production/dc start api worker
```

## 15. Routine operations

| Task | How |
| --- | --- |
| Security updates | automatic (`unattended-upgrades`); reboot when `/var/run/reboot-required` exists: `ssh deploy@$NOTES_HOST sudo reboot` (containers restart by themselves) |
| Copy backups off the server | `scp "deploy@$NOTES_HOST:/srv/notes/state/backups/*.dump" ~/notes-backups/` (dumps on the server die with the server) |
| Disk usage | `ssh deploy@$NOTES_HOST 'df -h / && docker system df'` |
| Rotate the JWT key (logs everyone out) | see *Rotating the JWT key* below |
| Revoke CI access | delete the `notes-ci-command` line from `/home/deploy/.ssh/authorized_keys` and the `DEPLOY_SSH_KEY` secret |
| Promote or demote an admin | `ssh deploy@$NOTES_HOST '/srv/notes/deploy/production/dc run --rm --no-deps migrate python -m notes_api.manage promote-admin <email>'` (or `demote-admin`) |
| Stop paying | Cloud Console → server → **Delete** (and the backups/snapshots); remove the `NOTES_HOST` variable so deploys and uptime checks skip |

**Rotating the JWT key.** The secret file is mode 444, so remove it before writing the new
one. Refresh tokens are database rows, not JWTs: delete them too, or every session survives
the rotation. Then redeploy the release that is running, so the new replicas read the new
key while the old ones keep serving (no downtime, unlike `--force-recreate`):

```bash
ssh "deploy@$NOTES_HOST" 'cd /srv/notes \
    && rm -f .secrets/notes_jwt_secret \
    && openssl rand -base64 48 | tr -d "\n" > .secrets/notes_jwt_secret \
    && chmod 444 .secrets/notes_jwt_secret \
    && deploy/production/dc exec -T db psql -U notes -c "DELETE FROM refresh_tokens" \
    && SKIP_PULL=1 deploy/production/rollout.sh "$(sed -n "s/^TAG=//p" state/release.env)"'
```

Access tokens signed with the old key stop working as soon as the old replicas are gone;
everyone logs in again. The Redis password rotates the same way (`notes_redis_password`),
except that Redis itself must restart: `deploy/production/dc up -d --force-recreate redis`
first (queued jobs survive in the append-only file), then the same `rollout.sh` line.

## 16. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| deploy job skipped | `NOTES_HOST` variable missing | step 9, then `gh workflow run notes-api.yml --ref main` |
| `Permission denied (publickey)` in the deploy job | wrong key in `DEPLOY_SSH_KEY` or bootstrap ran without the CI key | compare `ssh-keygen -yf ~/.ssh/notes_deploy` with `/home/deploy/.ssh/authorized_keys` |
| `Host key verification failed` | `DEPLOY_KNOWN_HOSTS` empty or for another name | rerun the `ssh-keyscan` line of step 9 |
| `required variable … is missing a value` | `/srv/notes/.env` incomplete | step 8 |
| browser shows a certificate error | ports 80/443 blocked, or DNS wrong | firewall (step 4), `getent hosts $NOTES_HOST`, `dc logs proxy \| jq -c 'select(.logger \| test("tls"))'` |
| `too many certificates` in the proxy log | Let's Encrypt rate limit on the shared sslip.io domain | wait (Caddy retries, and falls back to ZeroSSL), or use a [DuckDNS](https://www.duckdns.org) name or your own domain |
| `/health/startup` says `need 00xx` | migrations did not run | `dc run --rm migrate`, read its output |
| new replicas never become healthy | the release crashes at start | the old replicas keep serving; `dc logs api`, fix, push |
| `Too many authentication failures` when you log in | `MaxAuthTries 3` and an SSH agent offering many keys | `ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 deploy@$NOTES_HOST` |
| `notes-ci-command: not allowed: …` in the deploy job | the workflow sent a command the wrapper does not know | compare the job's `ssh notes-prod …` lines with `deploy/production/ci-command`; re-run `bootstrap.sh`'s wrapper step after changing it (`sudo` is not available to `deploy`: use the Hetzner console) |
| rollback says `no known-good release other than …` | no earlier release passed its smoke test | deploy a known-good commit by its SHA (step 14) |
| `/health/startup` says `need 00xx` after a rollback | not expected: a newer schema is fine | check that `alembic_version` holds a revision the newer release created (`dc exec db psql -U notes -c 'SELECT * FROM alembic_version'`) |
