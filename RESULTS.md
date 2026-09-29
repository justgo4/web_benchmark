# Benchmark Results

Generated: 2026-09-29T23:38:10.870888+00:00

## Method

- Runner CPU: `AMD EPYC 7763 64-Core Processor`; logical CPUs visible: `4`.
- Main runtime: CPython `3.13`. TurboAPI uses its required `3.14t` runtime and is not strictly runtime-identical.
- Endpoint: `GET /json` returning exactly `{"message":"hello","value":123}`.
- One process / one configured worker where the server exposes that control.
- Load: `wrk`, 2 threads, 128 keep-alive connections, 6s × 3 measured rounds after warmup.
- Ranking uses median requests/second across measured rounds.
- Native servers may internally use different thread/runtime designs; the table measures the stack as users actually deploy it, not a normalized CPU-cycle cost.

## Results

| Rank | Stack | Type | Version | Python | Median RPS | Range | p50 | p90 | p99 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | FastPySGI WSGI | server ceiling | 0.6 | 3.13 | 74,603 | 64,889–80,049 | 1.63ms | 1.92ms | 2.10ms |
| 2 | Dreaming Electric Sheep | framework | 1.2.1 | 3.13 | 59,529 | 59,152–59,683 | 2.12ms | 2.33ms | 2.79ms |
| 3 | Granian raw RSGI | server ceiling | 2.8.3 | 3.13 | 37,256 | 37,250–37,471 | 3.52ms | 4.09ms | 4.56ms |
| 4 | Uvicorn raw ASGI | server ceiling | 0.54.0 | 3.13 | 35,950 | 35,669–36,062 | 3.18ms | 4.02ms | 6.34ms |
| 5 | Jero + Granian | framework | 0.1.3 | 3.13 | 25,471 | 25,105–25,711 | 5.10ms | 5.68ms | 6.58ms |
| 6 | Sanic | framework | 25.12.1 | 3.13 | 18,403 | 18,257–18,628 | 5.64ms | 11.02ms | 134.26ms |
| 7 | BustAPI | framework | 0.15.0 | 3.13 | 14,612 | 14,575–14,637 | 10.20ms | 26.87ms | 52.66ms |
| 8 | BlackSheep + Granian | framework | 2.6.3 | 3.13 | 13,859 | 13,768–13,907 | 9.18ms | 10.38ms | 10.90ms |
| 9 | Starlette + Granian | framework | 1.7.0 | 3.13 | 12,910 | 12,764–13,079 | 9.89ms | 11.44ms | 11.89ms |
| 10 | Emmett + Granian | framework | 2.8.1 | 3.13 | 11,715 | 11,678–11,727 | 11.12ms | 11.45ms | 11.74ms |
| 11 | aiohttp | framework | 3.14.3 | 3.13 | 10,731 | 10,731–10,966 | 11.96ms | 14.16ms | 14.43ms |
| 12 | Falcon + Granian | framework | 4.3.1 | 3.13 | 10,004 | 9,909–10,178 | 12.74ms | 13.80ms | 14.29ms |
| 13 | Robyn | framework | 0.88.0 | 3.13 | 8,302 | 8,000–8,372 | 13.66ms | 20.00ms | 24.83ms |
| 14 | Litestar + Granian | framework | 2.24.0 | 3.13 | 7,940 | 7,895–8,094 | 16.19ms | 17.41ms | 17.87ms |
| 15 | FastAPI + Granian | framework | 0.142.1 | 3.13 | 6,187 | 6,034–6,229 | 20.82ms | 24.49ms | 25.12ms |

## Automated observations

- Fastest successful **common-runtime framework** in this run: **Dreaming Electric Sheep** at ~59,529 median RPS.
- Highest raw server ceiling measured: **FastPySGI WSGI** at ~74,603 median RPS.
- For the StarRocks gateway decision, this JSON hot-path test is a ceiling test. A proxy workload with connection pooling and an upstream HTTP hop is more representative and should be considered before migrating frameworks.

## Failed / incompatible cases

| Stack | Error |
|---|---|
| TurboAPI (Python 3.14t) | server exited with -4 |

## Reproduction

Run the GitHub Actions workflow `Python HTTP benchmark`, or locally on Linux:

```bash
sudo apt-get install -y wrk
python -m pip install uv
python benchmark.py
```

Raw `wrk` outputs and server/install logs are retained under `results/logs/` in the workflow artifact; `results/latest.json` contains the machine-readable summary.
