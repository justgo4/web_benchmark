# Benchmark Results

Generated: 2026-09-29T17:00:28.425846+00:00

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
| 1 | FastPySGI WSGI | server ceiling | 0.6 | 3.13 | 75,610 | 65,824–77,832 | 1.54ms | 1.98ms | 3.29ms |
| 2 | Dreaming Electric Sheep | framework | 1.2.1 | 3.13 | 59,323 | 59,138–59,414 | 2.14ms | 2.32ms | 2.70ms |
| 3 | Granian raw RSGI | server ceiling | 2.8.3 | 3.13 | 38,380 | 38,093–38,524 | 3.41ms | 3.97ms | 4.55ms |
| 4 | Uvicorn raw ASGI | server ceiling | 0.54.0 | 3.13 | 35,813 | 34,771–35,865 | 3.16ms | 4.02ms | 6.38ms |
| 5 | Jero + Granian | framework | 0.1.3 | 3.13 | 25,662 | 25,590–25,693 | 5.11ms | 5.68ms | 6.10ms |
| 6 | Sanic | framework | 25.12.1 | 3.13 | 18,169 | 18,043–18,194 | 5.79ms | 11.08ms | 88.62ms |
| 7 | BustAPI | framework | 0.15.0 | 3.13 | 14,581 | 14,564–14,622 | 10.22ms | 27.13ms | 56.02ms |
| 8 | BlackSheep + Granian | framework | 2.6.3 | 3.13 | 13,655 | 13,564–13,879 | 9.37ms | 10.31ms | 10.88ms |
| 9 | Starlette + Granian | framework | 1.7.0 | 3.13 | 12,357 | 12,266–12,487 | 10.64ms | 11.52ms | 11.89ms |
| 10 | Emmett + Granian | framework | 2.8.1 | 3.13 | 11,911 | 11,801–11,978 | 11.01ms | 11.37ms | 11.59ms |
| 11 | aiohttp | framework | 3.14.3 | 3.13 | 11,210 | 10,483–11,624 | 11.90ms | 14.10ms | 14.77ms |
| 12 | Falcon + Granian | framework | 4.3.1 | 3.13 | 10,362 | 10,014–10,473 | 12.27ms | 13.47ms | 14.08ms |
| 13 | Robyn | framework | 0.88.0 | 3.13 | 7,891 | 7,810–8,214 | 14.33ms | 20.47ms | 25.67ms |
| 14 | Litestar + Granian | framework | 2.24.0 | 3.13 | 7,833 | 7,788–7,920 | 16.42ms | 17.67ms | 18.03ms |
| 15 | FastAPI + Granian | framework | 0.141.1 | 3.13 | 7,260 | 7,175–7,293 | 16.56ms | 22.14ms | 22.94ms |

## Automated observations

- Fastest successful **common-runtime framework** in this run: **Dreaming Electric Sheep** at ~59,323 median RPS.
- Highest raw server ceiling measured: **FastPySGI WSGI** at ~75,610 median RPS.
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
