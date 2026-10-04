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
- **query_cache_after**: lookup=61768, hit=61608, hit_ratio=0.9974096619608859, usage=62880

## 2,000 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| aiomysql | native asyncio | 39.08% | 255 | 1163.45 ms | 1893.05 ms | 1981.30 ms | 7749.51 ms | 3655 |
| asyncmy | native asyncio | 34.78% | 224 | 1153.16 ms | 1841.78 ms | 1964.86 ms | 7903.97 ms | 3913 |
| Arrow Flight ADBC via threadpool | threadpool adapter | 17.13% | 119 | 492.03 ms | 1027.74 ms | 1599.63 ms | 7088.26 ms | 4972 |
| pyreqwest async HTTP | native asyncio | 3.65% | 22 | 1397.16 ms | 1964.40 ms | 1991.38 ms | 1999.33 ms | 5781 |

## 4,000 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|

## 6,000 offered QPS

| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |
|---|---|---:|---:|---:|---:|---:|---:|---:|

## Compatibility/startup failures

- **mysql.connector.aio 26.7.0**: TypeError('cannot unpack non-iterable NoneType object')

## Decision rule

- Prefer native asyncio clients for the Sanic hot path; Arrow Flight ADBC is shown separately because the Python ADBC API is blocking and needs a thread executor.
- This GitHub-hosted runner is a comparative 4-vCPU environment; production sizing still needs a run on the 16-core API host against the real 3-FE/4-BE cluster.
