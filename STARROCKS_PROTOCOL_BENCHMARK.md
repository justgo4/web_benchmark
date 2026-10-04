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
| MySQL protocol + PyMySQL | 25.533 ms | 30.145 ms | 3,917 | 2,590 |
| HTTP SQL API + pyreqwest | 29.902 ms | 36.498 ms | 3,344 | 3,386 |
| Arrow Flight SQL ADBC | 38.101 ms | 40.035 ms | 2,625 | 2,000 |

Winner: **MySQL protocol + PyMySQL**.

## Cached aggregate — converted to JSON-ready body (100 rows)

| Protocol | Median | p95 | Rows/s | Median bytes |
|---|---:|---:|---:|---:|
| MySQL protocol + PyMySQL | 28.028 ms | 30.395 ms | 3,568 | 3,691 |
| HTTP SQL API + pyreqwest | 30.650 ms | 31.724 ms | 3,263 | 3,691 |
| Arrow Flight SQL ADBC | 48.992 ms | 50.109 ms | 2,041 | 3,691 |

Winner: **MySQL protocol + PyMySQL**.

## Raw fetch by result size

Query Cache is enabled but plain row retrieval is not a Query Cache application scenario; these rows measure protocol/serialization transfer.

| Rows | HTTP ms | PyMySQL ms | Flight ms | Winner |
|---:|---:|---:|---:|---|
| 10 | 23.058 | 20.751 | 43.122 | MySQL protocol + PyMySQL |
| 100 | 21.288 | 18.778 | 34.664 | MySQL protocol + PyMySQL |
| 1,000 | 23.236 | 20.530 | 21.917 | MySQL protocol + PyMySQL |
| 10,000 | 65.338 | 64.822 | 32.751 | Arrow Flight SQL ADBC |
| 100,000 | 265.658 | 406.514 | 37.579 | Arrow Flight SQL ADBC |
| 500,000 | 1226.816 | 1948.351 | 97.164 | Arrow Flight SQL ADBC |

## JSON-ready by result size

This includes conversion into JSON-compatible Python objects and JSON serialization, approximating a web API response path.

| Rows | HTTP ms | PyMySQL ms | Flight ms | Winner |
|---:|---:|---:|---:|---|
| 10 | 21.969 | 19.369 | 33.622 | MySQL protocol + PyMySQL |
| 100 | 21.567 | 18.209 | 42.409 | MySQL protocol + PyMySQL |
| 1,000 | 26.301 | 20.965 | 29.429 | MySQL protocol + PyMySQL |
| 10,000 | 97.540 | 68.175 | 46.707 | Arrow Flight SQL ADBC |
| 100,000 | 553.031 | 514.264 | 136.299 | Arrow Flight SQL ADBC |
| 500,000 | 2868.665 | 2552.160 | 621.490 | Arrow Flight SQL ADBC |

## Interpretation

- Use the cached aggregate section for the real-time dashboard/API case.
- Use raw-fetch results to decide when Arrow Flight becomes worthwhile for large result sets or exports.
- GitHub-hosted runner results are comparative only; they are not an absolute production QPS estimate for the 16-core deployment.
