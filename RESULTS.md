# Benchmark Results

Generated: 2026-09-29T16:51:57.157600+00:00

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
| 1 | FastPySGI WSGI | server ceiling | 0.6 | 3.13 | 75,464 | 71,596–77,366 | 1.58ms | 1.89ms | 2.12ms |
| 2 | Granian raw RSGI | server ceiling | 2.8.3 | 3.13 | 39,088 | 38,592–39,244 | 3.38ms | 3.93ms | 4.42ms |
| 3 | Uvicorn raw ASGI | server ceiling | 0.54.0 | 3.13 | 37,001 | 33,692–37,069 | 3.11ms | 4.28ms | 24.19ms |
| 4 | Jero + Granian | framework | 0.1.3 | 3.13 | 25,894 | 25,838–25,960 | 4.99ms | 5.53ms | 6.10ms |
| 5 | Sanic | framework | 25.12.1 | 3.13 | 18,112 | 17,412–18,623 | 6.45ms | 10.81ms | 137.59ms |
| 6 | BustAPI | framework | 0.15.0 | 3.13 | 15,534 | 15,180–15,555 | 8.93ms | 25.61ms | 51.08ms |
| 7 | BlackSheep + Granian | framework | 2.6.3 | 3.13 | 14,009 | 13,956–14,030 | 9.12ms | 10.06ms | 12.09ms |
| 8 | Starlette + Granian | framework | 1.7.0 | 3.13 | 12,714 | 12,634–12,906 | 10.20ms | 11.13ms | 11.64ms |
| 9 | Emmett + Granian | framework | 2.8.1 | 3.13 | 12,135 | 12,104–12,210 | 10.63ms | 10.93ms | 11.19ms |
| 10 | aiohttp | framework | 3.14.3 | 3.13 | 11,840 | 11,416–12,920 | 11.19ms | 12.48ms | 13.82ms |
| 11 | Falcon + Granian | framework | 4.3.1 | 3.13 | 10,697 | 10,649–10,889 | 11.87ms | 13.21ms | 14.88ms |
| 12 | Litestar + Granian | framework | 2.24.0 | 3.13 | 8,355 | 8,125–8,400 | 15.57ms | 16.56ms | 17.36ms |
| 13 | FastAPI + Granian | framework | 0.141.1 | 3.13 | 7,030 | 7,006–7,045 | 18.51ms | 21.49ms | 23.10ms |

## Automated observations

- Fastest successful **common-runtime framework** in this run: **Jero + Granian** at ~25,894 median RPS.
- Highest raw server ceiling measured: **FastPySGI WSGI** at ~75,464 median RPS.
- For the StarRocks gateway decision, this JSON hot-path test is a ceiling test. A proxy workload with connection pooling and an upstream HTTP hop is more representative and should be considered before migrating frameworks.

## Failed / incompatible cases

| Stack | Error |
|---|---|
| Dreaming Electric Sheep | server exited with 1 |
| Robyn | server exited with 1 |
| TurboAPI (Python 3.14t) | server exited with -4 |

## Reproduction

Run the GitHub Actions workflow `Python HTTP benchmark`, or locally on Linux:

```bash
sudo apt-get install -y wrk
python -m pip install uv
python benchmark.py
```

Raw `wrk` outputs and server/install logs are retained under `results/logs/` in the workflow artifact; `results/latest.json` contains the machine-readable summary.
