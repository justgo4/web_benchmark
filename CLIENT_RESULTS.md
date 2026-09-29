# Outbound HTTP Client Benchmark

This benchmark targets the StarRocks-gateway use case: a Python API process making pooled HTTP/1.1 requests to an upstream service.

## Method

- Upstream: local FastPySGI endpoint returning the same small JSON body.
- Concurrency: 128 concurrent async workers.
- Measurement: 3 rounds × 6s after warmup.
- One long-lived client/pool per library; keep-alive enabled.
- Latency sampling is 1 request per worker per 64 completed requests to reduce measurement overhead.
- Because client and upstream share the same GitHub runner, this is a comparative local proxy benchmark, not an absolute network benchmark.

## Results

| Rank | Client | Version | Median RPS | Range | p50 | p90 | p99 | Errors |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | pyreqwest | 0.13.0 | 17,620 | 17,303–17,740 | 6.755ms | 9.553ms | 10.249ms | 0 |
| 2 | aiohttp | 3.14.3 | 15,354 | 15,347–15,467 | 8.032ms | 8.252ms | 9.541ms | 0 |
| 3 | pyqwest | 0.11.0 | 13,552 | 13,388–13,751 | 8.695ms | 13.950ms | 20.555ms | 0 |
| 4 | httpx | 0.28.1 | 362 | 359–363 | 367.303ms | 887.578ms | 1341.703ms | 0 |

## Automated observation

- Fastest client in this run: **pyreqwest** at ~17,620 median RPS.
- For the actual StarRocks API gateway, upstream SQL latency will usually dominate this microbenchmark; the main value here is identifying avoidable HTTP-client overhead and connection-pool behavior.
