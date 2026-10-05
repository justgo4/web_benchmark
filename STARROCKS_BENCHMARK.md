# Realistic StarRocks Gateway Benchmark

Complete path:
wrk -> framework/server -> pyreqwest keep-alive -> StarRocks-style NDJSON -> parse -> JSON API response

SQL shape: select id, date from test;

The mock upstream is FastPySGI and returns prebuilt StarRocks-style NDJSON. The configured 5ms/20ms query delay is applied identically inside every gateway handler, so the mock itself does not become the sleeping bottleneck.

## 0ms / 100 rows

| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Sanic | 2,327 | 2,287-2,366 | 52.94ms | 55.56ms | 250.19ms | 0 |
| 2 | Uvicorn raw ASGI | 2,236 | 2,214-2,257 | 56.78ms | 63.10ms | 573.59ms | 0 |
| 3 | Dreaming Electric Sheep | 2,029 | 2,008-2,049 | 61.92ms | 63.62ms | 65.48ms | 0 |
| 4 | Jero + Granian | 2,018 | 2,001-2,036 | 62.58ms | 64.81ms | 66.40ms | 0 |
| 5 | Granian raw RSGI | 1,936 | 1,929-1,944 | 65.61ms | 67.43ms | 69.03ms | 0 |
| 6 | aiohttp | 1,876 | 1,872-1,880 | 67.71ms | 70.46ms | 73.31ms | 0 |
| 7 | FastPySGI | 1,856 | 1,846-1,866 | 50.20ms | 63.81ms | 1.33s | 0 |
| 8 | Litestar + Granian | 1,822 | 1,818-1,826 | 69.65ms | 71.42ms | 73.67ms | 0 |
| 9 | BlackSheep + Granian | 1,815 | 1,810-1,821 | 69.90ms | 71.55ms | 73.93ms | 0 |
| 10 | Emmett + Granian | 1,811 | 1,804-1,818 | 70.08ms | 71.82ms | 73.58ms | 0 |
| 11 | Starlette + Granian | 1,807 | 1,797-1,817 | 69.85ms | 71.76ms | 73.52ms | 0 |
| 12 | Falcon + Granian | 1,737 | 1,724-1,749 | 72.73ms | 74.99ms | 78.73ms | 0 |
| 13 | Robyn | 1,635 | 1,628-1,643 | 74.00ms | 88.30ms | 101.96ms | 0 |
| 14 | BustAPI | 1,498 | 1,486-1,510 | 83.67ms | 90.71ms | 97.74ms | 0 |
| 15 | FastAPI + Granian | 874 | 863-886 | 142.59ms | 146.21ms | 154.03ms | 0 |

Failed/incompatible: TurboAPI (server not ready: process exited with -4)

## 5ms / 100 rows

| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Sanic | 2,308 | 2,292-2,324 | 54.16ms | 57.44ms | 111.14ms | 0 |
| 2 | Uvicorn raw ASGI | 2,209 | 2,191-2,228 | 56.75ms | 60.70ms | 85.33ms | 0 |
| 3 | Jero + Granian | 2,034 | 2,029-2,038 | 62.28ms | 66.56ms | 69.61ms | 0 |
| 4 | Granian raw RSGI | 1,966 | 1,953-1,979 | 64.48ms | 68.42ms | 72.29ms | 0 |
| 5 | aiohttp | 1,934 | 1,910-1,959 | 64.28ms | 68.86ms | 78.47ms | 0 |
| 6 | Emmett + Granian | 1,869 | 1,862-1,875 | 67.61ms | 72.76ms | 76.55ms | 0 |
| 7 | Starlette + Granian | 1,827 | 1,823-1,831 | 69.74ms | 74.00ms | 77.51ms | 0 |
| 8 | Litestar + Granian | 1,826 | 1,824-1,828 | 69.57ms | 74.26ms | 80.87ms | 0 |
| 9 | BlackSheep + Granian | 1,823 | 1,818-1,829 | 69.68ms | 73.48ms | 76.81ms | 0 |
| 10 | Falcon + Granian | 1,737 | 1,731-1,744 | 72.67ms | 79.50ms | 85.33ms | 0 |
| 11 | Robyn | 1,714 | 1,703-1,724 | 71.82ms | 86.53ms | 106.79ms | 0 |
| 12 | BustAPI | 1,475 | 1,464-1,485 | 84.40ms | 93.35ms | 124.85ms | 0 |
| 13 | FastAPI + Granian | 862 | 854-870 | 145.08ms | 152.07ms | 226.72ms | 0 |
| 14 | Dreaming Electric Sheep | 156 | 144-168 | 728.45ms | 730.75ms | 869.84ms | 0 |
| 15 | FastPySGI | 154 | 143-166 | 154.59ms | 201.69ms | 1.18s | 0 |

Failed/incompatible: TurboAPI (server not ready: process exited with -4)

## 20ms / 100 rows

| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Jero + Granian | 1,985 | 1,978-1,991 | 64.72ms | 68.85ms | 78.32ms | 0 |
| 2 | Granian raw RSGI | 1,886 | 1,878-1,894 | 68.09ms | 71.25ms | 73.50ms | 0 |
| 3 | Emmett + Granian | 1,801 | 1,789-1,813 | 71.37ms | 75.68ms | 83.57ms | 0 |
| 4 | aiohttp | 1,800 | 1,759-1,841 | 71.60ms | 78.50ms | 80.36ms | 0 |
| 5 | Sanic | 1,794 | 1,785-1,803 | 68.76ms | 71.18ms | 73.12ms | 0 |
| 6 | BlackSheep + Granian | 1,784 | 1,771-1,796 | 71.66ms | 75.89ms | 80.61ms | 0 |
| 7 | Litestar + Granian | 1,750 | 1,742-1,758 | 73.55ms | 78.45ms | 83.46ms | 0 |
| 8 | Uvicorn raw ASGI | 1,729 | 1,727-1,731 | 72.86ms | 75.66ms | 79.06ms | 0 |
| 9 | Starlette + Granian | 1,726 | 1,715-1,738 | 73.84ms | 78.21ms | 87.93ms | 0 |
| 10 | Robyn | 1,705 | 1,697-1,714 | 76.86ms | 87.52ms | 108.18ms | 0 |
| 11 | Falcon + Granian | 1,705 | 1,685-1,725 | 76.19ms | 81.61ms | 94.04ms | 0 |
| 12 | BustAPI | 1,431 | 1,419-1,443 | 88.31ms | 100.57ms | 114.52ms | 0 |
| 13 | FastAPI + Granian | 864 | 859-870 | 143.31ms | 157.59ms | 176.44ms | 0 |
| 14 | Dreaming Electric Sheep | 28 | 16-40 | 1.33s | 1.87s | 2.00s | 0 |
| 15 | FastPySGI | 28 | 16-40 | 166.91ms | 209.55ms | 376.95ms | 0 |

Failed/incompatible: TurboAPI (server not ready: process exited with -4)

## 5ms / 1000 rows

| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Jero + Granian | 370 | 358-382 | 330.02ms | 334.66ms | 602.02ms | 0 |
| 2 | Sanic | 362 | 356-368 | 231.27ms | 299.03ms | 1.40s | 0 |
| 3 | Litestar + Granian | 356 | 345-368 | 339.33ms | 346.07ms | 388.31ms | 0 |
| 4 | Uvicorn raw ASGI | 331 | 318-344 | 232.81ms | 307.95ms | 1.45s | 0 |
| 5 | Granian raw RSGI | 327 | 316-337 | 367.17ms | 380.10ms | 703.16ms | 0 |
| 6 | aiohttp | 322 | 310-333 | 372.19ms | 384.84ms | 437.64ms | 0 |
| 7 | Emmett + Granian | 319 | 309-330 | 377.58ms | 391.86ms | 692.63ms | 0 |
| 8 | Starlette + Granian | 319 | 308-330 | 377.68ms | 385.52ms | 432.04ms | 0 |
| 9 | BlackSheep + Granian | 318 | 307-330 | 377.08ms | 383.74ms | 435.49ms | 0 |
| 10 | Falcon + Granian | 314 | 299-328 | 387.70ms | 407.28ms | 704.54ms | 0 |
| 11 | Robyn | 310 | 309-310 | 380.63ms | 444.54ms | 608.79ms | 0 |
| 12 | BustAPI | 294 | 281-308 | 404.15ms | 436.28ms | 502.63ms | 0 |
| 13 | FastAPI + Granian | 112 | 101-123 | 969.36ms | 979.54ms | 1.19s | 0 |
| 14 | Dreaming Electric Sheep | 109 | 97-121 | 998.33ms | 1.68s | 1.96s | 0 |
| 15 | FastPySGI | 102 | 90-114 | 179.15ms | 238.69ms | 1.37s | 0 |

Failed/incompatible: TurboAPI (server not ready: process exited with -4)

## Overall

Overall score = geometric mean of median RPS across all four scenarios. Only stacks completing all scenarios are ranked.

| Rank | Stack | Geometric-mean RPS |
|---:|---|---:|
| 1 | Sanic | 1,367 |
| 2 | Jero + Granian | 1,318 |
| 3 | Uvicorn raw ASGI | 1,297 |
| 4 | Granian raw RSGI | 1,238 |
| 5 | aiohttp | 1,204 |
| 6 | Litestar + Granian | 1,200 |
| 7 | Emmett + Granian | 1,181 |
| 8 | BlackSheep + Granian | 1,171 |
| 9 | Starlette + Granian | 1,161 |
| 10 | Falcon + Granian | 1,127 |
| 11 | Robyn | 1,103 |
| 12 | BustAPI | 982 |
| 13 | FastAPI + Granian | 520 |
| 14 | Dreaming Electric Sheep | 176 |
| 15 | FastPySGI | 169 |

Overall winner in this run: Sanic.

Final production verification should still run on the actual 16C/64G API host against the real StarRocks 4.1.1 FE, because network latency, FE scheduling, Query Cache, result size and CPU model can change the ordering.

## Failures

| Stack | Scenario | Error |
|---|---|---|
| TurboAPI | 0ms / 100 rows | server not ready: process exited with -4 |
| TurboAPI | 5ms / 100 rows | server not ready: process exited with -4 |
| TurboAPI | 20ms / 100 rows | server not ready: process exited with -4 |
| TurboAPI | 5ms / 1000 rows | server not ready: process exited with -4 |
