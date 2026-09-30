# Dashboard 20-endpoint / 4000-QPS benchmark

Workload modeled from the target deployment:

- 20 API endpoints.
- 200 requests/second per endpoint.
- 4,000 aggregate requests/second.
- Every API request performs one StarRocks-style HTTP SQL call.
- Small 10-row dashboard result.
- No local result cache and no singleflight.
- Repeated per-endpoint SQL approximates a hot Query Cache workload.
- 4 application workers on a 4-vCPU GitHub runner.
- Primary test: 4,000 QPS for 8 seconds, repeated twice.
- Headroom tests: 6,000 and 8,000 QPS.

## Simulated hot StarRocks latency: 2ms

| Rank | Stack | 4k target | Throughput | Success | p95 | p99 | Max stable tested rate |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Sanic | PASS | 3,999 | 100.000% | 4.61ms | 5.42ms | 6,000 QPS |
| 2 | Jero + Granian | PASS | 3,999 | 100.000% | 5.11ms | 6.24ms | 6,000 QPS |
| 3 | Granian raw RSGI | PASS | 3,999 | 100.000% | 5.38ms | 6.83ms | 6,000 QPS |
| 4 | Litestar + Granian | PASS | 3,998 | 100.000% | 6.64ms | 8.14ms | 6,000 QPS |
| 5 | FastAPI + Granian | PASS | 3,993 | 100.000% | 28.01ms | 38.94ms | 4,000 QPS |
| 6 | Flask + Gunicorn gthread | FAIL | 1,886 | 100.000% | 5887.49ms | 6979.59ms | 0 QPS |
| 7 | Quart + Granian | FAIL | 749 | 87.023% | 30000.69ms | 30001.05ms | 0 QPS |

Failed/incompatible: BustAPI (startup/readiness: TimeoutError('timed out'))

## Simulated hot StarRocks latency: 5ms

| Rank | Stack | 4k target | Throughput | Success | p95 | p99 | Max stable tested rate |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Sanic | PASS | 3,997 | 100.000% | 7.78ms | 9.86ms | 6,000 QPS |
| 2 | Jero + Granian | PASS | 3,997 | 100.000% | 8.33ms | 9.97ms | 6,000 QPS |
| 3 | Granian raw RSGI | PASS | 3,997 | 100.000% | 8.51ms | 10.26ms | 6,000 QPS |
| 4 | Litestar + Granian | PASS | 3,997 | 100.000% | 10.08ms | 11.85ms | 6,000 QPS |
| 5 | FastAPI + Granian | PASS | 3,992 | 100.000% | 38.10ms | 48.09ms | 4,000 QPS |
| 6 | Flask + Gunicorn gthread | FAIL | 1,341 | 99.391% | 8299.23ms | 10369.52ms | 0 QPS |
| 7 | Quart + Granian | FAIL | 627 | 82.233% | 30000.76ms | 30001.08ms | 0 QPS |

Failed/incompatible: BustAPI (startup/readiness: TimeoutError('timed out'))

## Simulated hot StarRocks latency: 10ms

| Rank | Stack | 4k target | Throughput | Success | p95 | p99 | Max stable tested rate |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | Sanic | PASS | 3,995 | 100.000% | 12.69ms | 13.83ms | 6,000 QPS |
| 2 | Granian raw RSGI | PASS | 3,995 | 100.000% | 13.69ms | 15.90ms | 6,000 QPS |
| 3 | Jero + Granian | PASS | 3,995 | 100.000% | 14.57ms | 16.54ms | 6,000 QPS |
| 4 | Litestar + Granian | PASS | 3,994 | 100.000% | 16.40ms | 18.72ms | 4,000 QPS |
| 5 | Flask + Gunicorn gthread | FAIL | 1,760 | 100.000% | 8792.50ms | 9446.39ms | 0 QPS |
| 6 | FastAPI + Granian | FAIL | 2,396 | 98.631% | 204.25ms | 15068.55ms | 0 QPS |
| 7 | Quart + Granian | FAIL | 722 | 86.364% | 30000.71ms | 30001.06ms | 0 QPS |

Failed/incompatible: BustAPI (startup/readiness: TimeoutError('timed out'))

## Overall

Ranking priority: first sustain the required 4,000 QPS in all latency scenarios, then maximize tested headroom, then minimize p99.

| Rank | Stack | 4k scenarios passed | Minimum tested headroom | Mean p95 | Mean p99 |
|---:|---|---:|---:|---:|---:|
| 1 | Sanic | 3/3 | 6,000 QPS | 8.36ms | 9.70ms |
| 2 | Jero + Granian | 3/3 | 6,000 QPS | 9.34ms | 10.92ms |
| 3 | Granian raw RSGI | 3/3 | 6,000 QPS | 9.19ms | 11.00ms |
| 4 | Litestar + Granian | 3/3 | 4,000 QPS | 11.04ms | 12.90ms |
| 5 | FastAPI + Granian | 2/3 | 0 QPS | 90.12ms | 5051.86ms |
| 6 | Flask + Gunicorn gthread | 0/3 | 0 QPS | 7659.74ms | 8931.83ms |
| 7 | Quart + Granian | 0/3 | 0 QPS | 30000.72ms | 30001.06ms |

Measured winner on this CI workload: **Sanic**.

Use this result to choose the framework. Absolute production capacity must still be verified on the actual 16-core API host against the real StarRocks 4.1.1 FE/LB.
