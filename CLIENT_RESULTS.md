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
| 1 | pyreqwest | 0.13.0 | 9,662 | 9,634–9,751 | 13.170ms | 15.925ms | 16.382ms | 0 |
| 2 | pyqwest | 0.11.0 | 8,754 | 8,722–8,816 | 13.408ms | 20.892ms | 27.163ms | 0 |
| 3 | aiohttp | 3.14.3 | 7,611 | 6,424–7,941 | 15.338ms | 20.831ms | 22.119ms | 0 |
| 4 | httpx | 0.28.1 | 255 | 255–255 | 478.228ms | 1208.467ms | 3223.360ms | 0 |

## Automated observation

- Fastest client in this run: **pyreqwest** at ~9,662 median RPS.
- For the actual StarRocks API gateway, upstream SQL latency will usually dominate this microbenchmark; the main value here is identifying avoidable HTTP-client overhead and connection-pool behavior.
