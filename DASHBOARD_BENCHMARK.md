# Dashboard workload benchmark

User workload modeled directly:

- 20 API endpoints.
- 200 requests/second per endpoint.
- 4,000 aggregate API requests/second worst case.
- Each API request makes one outbound StarRocks-style HTTP SQL request.
- 10-row small dashboard response.
- No API local cache and no singleflight in the ranking.
- StarRocks Query Cache is approximated by repeated per-endpoint SQL and low upstream latency.
- 4 application workers on a 4-vCPU GitHub runner.
- Burst test schedules 4,000 total requests into a 200ms window to approximate synchronized dashboards.

## Simulated cached StarRocks latency: 2ms

| Rank | Stack | 4k target | Throughput | Success | steady p95 | steady p99 | burst p95 | burst p99 |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Jero + Granian | PASS | 3,995 | 100.000% | 5.03ms | 6.12ms | N/A | N/A |
| 2 | Granian raw RSGI | PASS | 3,996 | 100.000% | 5.22ms | 6.71ms | N/A | N/A |
| 3 | Litestar + Granian | PASS | 3,994 | 100.000% | 6.44ms | 7.64ms | N/A | N/A |
| 4 | Sanic | PASS | 3,996 | 100.000% | 4.81ms | 13.57ms | N/A | N/A |
| 5 | FastAPI + Granian | PASS | 3,989 | 100.000% | 23.97ms | 31.22ms | N/A | N/A |
| 6 | Flask + Gunicorn gthread | FAIL | 2,831 | 100.000% | 1215.10ms | 1263.24ms | N/A | N/A |

Failed: Quart + Granian (TimeoutExpired(['vegeta', 'attack', '-rate=4000/s', '-duration=3s', '-workers=64', '-max-workers=8192', '-targets=/home/runner/work/web_benchmark/web_benchmark/results/targets_steady.txt'], 20)); BustAPI (TimeoutError('timed out'))

## Simulated cached StarRocks latency: 5ms

| Rank | Stack | 4k target | Throughput | Success | steady p95 | steady p99 | burst p95 | burst p99 |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Jero + Granian | PASS | 3,991 | 100.000% | 8.19ms | 9.35ms | N/A | N/A |
| 2 | Granian raw RSGI | PASS | 3,993 | 100.000% | 9.35ms | 12.10ms | N/A | N/A |
| 3 | Litestar + Granian | PASS | 3,992 | 100.000% | 10.53ms | 12.22ms | N/A | N/A |
| 4 | Sanic | PASS | 3,992 | 100.000% | 8.13ms | 30.50ms | N/A | N/A |
| 5 | FastAPI + Granian | PASS | 3,979 | 100.000% | 41.71ms | 59.39ms | N/A | N/A |
| 6 | Flask + Gunicorn gthread | FAIL | 1,825 | 100.000% | 1388.79ms | 2938.29ms | N/A | N/A |

Failed: Quart + Granian (TimeoutExpired(['vegeta', 'attack', '-rate=4000/s', '-duration=3s', '-workers=64', '-max-workers=8192', '-targets=/home/runner/work/web_benchmark/web_benchmark/results/targets_steady.txt'], 20)); BustAPI (TimeoutError('timed out'))

## Overall decision

Primary score: number of StarRocks latency scenarios that sustain at least 3,900 completed requests/s with >=99.9% success. Ties use success rate and lower steady-state p99.

| Rank | Stack | Scenarios passing 4k target | Mean steady p99 |
|---:|---|---:|---:|
| 1 | Jero + Granian | 2/2 | 7.74ms |
| 2 | Granian raw RSGI | 2/2 | 9.41ms |
| 3 | Litestar + Granian | 2/2 | 9.93ms |
| 4 | Sanic | 2/2 | 22.03ms |
| 5 | FastAPI + Granian | 2/2 | 45.30ms |
| 6 | Flask + Gunicorn gthread | 0/2 | 2100.76ms |

Measured winner for this exact 4-vCPU CI workload: **Jero + Granian**.

Production capacity must still be verified on the real 16-core API host against the real StarRocks FE/LB. The CI benchmark is intended to choose the framework, not to predict absolute 16-core capacity.
