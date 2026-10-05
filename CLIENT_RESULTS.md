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
| 1 | pyreqwest | 0.14.0 | 10,032 | 9,971–10,118 | 12.495ms | 15.517ms | 16.255ms | 0 |
| 2 | pyqwest | 0.11.0 | 8,740 | 8,733–8,794 | 14.214ms | 21.491ms | 27.930ms | 0 |
| 3 | aiohttp | 3.14.3 | 6,982 | 6,551–7,420 | 22.473ms | 23.460ms | 25.303ms | 0 |
| 4 | httpx | 0.28.1 | 256 | 255–258 | 520.471ms | 1265.936ms | 1919.480ms | 0 |

## Automated observation

- Fastest client in this run: **pyreqwest** at ~10,032 median RPS.
- For the actual StarRocks API gateway, upstream SQL latency will usually dominate this microbenchmark; the main value here is identifying avoidable HTTP-client overhead and connection-pool behavior.
