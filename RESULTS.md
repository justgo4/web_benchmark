# Benchmark Results

Generated: 2026-09-29T17:12:46.982961+00:00

## Method

- Runner CPU: `AMD EPYC 9V74 80-Core Processor`; logical CPUs visible: `4`.
- Main runtime: CPython `3.13`. TurboAPI uses its required `3.14t` runtime and is not strictly runtime-identical.
- Endpoint: `GET /json` returning exactly `{"message":"hello","value":123}`.
- One process / one configured worker where the server exposes that control.
- Load: `wrk`, 2 threads, 128 keep-alive connections, 6s × 3 measured rounds after warmup.
- Ranking uses median requests/second across measured rounds.
- Native servers may internally use different thread/runtime designs; the table measures the stack as users actually deploy it, not a normalized CPU-cycle cost.

## Results

| Rank | Stack | Type | Version | Python | Median RPS | Range | p50 | p90 | p99 |
|---:|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | TurboAPI (Python 3.14t) | framework-special-runtime | 1.0.35 | 3.14t | 115,813 | 112,328–123,325 | 111.00us | 223.00us | 825.00us |
| 2 | FastPySGI WSGI | server ceiling | 0.6 | 3.13 | 100,587 | 97,905–102,381 | 1.21ms | 1.40ms | 1.85ms |
| 3 | Dreaming Electric Sheep | framework | 1.2.1 | 3.13 | 82,473 | 82,088–82,920 | 1.53ms | 1.72ms | 2.26ms |
| 4 | Granian raw RSGI | server ceiling | 2.8.3 | 3.13 | 55,842 | 54,451–55,995 | 2.34ms | 2.71ms | 3.00ms |
| 5 | Uvicorn raw ASGI | server ceiling | 0.54.0 | 3.13 | 48,792 | 48,307–49,952 | 2.49ms | 2.80ms | 4.87ms |
| 6 | Jero + Granian | framework | 0.1.3 | 3.13 | 39,886 | 39,616–40,094 | 3.28ms | 3.62ms | 3.90ms |
| 7 | Sanic | framework | 25.12.1 | 3.13 | 32,229 | 32,125–32,303 | 3.77ms | 4.19ms | 17.44ms |
| 8 | BustAPI | framework | 0.15.0 | 3.13 | 26,179 | 25,641–26,358 | 4.93ms | 14.38ms | 28.13ms |
| 9 | BlackSheep + Granian | framework | 2.6.3 | 3.13 | 23,681 | 23,642–23,962 | 5.41ms | 5.84ms | 6.14ms |
| 10 | Starlette + Granian | framework | 1.7.0 | 3.13 | 22,212 | 22,008–22,924 | 5.83ms | 6.31ms | 6.66ms |
| 11 | aiohttp | framework | 3.14.3 | 3.13 | 22,207 | 21,300–25,926 | 6.15ms | 6.38ms | 7.71ms |
| 12 | Emmett + Granian | framework | 2.8.1 | 3.13 | 21,049 | 20,997–21,441 | 6.14ms | 6.39ms | 6.62ms |
| 13 | Falcon + Granian | framework | 4.3.1 | 3.13 | 16,510 | 16,492–16,723 | 7.78ms | 8.24ms | 8.68ms |
| 14 | Robyn | framework | 0.88.0 | 3.13 | 14,033 | 13,724–14,432 | 7.95ms | 11.68ms | 15.24ms |
| 15 | Litestar + Granian | framework | 2.24.0 | 3.13 | 13,805 | 13,767–15,455 | 9.64ms | 10.03ms | 10.22ms |
| 16 | FastAPI + Granian | framework | 0.141.1 | 3.13 | 11,731 | 11,720–11,811 | 11.24ms | 13.51ms | 13.93ms |

## Automated observations

- Fastest successful **common-runtime framework** in this run: **Dreaming Electric Sheep** at ~82,473 median RPS.
- Special-runtime result: **TurboAPI (Python 3.14t)** reached ~115,813 median RPS; compare cautiously because it uses free-threaded Python 3.14t and a different native threading model.
- Highest raw server ceiling measured: **FastPySGI WSGI** at ~100,587 median RPS.
- For the StarRocks gateway decision, this JSON hot-path test is a ceiling test. A proxy workload with connection pooling and an upstream HTTP hop is more representative and should be considered before migrating frameworks.

## Reproduction

Run the GitHub Actions workflow `Python HTTP benchmark`, or locally on Linux:

```bash
sudo apt-get install -y wrk
python -m pip install uv
python benchmark.py
```

Raw `wrk` outputs and server/install logs are retained under `results/logs/` in the workflow artifact; `results/latest.json` contains the machine-readable summary.
