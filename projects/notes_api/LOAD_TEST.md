# Notes API — load-test report

This report checks the production setup against its targets with [Locust](https://docs.locust.io/).
It has two result sections:

- **Local rehearsal**: the production stack (`compose.yaml` + `compose.prod.yaml`, Caddy with
  TLS, two API replicas, PostgreSQL, Redis, the worker, Prometheus) running on a development
  machine. The Phase 6 Project notebook fills it in on every run.
- **Live**: the deployed server at `https://<NOTES_HOST>`, filled in after the first deploy
  ([DEPLOY.md](DEPLOY.md), step 13).

## Scenario

`load/locustfile.py` simulates users of one account who mostly read and sometimes write:

| Task | Request | Weight | What it exercises |
| --- | --- | ---: | --- |
| `list_notes` | `GET /api/v1/notes?limit=20` | 5 | authentication, offset pagination, a database read |
| `read_note` | `GET /api/v1/notes/{id}` | 3 | the Redis cache and ETags (notes this user created) |
| `create_note` | `POST /api/v1/notes` | 1 | a transaction, the outbox row, cache invalidation |
| `feed` | `GET /api/v1/notes/feed?limit=10` | 1 | keyset pagination |

- **Think time:** each user waits 50–200 ms between requests (`between(0.05, 0.2)`), so 50 users
  offer roughly 250–400 requests per second.
- **Setup:** one account (`load-<random>@example.com`) is registered and logged in once
  before the users start. Registration and login are rate-limited per address, so users
  share one token.
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

`load/results/` is git-ignored. The run creates notes owned by the `load-…@example.com`
account. [DEPLOY.md](DEPLOY.md) shows how to delete them.

## Results — local rehearsal

<!-- results:local:start -->
Run at 2026-11-21 07:20 UTC against `https://localhost:58443`: 50 users, spawn rate 10/s, 15s.

| Endpoint | Requests | Failures | req/s | p50 ms | p95 ms | p99 ms | max ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GET `/api/v1/notes` | 2202 | 0 | 157.2 | 8 | 15 | 27 | 67 |
| POST `/api/v1/notes` | 449 | 0 | 32.0 | 9 | 17 | 28 | 70 |
| GET `/api/v1/notes/feed` | 470 | 0 | 33.5 | 7 | 15 | 28 | 61 |
| GET `/api/v1/notes/{id}` | 1222 | 0 | 87.2 | 6 | 13 | 21 | 75 |
| **All requests** | 4343 | 0 | 310.0 | 7 | 15 | 25 | 75 |

| Target | Measured | Verdict |
| --- | ---: | --- |
| p95 latency (client side) < 200 ms | 15 ms | **PASS** |
| failed requests < 1% | 0.00% | **PASS** |
| throughput >= 100 req/s | 310 req/s | **PASS** |
| p95 latency (server side, Prometheus) < 200 ms | 18 ms | **PASS** |
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
