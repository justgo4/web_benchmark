# Benchmark Results

Generated: 2026-10-05T15:44:02.975636+00:00

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
| 1 | FastPySGI WSGI | server ceiling | 0.6 | 3.13 | 71,980 | 58,687–77,771 | 1.65ms | 2.01ms | 2.25ms |
| 2 | Dreaming Electric Sheep | framework | 1.2.1 | 3.13 | 56,579 | 55,395–57,352 | 2.18ms | 2.63ms | 3.41ms |
| 3 | Granian raw RSGI | server ceiling | 2.8.4 | 3.13 | 37,310 | 36,842–37,365 | 3.49ms | 4.04ms | 4.41ms |
| 4 | Jero + Granian | framework | 0.1.3 | 3.13 | 25,400 | 25,303–25,749 | 5.14ms | 5.74ms | 6.26ms |
| 5 | Uvicorn raw ASGI | server ceiling | 0.54.0 | 3.13 | 19,355 | 19,197–19,962 | 7.05ms | 7.63ms | 119.18ms |
| 6 | BustAPI | framework | 0.15.0 | 3.13 | 14,375 | 14,283–14,397 | 10.27ms | 29.49ms | 57.46ms |
| 7 | BlackSheep + Granian | framework | 2.6.3 | 3.13 | 13,858 | 13,656–14,042 | 9.23ms | 10.38ms | 11.03ms |
| 8 | Starlette + Granian | framework | 1.7.0 | 3.13 | 12,506 | 12,490–12,568 | 10.19ms | 11.39ms | 12.05ms |
| 9 | Emmett + Granian | framework | 2.8.1 | 3.13 | 11,631 | 11,535–11,698 | 11.17ms | 11.61ms | 11.97ms |
| 10 | aiohttp | framework | 3.14.3 | 3.13 | 11,269 | 10,654–11,502 | 10.87ms | 14.32ms | 15.52ms |
| 11 | Sanic | framework | 25.12.1 | 3.13 | 10,483 | 10,406–11,027 | 12.14ms | 14.47ms | 209.07ms |
| 12 | Falcon + Granian | framework | 4.4.0 | 3.13 | 9,817 | 9,680–9,915 | 13.04ms | 14.11ms | 14.68ms |
| 13 | Litestar + Granian | framework | 2.24.0 | 3.13 | 7,869 | 7,670–8,167 | 15.99ms | 17.73ms | 18.29ms |
| 14 | Robyn | framework | 0.88.0 | 3.13 | 7,743 | 7,714–7,936 | 14.70ms | 20.81ms | 26.60ms |
| 15 | FastAPI + Granian | framework | 0.142.2 | 3.13 | 6,058 | 5,865–6,274 | 21.93ms | 24.97ms | 25.58ms |

## Automated observations

- Fastest successful **common-runtime framework** in this run: **Dreaming Electric Sheep** at ~56,579 median RPS.
- Highest raw server ceiling measured: **FastPySGI WSGI** at ~71,980 median RPS.
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
