# Recommendation for the 20-endpoint StarRocks dashboard API

Updated: 2026-09-30

## Exact workload

The benchmark now models the stated production requirement directly:

- StarRocks 4.1.1 backend.
- Global StarRocks Query Cache assumed enabled.
- 20 API endpoints.
- Up to 200 requests/second per endpoint.
- Worst-case aggregate API load: 4,000 requests/second.
- Every API request performs one StarRocks-style HTTP SQL request.
- Small dashboard result set: 10 rows.
- No API local cache and no singleflight in the ranking.
- Four application workers on a four-vCPU GitHub runner.
- Repeated per-endpoint SQL with simulated cached StarRocks latency of 2ms and 5ms for the final steady comparison.
- A separate full run also tested 10ms latency and a synchronized 4,000-request burst scheduled into 200ms.

The detailed data is in `DASHBOARD_BENCHMARK.md` and `results/dashboard_latest.json`.

## Steady 4,000 QPS result

### 2ms StarRocks latency

| Stack | Throughput | Success | p95 | p99 | Target |
|---|---:|---:|---:|---:|---|
| Jero + Granian | 3,995 | 100% | 5.03ms | 6.12ms | PASS |
| Granian raw RSGI | 3,996 | 100% | 5.22ms | 6.71ms | PASS |
| Litestar + Granian | 3,994 | 100% | 6.44ms | 7.64ms | PASS |
| Sanic | 3,996 | 100% | 4.81ms | 13.57ms | PASS |
| FastAPI + Granian | 3,989 | 100% | 23.97ms | 31.22ms | PASS |
| Flask + Gunicorn gthread | 2,831 | 100% | 1215.10ms | 1263.24ms | FAIL |

Quart + Granian and BustAPI did not complete this exact 4,000-QPS test successfully.

### 5ms StarRocks latency

| Stack | Throughput | Success | p95 | p99 | Target |
|---|---:|---:|---:|---:|---|
| Jero + Granian | 3,991 | 100% | 8.19ms | 9.35ms | PASS |
| Granian raw RSGI | 3,993 | 100% | 9.35ms | 12.10ms | PASS |
| Litestar + Granian | 3,992 | 100% | 10.53ms | 12.22ms | PASS |
| Sanic | 3,992 | 100% | 8.13ms | 30.50ms | PASS |
| FastAPI + Granian | 3,979 | 100% | 41.71ms | 59.39ms | PASS |
| Flask + Gunicorn gthread | 1,825 | 100% | 1388.79ms | 2938.29ms | FAIL |

## Burst result

The earlier full run additionally scheduled roughly 4,000 requests into a 200ms window.

Sanic completed the burst benchmark while still sustaining the 4,000-QPS steady target:

- 2ms upstream: steady ~3,999 QPS, p99 ~4.22ms; burst p99 ~149.61ms.
- 5ms upstream: steady ~3,997 QPS, p99 ~7.25ms; burst p99 ~160.16ms.
- 10ms upstream: steady ~3,994 QPS, p99 ~12.46ms; burst p99 ~133.68ms.

The Granian/Jero/Litestar/Quart burst attempts did not drain within the benchmark's 20-second guard in that deliberately extreme burst configuration. This does not mean they cannot serve production traffic; it means Sanic demonstrated substantially better behavior in the synchronized-burst test used here.

## Production recommendation

### Primary choice: Sanic + pyreqwest

For this specific workload, Sanic is the production recommendation.

Reasons:

1. It sustains the required 4,000 aggregate QPS on only four CI vCPUs at 2ms, 5ms and 10ms simulated StarRocks latency.
2. It returned 100% successful responses in those steady tests.
3. It is the only tested production-oriented framework that also completed the deliberately harsh synchronized burst test.
4. Its route/decorator style is close to Flask, so the 20 endpoint implementation remains simple.
5. Sanic has existed since 2016 and has a large established project/community, unlike Jero which was created in June 2026 and is still extremely small.
6. The separate outbound-client benchmark favors pyreqwest, so the recommended hot path is Sanic + a long-lived pyreqwest connection pool.

### Second choice: Litestar + Granian + pyreqwest

Choose this when typed routing, dependency injection and a more structured API framework are more important than the simplest possible Flask-like style.

It sustained the 4,000-QPS steady target with excellent p99 latency, but it did not complete the extreme 200ms burst test under the current guard.

### Performance-specialist choice: Granian raw RSGI + pyreqwest

This has very low framework overhead and excellent steady performance. It is attractive because there are only 20 fixed endpoints, but it requires writing more gateway plumbing manually and is less Flask-like.

### Do not choose Jero for production yet

Jero + Granian produced the best steady-state p99 in this benchmark, but the Jero repository was only created in June 2026 and is currently a very small project. Its current maturity does not justify choosing it over Sanic for a customer-facing production API merely to save a few milliseconds at p99.

### Do not keep Flask for this target

Flask + Gunicorn gthread did not sustain 4,000 QPS on the same four-vCPU test and accumulated roughly 1-3 seconds of p99 latency.

## Suggested deployment shape

```
Cloud LB / Nginx
        |
   Sanic API
   4 workers initially
        |
 long-lived pyreqwest pool
        |
 FE load balancing / multiple FE addresses
        |
 StarRocks 4.1.1
 Query Cache enabled
```

Because the API host also runs an FE, start with four Sanic workers rather than consuming all 16 CPU cores. The four-vCPU CI test already sustained the stated 4,000-QPS workload. Increase worker count only after measuring the real host, leaving CPU headroom for FE work.

If two API replicas are deployed on different hosts, four workers per API instance gives both capacity headroom and API-layer HA.

## Optional request coalescing

The benchmark deliberately disables singleflight.

If the 200 calls/second to one endpoint are the same endpoint + same parameters, singleflight can merge requests that overlap in time without introducing a TTL or stale data. It can therefore reduce actual StarRocks query fan-out even though StarRocks Query Cache is already enabled.

This is an additional protection, not a requirement for the framework to reach the measured 4,000-QPS target.
