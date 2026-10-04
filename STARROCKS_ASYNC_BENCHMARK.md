# StarRocks async client benchmark

- StarRocks: 4.1.1-14b7e3f
- Rows loaded: 1,000,000
- Query Cache variable: ['enable_query_cache', 'true']
- Main pool size: 160
- Flight thread/connection pool: 64
- 20 fixed dashboard endpoint queries, each returning 10 aggregate rows.
- Primary load: 4,000 QPS = 20 endpoints × 200 QPS.
- Every request includes Query Cache + pipeline_dop=1 SET_VAR hints.
- Latency is JSON-ready latency and includes pool/semaphore wait.

## Query Cache verification

- **query_cache_before**: lookup=0, hit=0, hit_ratio=0.0, usage=0
- **query_cache_after_warm**: lookup=160, hit=0, hit_ratio=0.0, usage=62880
- **query_cache_after**: lookup=91291, hit=91131, hit_ratio=0.9982473628287564, usage=62880

## 100 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| aiomysql | native asyncio | 100.00% | 100 | 19.25 ms | 30.74 ms | 43.52 ms | 44.26 ms | 0 |
| pyreqwest async HTTP | native asyncio | 100.00% | 100 | 39.52 ms | 67.86 ms | 79.20 ms | 79.51 ms | 0 |
| asyncmy | native asyncio | 100.00% | 99 | 70.11 ms | 160.15 ms | 186.19 ms | 187.79 ms | 0 |

## 250 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| aiomysql | native asyncio | 99.47% | 206 | 656.14 ms | 1488.12 ms | 1787.96 ms | 1788.42 ms | 4 |
| pyreqwest async HTTP | native asyncio | 99.60% | 197 | 754.28 ms | 1610.54 ms | 1813.66 ms | 1814.30 ms | 3 |
| asyncmy | native asyncio | 55.87% | 88 | 1153.40 ms | 1937.41 ms | 1980.17 ms | 1980.50 ms | 331 |

## 500 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| aiomysql | native asyncio | 42.67% | 94 | 1344.00 ms | 1954.78 ms | 1989.38 ms | 3733.34 ms | 860 |
| asyncmy | native asyncio | 38.33% | 77 | 1552.49 ms | 1943.55 ms | 1984.83 ms | 4613.08 ms | 925 |
| pyreqwest async HTTP | native asyncio | 34.27% | 74 | 1117.93 ms | 1836.56 ms | 1959.26 ms | 1994.98 ms | 986 |

## 750 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| asyncmy | native asyncio | 39.73% | 94 | 1502.51 ms | 1871.03 ms | 1952.11 ms | 6676.58 ms | 1356 |
| aiomysql | native asyncio | 29.02% | 66 | 1458.89 ms | 1926.25 ms | 1952.81 ms | 7307.66 ms | 1597 |
| pyreqwest async HTTP | native asyncio | 16.22% | 37 | 1337.57 ms | 1912.92 ms | 1982.91 ms | 2450.03 ms | 1885 |

## 1,000 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|

## 1,500 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|

## 2,000 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|

## 4,000 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|

## Compatibility/startup failures

- **mysql.connector.aio 26.7.0**: TypeError('cannot unpack non-iterable NoneType object')

## Decision rule

- Prefer native asyncio clients for the Sanic hot path; Arrow Flight ADBC is shown separately because the Python ADBC API is blocking and needs a thread executor.
- This GitHub-hosted runner is a comparative 4-vCPU environment; production sizing still needs a run on the 16-core API host against the real 3-FE/4-BE cluster.
