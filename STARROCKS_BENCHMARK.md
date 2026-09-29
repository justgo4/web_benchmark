# Realistic StarRocks Gateway Benchmark

Complete path:
wrk -> framework/server -> pyreqwest keep-alive -> StarRocks-style NDJSON -> parse -> JSON API response

SQL shape: select id, date from test;

The mock upstream is FastPySGI and returns prebuilt StarRocks-style NDJSON. The configured 5ms/20ms query delay is applied identically inside every gateway handler, so the mock itself does not become the sleeping bottleneck.

## 0ms / 100 rows

| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Sanic | 2,248 | 2,210-2,287 | 56.59ms | 60.96ms | 125.85ms | 0 |
| 2 | Uvicorn raw ASGI | 2,225 | 2,206-2,244 | 56.28ms | 64.07ms | 204.50ms | 0 |
| 3 | Dreaming Electric Sheep | 2,045 | 2,039-2,051 | 61.89ms | 63.75ms | 64.24ms | 0 |
| 4 | Jero + Granian | 2,024 | 2,005-2,042 | 62.97ms | 64.96ms | 73.86ms | 0 |
| 5 | Granian raw RSGI | 1,940 | 1,926-1,953 | 65.22ms | 67.34ms | 69.02ms | 0 |
| 6 | aiohttp | 1,902 | 1,870-1,934 | 65.24ms | 69.45ms | 73.25ms | 0 |
| 7 | FastPySGI | 1,877 | 1,875-1,878 | 49.42ms | 63.61ms | 1.35s | 0 |
| 8 | BlackSheep + Granian | 1,825 | 1,824-1,825 | 69.74ms | 71.19ms | 73.44ms | 0 |
| 9 | Litestar + Granian | 1,814 | 1,805-1,823 | 69.93ms | 71.64ms | 77.50ms | 0 |
| 10 | Starlette + Granian | 1,809 | 1,796-1,822 | 69.66ms | 71.57ms | 74.09ms | 0 |
| 11 | Emmett + Granian | 1,808 | 1,778-1,838 | 70.82ms | 72.78ms | 92.49ms | 0 |
| 12 | Falcon + Granian | 1,735 | 1,730-1,739 | 73.25ms | 75.96ms | 78.62ms | 0 |
| 13 | Robyn | 1,660 | 1,660-1,661 | 73.08ms | 87.45ms | 104.33ms | 0 |
| 14 | BustAPI | 1,503 | 1,492-1,514 | 83.60ms | 90.79ms | 99.68ms | 0 |
| 15 | FastAPI + Granian | 874 | 866-882 | 143.49ms | 146.85ms | 151.90ms | 0 |

Failed/incompatible: TurboAPI (server not ready: process exited with -4)

## 5ms / 100 rows

| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Sanic | 2,422 | 2,386-2,458 | 49.90ms | 58.76ms | 71.13ms | 0 |
| 2 | Uvicorn raw ASGI | 2,375 | 2,337-2,413 | 52.20ms | 63.91ms | 162.24ms | 0 |
| 3 | Jero + Granian | 2,042 | 2,028-2,057 | 61.61ms | 66.49ms | 69.65ms | 0 |
| 4 | Granian raw RSGI | 1,971 | 1,943-1,999 | 63.70ms | 67.86ms | 71.62ms | 0 |
| 5 | aiohttp | 1,929 | 1,919-1,938 | 67.08ms | 69.31ms | 74.72ms | 0 |
| 6 | BlackSheep + Granian | 1,863 | 1,860-1,866 | 67.99ms | 72.59ms | 78.76ms | 0 |
| 7 | Litestar + Granian | 1,862 | 1,859-1,866 | 68.28ms | 73.08ms | 78.24ms | 0 |
| 8 | Emmett + Granian | 1,857 | 1,851-1,862 | 67.54ms | 72.56ms | 83.10ms | 0 |
| 9 | Starlette + Granian | 1,811 | 1,810-1,813 | 69.79ms | 75.29ms | 90.67ms | 0 |
| 10 | Falcon + Granian | 1,750 | 1,736-1,763 | 71.56ms | 77.37ms | 92.11ms | 0 |
| 11 | Robyn | 1,708 | 1,703-1,714 | 71.36ms | 85.19ms | 102.55ms | 0 |
| 12 | BustAPI | 1,499 | 1,494-1,503 | 84.26ms | 92.15ms | 101.16ms | 0 |
| 13 | FastAPI + Granian | 882 | 868-896 | 140.88ms | 147.31ms | 162.25ms | 0 |
| 14 | Dreaming Electric Sheep | 156 | 144-169 | 727.83ms | 1.12s | 1.41s | 0 |
| 15 | FastPySGI | 155 | 143-167 | 148.73ms | 201.23ms | 1.20s | 0 |

Failed/incompatible: TurboAPI (server not ready: process exited with -4)

