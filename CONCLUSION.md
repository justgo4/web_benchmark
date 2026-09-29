# Conclusion for a StarRocks-facing Python API gateway

Benchmark date: 2026-09-29 (GitHub-hosted Ubuntu runners)

This repository contains two complementary benchmarks:

- `RESULTS.md`: inbound HTTP server/framework ceiling test.
- `CLIENT_RESULTS.md`: pooled outbound HTTP/1.1 client test, representative of an API process calling StarRocks HTTP SQL.

## 1. Inbound server/framework result

Latest same-run ranking (4 logical CPUs, AMD EPYC 9V74):

| Stack | Median RPS | Relative to BustAPI |
|---|---:|---:|
| TurboAPI 1.0.35 / Python 3.14t | 115,813 | 4.42x |
| FastPySGI WSGI (raw server ceiling) | 100,587 | 3.84x |
| Dreaming Electric Sheep 1.2.1 | 82,473 | 3.15x |
| Granian raw RSGI 2.8.3 | 55,842 | 2.13x |
| Jero + Granian | 39,886 | 1.52x |
| Sanic | 32,229 | 1.23x |
| BustAPI 0.15.0 | 26,179 | 1.00x |

The remaining tested frameworks are in `RESULTS.md`.

### TurboAPI warning

TurboAPI is the fastest tested framework in the latest run, but it is **not yet the safest production choice** based on these measurements.

An earlier run on an AMD EPYC 7763 GitHub runner installed TurboAPI 1.0.35 successfully, started the Zig server, registered the route, and then exited with signal `-4` (SIGILL) before a valid benchmark could be collected. A later run on AMD EPYC 9V74 succeeded and reached ~115.8k RPS.

That does not prove the exact root cause is the CPU model, but it demonstrates environment-sensitive native-runtime behavior that should be resolved or reproduced before using TurboAPI for a customer-facing production endpoint.

Also note that TurboAPI uses Python 3.14t and a different native/free-threaded runtime, so its number is not a strict CPython-3.13 apples-to-apples comparison.

## 2. Outbound HTTP client result

For the actual StarRocks gateway, this layer matters because each cache miss / singleflight leader will issue an HTTP request to StarRocks.

Same-run HTTP/1.1 keep-alive result:

| Client | Median RPS | Relative to aiohttp |
|---|---:|---:|
| pyreqwest 0.13.0 | 17,620 | 1.15x |
| aiohttp 3.14.3 | 15,354 | 1.00x |
| pyqwest 0.11.0 | 13,552 | 0.88x |
| httpx 0.28.1 | 362 | 0.02x |

All four completed with zero request errors in the measured rounds.

For this workload, **pyreqwest is the first client to test against the real StarRocks HTTP SQL endpoint**, with **aiohttp as the mature fallback/reference**. HTTPX is not attractive for a throughput-sensitive proxy path based on this test.

## 3. Practical decision for the current project

The API service is a thin gateway:

```
client
  -> authentication / tenant checks
  -> validation / rate limit
  -> local short TTL cache + singleflight
  -> pooled HTTP client
  -> StarRocks HTTP SQL API
```

The framework hot path is therefore only part of total latency. Once a StarRocks query takes milliseconds or tens of milliseconds, the relative difference between 25k and 80k "hello JSON" RPS shrinks substantially.

Recommended evaluation order:

1. **Keep BustAPI as the production baseline** until a realistic StarRocks proxy benchmark proves migration is worthwhile.
2. Replace/benchmark the outbound client first: **pyreqwest vs aiohttp** with one long-lived connection pool per API process.
3. If inbound HTTP overhead becomes measurable, benchmark **Granian raw RSGI** for the intentionally thin gateway. It gives a large ceiling increase without requiring Python 3.14t.
4. Evaluate **Dreaming Electric Sheep** if its API/maturity satisfies production requirements; it was the fastest normal CPython-3.13 framework in this run.
5. Treat **TurboAPI** as the performance leader / experimental candidate until the observed SIGILL variability is explained and production compatibility is verified on the actual 16-core cloud host CPU.

## 4. What these numbers do and do not prove

These are controlled microbenchmarks on GitHub-hosted runners. They are useful for comparing framework and client overhead, but they are not capacity numbers for the production 16C/64G server.

GitHub changes runner CPU models between runs; therefore:

- compare frameworks **within the same run**, not absolute RPS across different runs;
- use the production machine for the final capacity benchmark;
- the decisive test should include authentication, query-key construction, singleflight, the chosen HTTP client, NDJSON parsing, and a real StarRocks query.

The raw machine-readable data is in:

- `results/latest.json`
- `results/client_latest.json`

The GitHub Actions workflow can reproduce both suites.
