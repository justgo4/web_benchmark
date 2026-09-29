# Conclusion for a StarRocks-facing Python API gateway

Benchmark date: 2026-09-30

The repository now contains three layers of measurement:

- `RESULTS.md`: constant-JSON inbound HTTP ceiling.
- `CLIENT_RESULTS.md`: pooled outbound HTTP client benchmark.
- `STARROCKS_BENCHMARK.md`: realistic gateway path using pyreqwest, StarRocks-style NDJSON, parsing and response serialization.

The third benchmark is the most relevant one for framework selection.

## Realistic gateway result

Measured path:

```
wrk
 -> Python HTTP stack
 -> pyreqwest keep-alive
 -> StarRocks-style NDJSON response
 -> NDJSON parsing
 -> API JSON serialization
 -> client
```

SQL shape: `select id, date from test;`.

Runner: AMD EPYC 7763, 4 logical CPUs, 128 concurrent connections.

### Overall, equal weighting across four scenarios

| Rank | Stack | Geometric-mean RPS |
|---:|---|---:|
| 1 | Sanic | 1,385 |
| 2 | Uvicorn raw ASGI | 1,346 |
| 3 | Jero + Granian | 1,323 |
| 4 | Granian raw RSGI | 1,248 |
| 5 | Litestar + Granian | 1,218 |
| 6 | aiohttp | 1,216 |
| 7 | BlackSheep + Granian | 1,185 |
| 8 | Emmett + Granian | 1,181 |
| 9 | Starlette + Granian | 1,167 |
| 10 | Falcon + Granian | 1,137 |
| 11 | Robyn | 1,113 |
| 12 | BustAPI | 995 |
| 13 | FastAPI + Granian | 526 |
| 14 | Dreaming Electric Sheep | 177 |
| 15 | FastPySGI | 171 |

TurboAPI did not complete any realistic scenario on this EPYC 7763 runner because the process exited with SIGILL (-4).

## Scenario winners

| Scenario | Winner | Median RPS | BustAPI | Winner advantage |
|---|---|---:|---:|---:|
| 0ms / 100 rows | Sanic | 2,248 | 1,503 | ~50% |
| 5ms / 100 rows | Sanic | 2,422 | 1,499 | ~62% |
| 20ms / 100 rows | Jero + Granian | 2,017 | 1,457 | ~38% |
| 5ms / 1000 rows | Jero + Granian | 367 | 299 | ~23% |

This changes the conclusion from the constant-JSON benchmark.

## Important findings

### 1. Empty-route RPS is not enough

Dreaming Electric Sheep and FastPySGI looked extremely fast in the constant-response benchmark. Once upstream I/O was introduced, their synchronous path collapsed:

- at 20ms / 100 rows, both were about 28 RPS;
- asynchronous stacks remained around 1,450-2,020 RPS.

For a StarRocks gateway, asynchronous I/O behavior is therefore more important than a spectacular hello-world RPS number.

### 2. BustAPI works, but it was not the fastest realistic gateway

BustAPI completed every scenario with zero non-2xx responses, but ranked 12th by equal-weight geometric mean.

Compared with BustAPI:

- Sanic was roughly 39% higher on the four-scenario geometric-mean score;
- Jero + Granian was roughly 33% higher;
- Granian raw RSGI was roughly 25% higher.

### 3. Workload shape changes the winner

Sanic won the small/fast result scenarios.

Jero + Granian won both:

- 20ms query latency / 100 rows;
- 5ms / 1000-row result.

For a dashboard workload with small result sets and very fast StarRocks queries, Sanic is currently the strongest measured candidate.

For more typical SQL latency or larger result sets, Jero + Granian is currently the strongest measured candidate.

### 4. TurboAPI remains experimental for this deployment decision

TurboAPI previously reached ~115.8k constant-JSON RPS on an EPYC 9V74 runner.

However, it has now failed with SIGILL on EPYC 7763 in both an earlier test and every realistic StarRocks scenario in this run.

Until that CPU/runtime compatibility issue is understood and reproduced on the actual cloud host CPU, it should not be selected for the customer-facing production API solely because of its microbenchmark speed.

## Outbound HTTP client

The separate pooled-client benchmark still favors pyreqwest:

| Client | Median RPS |
|---|---:|
| pyreqwest | 17,620 |
| aiohttp | 15,354 |
| pyqwest | 13,552 |
| httpx | 362 |

For the gateway hot path, pyreqwest remains the first client to validate against the real StarRocks cluster.

## Current engineering recommendation

The most useful production candidates to carry into the final on-host test are:

1. Sanic + pyreqwest
2. Jero + Granian + pyreqwest
3. Granian raw RSGI + pyreqwest
4. BustAPI + pyreqwest as the existing baseline

The final decision should not use GitHub-runner absolute RPS. Run these four stacks on the actual 16C/64G API host against the actual StarRocks 4.1.1 FE/LB, with the real authentication path, SQL templates, NDJSON parsing, singleflight and intended response sizes.

Raw results:

- `results/latest.json`
- `results/client_latest.json`
- `results/starrocks_latest.json`