## 20ms / 100 rows

| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Jero + Granian | 2,017 | 2,016-2,018 | 63.78ms | 67.35ms | 70.70ms | 0 |
| 2 | Granian raw RSGI | 1,921 | 1,916-1,926 | 66.77ms | 71.45ms | 73.79ms | 0 |
| 3 | Sanic | 1,882 | 1,864-1,900 | 65.85ms | 77.76ms | 94.63ms | 0 |
| 4 | aiohttp | 1,860 | 1,831-1,889 | 67.97ms | 75.94ms | 112.50ms | 0 |
| 5 | Uvicorn raw ASGI | 1,851 | 1,849-1,852 | 68.65ms | 77.26ms | 96.95ms | 0 |
| 6 | Litestar + Granian | 1,822 | 1,801-1,842 | 71.61ms | 76.35ms | 85.17ms | 0 |
| 7 | BlackSheep + Granian | 1,817 | 1,811-1,824 | 69.93ms | 74.90ms | 84.75ms | 0 |
| 8 | Emmett + Granian | 1,811 | 1,807-1,814 | 71.18ms | 76.11ms | 84.40ms | 0 |
| 9 | Starlette + Granian | 1,770 | 1,748-1,791 | 71.46ms | 75.92ms | 84.79ms | 0 |
| 10 | Robyn | 1,758 | 1,750-1,766 | 76.73ms | 85.50ms | 98.04ms | 0 |
| 11 | Falcon + Granian | 1,744 | 1,729-1,759 | 73.08ms | 77.55ms | 86.80ms | 0 |
| 12 | BustAPI | 1,457 | 1,454-1,459 | 86.82ms | 98.30ms | 113.65ms | 0 |
| 13 | FastAPI + Granian | 890 | 873-906 | 139.54ms | 147.90ms | 155.73ms | 0 |
| 14 | FastPySGI | 28 | 16-40 | 270.02ms | 498.98ms | 1.60s | 0 |
| 15 | Dreaming Electric Sheep | 28 | 16-40 | 0.00us | 0.00us | 0.00us | 0 |

Failed/incompatible: TurboAPI (server not ready: process exited with -4)

## 5ms / 1000 rows

| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Jero + Granian | 367 | 357-377 | 332.06ms | 334.71ms | 376.03ms | 0 |
| 2 | Sanic | 359 | 355-363 | 228.07ms | 352.02ms | 1.57s | 0 |
| 3 | Litestar + Granian | 358 | 347-369 | 337.73ms | 343.72ms | 389.91ms | 0 |
| 4 | Uvicorn raw ASGI | 335 | 323-347 | 243.98ms | 351.57ms | 1.44s | 0 |
| 5 | Granian raw RSGI | 331 | 319-342 | 365.28ms | 370.20ms | 421.04ms | 0 |
| 6 | aiohttp | 321 | 308-334 | 372.29ms | 378.10ms | 431.79ms | 0 |
| 7 | Emmett + Granian | 320 | 309-332 | 376.43ms | 382.04ms | 436.03ms | 0 |
| 8 | Starlette + Granian | 320 | 307-332 | 376.61ms | 400.33ms | 695.30ms | 0 |
| 9 | BlackSheep + Granian | 319 | 308-330 | 376.02ms | 391.36ms | 433.18ms | 0 |
| 10 | Falcon + Granian | 316 | 303-329 | 378.95ms | 385.69ms | 437.12ms | 0 |
| 11 | Robyn | 307 | 303-311 | 387.63ms | 453.23ms | 642.29ms | 0 |
| 12 | BustAPI | 299 | 289-308 | 407.43ms | 466.72ms | 738.42ms | 0 |
| 13 | FastAPI + Granian | 111 | 99-124 | 967.46ms | 986.86ms | 1.21s | 0 |
| 14 | Dreaming Electric Sheep | 109 | 97-120 | 996.25ms | 1.01s | 1.20s | 0 |
| 15 | FastPySGI | 104 | 92-116 | 177.28ms | 240.03ms | 1.35s | 0 |

Failed/incompatible: TurboAPI (server not ready: process exited with -4)

## Overall

Overall score = geometric mean of median RPS across all four scenarios. Only stacks completing all scenarios are ranked.

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

Overall winner in this run: Sanic.

Final production verification should still run on the actual 16C/64G API host against the real StarRocks 4.1.1 FE, because network latency, FE scheduling, Query Cache, result size and CPU model can change the ordering.

## Failures

| Stack | Scenario | Error |
|---|---|---|
| TurboAPI | 0ms / 100 rows | server not ready: process exited with -4 |
| TurboAPI | 5ms / 100 rows | server not ready: process exited with -4 |
| TurboAPI | 20ms / 100 rows | server not ready: process exited with -4 |
| TurboAPI | 5ms / 1000 rows | server not ready: process exited with -4 |
