# StarRocks 4.1.1 protocol benchmark

- StarRocks reported version: `4.1.1-14b7e3f`
- Rows loaded: 1,000,000
- Query Cache session variable: `('enable_query_cache', 'true')`
- Query Cache hint on every query: `SET_VAR(enable_query_cache=true, pipeline_dop=1)`
- Arrow Flight proxy: StarRocks default (enabled).
- HTTP client: pyreqwest persistent Rust/reqwest connection pool.
- Native rounds: 5; JSON-ready rounds: 3.

## Query Cache verification

- **after_invalidate**: lookup=0, hit=0, hit_ratio=0.0, usage=0
- **after_warm**: lookup=8, hit=0, hit_ratio=0.0, usage=17544
- **after_benchmark**: lookup=248, hit=240, hit_ratio=0.967741935483871, usage=17544

## Cached aggregate — native result form (100 rows)

| Protocol | Median | p95 | Rows/s | Median bytes |
|---|---:|---:|---:|---:|
| MySQL protocol + PyMySQL | 25.378 ms | 28.233 ms | 3,940 | 2,590 |
| HTTP SQL API + pyreqwest | 29.828 ms | 37.107 ms | 3,353 | 3,386 |
| Arrow Flight SQL ADBC | 38.468 ms | 46.903 ms | 2,600 | 2,000 |

Winner: **MySQL protocol + PyMySQL**.

## Cached aggregate — converted to JSON-ready body (100 rows)

| Protocol | Median | p95 | Rows/s | Median bytes |
|---|---:|---:|---:|---:|
| MySQL protocol + PyMySQL | 26.576 ms | 26.774 ms | 3,763 | 3,691 |
| HTTP SQL API + pyreqwest | 26.787 ms | 27.129 ms | 3,733 | 3,691 |
| Arrow Flight SQL ADBC | 39.248 ms | 55.537 ms | 2,548 | 3,691 |

Winner: **MySQL protocol + PyMySQL**.

## Raw fetch by result size

Query Cache is enabled but plain row retrieval is not a Query Cache application scenario; these rows measure protocol/serialization transfer.

| Rows | HTTP ms | PyMySQL ms | Flight ms | Winner |
|---:|---:|---:|---:|---|
| 10 | 22.094 | 20.244 | 37.767 | MySQL protocol + PyMySQL |
| 100 | 21.379 | 19.695 | 31.963 | MySQL protocol + PyMySQL |
| 1,000 | 24.796 | 22.127 | 28.859 | MySQL protocol + PyMySQL |
| 10,000 | 58.112 | 77.146 | 36.410 | Arrow Flight SQL ADBC |
| 100,000 | 274.514 | 395.073 | 39.939 | Arrow Flight SQL ADBC |
| 500,000 | 1179.334 | 2006.345 | 86.542 | Arrow Flight SQL ADBC |

## JSON-ready by result size

This includes conversion into JSON-compatible Python objects and JSON serialization, approximating a web API response path.

| Rows | HTTP ms | PyMySQL ms | Flight ms | Winner |
|---:|---:|---:|---:|---|
| 10 | 27.209 | 20.684 | 35.837 | MySQL protocol + PyMySQL |
| 100 | 20.971 | 18.289 | 28.824 | MySQL protocol + PyMySQL |
| 1,000 | 28.116 | 26.613 | 33.147 | MySQL protocol + PyMySQL |
| 10,000 | 67.740 | 62.154 | 33.123 | Arrow Flight SQL ADBC |
| 100,000 | 568.189 | 515.309 | 138.463 | Arrow Flight SQL ADBC |
| 500,000 | 2796.542 | 2539.415 | 604.854 | Arrow Flight SQL ADBC |

## Interpretation

- Use the cached aggregate section for the real-time dashboard/API case.
- Use raw-fetch results to decide when Arrow Flight becomes worthwhile for large result sets or exports.
- GitHub-hosted runner results are comparative only; they are not an absolute production QPS estimate for the 16-core deployment.
