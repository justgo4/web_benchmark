# Snapshot gateway benchmark

The request hot path performs no StarRocks query.

- 100 metric endpoints.
- Immutable snapshot is rebuilt once per second.
- JSON is serialized during refresh, not per request.
- Every request verifies HMAC-SHA256, timestamp window, and a per-user ACL bitset.
- Four users have disjoint 25-metric permissions.
- /api/{metric} serves one metric.
- /snapshot serves all metrics visible to the authenticated user in one response.
- One server process/worker on a 4-vCPU GitHub runner; load generator shares the same runner.

## Individual metric endpoint

| Stack | Max stable tested QPS | 1k p99 | 5k p99 | 10k p99 | 20k p99 |
|---|---:|---:|---:|---:|---:|
| FastPySGI WSGI | 20,000 | 0.11 ms | 0.19 ms | 0.36 ms | 1.67 ms |
| Granian RSGI + rloop | 20,000 | 0.14 ms | 0.25 ms | 1.43 ms | 4.94 ms |
| Granian RSGI + uvloop | 20,000 | 0.15 ms | 0.25 ms | 1.69 ms | 5.92 ms |
| Granian raw ASGI + uvloop | 20,000 | 0.15 ms | 0.27 ms | 2.32 ms | 5.96 ms |
| Granian RSGI + asyncio | 20,000 | 0.16 ms | 0.35 ms | 2.29 ms | 7.87 ms |
| Sanic raw-bytes | 20,000 | 0.16 ms | 0.44 ms | 1.00 ms | 11.07 ms |

## Batch snapshot endpoint

| Stack | Max stable tested QPS | 100 p99 | 1k p99 | 5k p99 |
|---|---:|---:|---:|---:|
| Granian RSGI + rloop | 5,000 | 0.22 ms | 0.14 ms | 0.23 ms |
| FastPySGI WSGI | 5,000 | 0.34 ms | 0.10 ms | 0.18 ms |
| Granian RSGI + uvloop | 5,000 | 0.27 ms | 0.15 ms | 0.24 ms |
| Granian raw ASGI + uvloop | 5,000 | 0.29 ms | 0.16 ms | 0.28 ms |
| Granian RSGI + asyncio | 5,000 | 0.28 ms | 0.17 ms | 0.30 ms |
| Sanic raw-bytes | 5,000 | 0.25 ms | 0.17 ms | 0.43 ms |

## Interpretation

- This measures the proposed production request path: authentication, authorization, memory lookup, and raw-byte response.
- StarRocks load is controlled by the refresh scheduler, so downstream user count does not multiply StarRocks QPS.
- If the dashboard can use /snapshot, 100 per-metric calls per second become one call per second per user.
