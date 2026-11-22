# Notes API — load-test report

This report checks the production setup against its targets with [Locust](https://docs.locust.io/).
It has two result sections:

- **Local rehearsal**: the production stack (`compose.yaml` + `compose.prod.yaml`, Caddy with
  TLS, two API replicas, PostgreSQL, Redis, the worker, Prometheus) running on a development
  machine. The Phase 6 Project notebook fills it in on every run.
- **Live**: the deployed server at `https://<NOTES_HOST>`, filled in after the first deploy
  ([DEPLOY.md](DEPLOY.md), step 13).

## Scenario

`load/locustfile.py` simulates users who mostly read and sometimes write:

| Task | Request | Weight | What it exercises |
| --- | --- | ---: | --- |
| `list_notes` | `GET /api/v1/notes?limit=20` | 5 | authentication, offset pagination, a database read |
| `read_note` | `GET /api/v1/notes/{id}` | 3 | the Redis cache and ETags (notes this user created) |
| `create_note` | `POST /api/v1/notes` | 1 | a transaction, the outbox row, cache invalidation |
| `feed` | `GET /api/v1/notes/feed?limit=10` | 1 | keyset pagination |

- **Think time:** each user waits 50–200 ms between requests (`between(0.05, 0.2)`), so 50 users
  offer roughly 250–400 requests per second.
- **Accounts:** a pool of throw-away accounts, `load-<run>-<n>@example.com`, one for every two
  simulated users (25 for 50 users; `NOTES_LOAD_ACCOUNTS` overrides it). The API limits each
  user to 120 writes a minute, and one shared account would measure that limit instead of
  the server; raising the limit for the test would measure a server that is not the
  production one. Each account writes about 40 times a minute, within its budget.
- **Setup and clean-up:** `load/accounts.py` registers the pool before the users start, at
  the pace the registration limit allows (5 a minute per client address: about five
  minutes for 25 accounts; Locust's run time starts after that), then logs every account in.
  When the test stops, each account deletes itself (`DELETE /api/v1/users/me`; its notes,
  tokens and events cascade). The same file runs unchanged locally and against the live
  server.
- **Run (live):** 50 users, spawn rate 10 per second, 2 minutes, from a machine close to the
  server's region. Network round trips count in the client-side numbers; the server-side
  95th percentile from Prometheus does not include them.
- **Run (local rehearsal):** 50 users, spawn rate 10 per second, 15 seconds (shorter, so the
  notebook stays fast).

## Targets

| Target | Threshold | Why |
| --- | --- | --- |
| p95 latency | < 200 ms | the latency goal of Unit 6.8; also the `NotesApiSlowP95` alert |
| failed requests | < 1% | the `NotesApiHighErrorRate` alert threshold |
| throughput | ≥ 100 requests/s | headroom for a small team on a 2 vCPU server |

The locustfile enforces the first two: `locust` exits with code 1 when either is missed.

## How to run it

Local rehearsal: run the *Rehearsal* step of the Phase 6 Project notebook.

Live, from `projects/notes_api/` (an SSH tunnel to Prometheus gives the server-side p95):

```bash
ssh -N -L 9090:127.0.0.1:9090 deploy@$NOTES_HOST &      # Prometheus on 127.0.0.1:9090
uv run locust -f load/locustfile.py --host "https://$NOTES_HOST" \
    --headless -u 50 -r 10 -t 2m --only-summary --csv load/results/live
uv run python load/report.py --stats load/results/live_stats.csv --section live \
    --host "https://$NOTES_HOST" --users 50 --duration 2m --window 120 \
    --prometheus http://127.0.0.1:9090
kill %1                                                  # close the tunnel
```

`load/results/` is git-ignored. The run deletes its own accounts and their notes at the
end. Only if it was killed first, [DEPLOY.md](DEPLOY.md) (step 13) shows how to delete what
is left. Keep a run under 10 minutes after the setup: access tokens last 15 minutes.

## Results — local rehearsal

<!-- results:local:start -->
Run at 2026-11-22 14:46 UTC against `https://localhost:58443`: 50 users, spawn rate 10/s, 15s.

| Endpoint | Requests | Failures | req/s | p50 ms | p95 ms | p99 ms | max ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GET `/api/v1/notes` | 2491 | 0 | 165.9 | 8 | 15 | 24 | 36 |
| POST `/api/v1/notes` | 500 | 0 | 33.3 | 10 | 28 | 37 | 148 |
| GET `/api/v1/notes/feed` | 479 | 0 | 31.9 | 7 | 14 | 21 | 29 |
| GET `/api/v1/notes/{id}` | 1291 | 0 | 86.0 | 6 | 13 | 19 | 31 |
| **All requests** | 4761 | 0 | 317.1 | 8 | 16 | 28 | 148 |

| Target | Measured | Verdict |
| --- | ---: | --- |
| p95 latency (client side) < 200 ms | 16 ms | **PASS** |
| failed requests < 1% | 0.00% | **PASS** |
| throughput >= 100 req/s | 317 req/s | **PASS** |
| p95 latency (server side, Prometheus) < 200 ms | 19 ms | **PASS** |
<!-- results:local:end -->

## Results — live

<!-- results:live:start -->
_Waiting for the first deploy (see DEPLOY.md, step 13)._
<!-- results:live:end -->

## Reading the results

- **Client-side vs server-side p95.** Locust measures the full round trip: DNS, TLS, the
  internet path and Caddy. Prometheus measures only the time inside the API. A large gap
  means the network dominates, so test from closer to the server. A high server-side p95
  points at the application or the database.
- **Where the time goes.** Use the Grafana dashboard during the run: the latency panel
  shows p50/p95/p99, the in-progress panel shows queueing, and the request-rate panel
  shows which route is busiest.
- **Capacity.** Little's law: requests in flight = throughput × latency. At 300 requests/s
  and 20 ms, that is 6 requests in flight across 4 Uvicorn processes, so there is plenty of
  headroom. When p95 climbs while throughput stays flat, the server is saturated.
- **The local rehearsal runs on a developer machine.** Its absolute numbers are not a
  prediction for the server. It proves the stack, the scenario and the report work end to end.
