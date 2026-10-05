# Realtime Gateway

Single-host realtime dashboard gateway for StarRocks 4.1.1.

## Your 100-table case

You do **not** need to combine 100 result tables into one StarRocks query.

Each dashboard metric has its own entry in metrics.json:

```json
{
  "id": "orders_now",
  "sql": "SELECT ... FROM dashboard.table_for_orders ...",
  "refresh_ms": 1000,
  "max_stale_ms": 5000
}
```

For 100 source tables, configure 100 entries. They may have completely different schemas and SQL because each metric response is stored independently as JSON.

The gateway schedules the reads in the background with bounded concurrency and spreads them across their refresh windows. HTTP requests never query StarRocks.

```
100 independent StarRocks result tables
        |
        | bounded async reads
        | each metric has its own cadence
        v
per-metric last-good state
        |
        | rebuild pre-serialized snapshots
        v
Granian RSGI + uvloop
        |
        +-- /api/{metric_id}
        +-- /snapshot
```

If all 100 metrics refresh every second, StarRocks sees about 100 SQL queries per second, independent of user count. With mixed cadences:

```
StarRocks average QPS ~= sum(1000 / refresh_ms)
```

Example: 60 metrics at 1s + 20 at 5s + 20 at 60s is about 64.3 SQL QPS.

This is very different from the naive design:

```
100 metrics * number of users * 1 request/s
```

## Why not UNION ALL all 100 tables

It is technically possible to build one giant UNION ALL or a view when schemas can be normalized, but it is not the recommended design here:

- all 100 sources become coupled to the slowest subquery;
- realtime and offline metrics lose independent refresh cadences;
- one problematic table can hurt the whole snapshot;
- the FE must build and schedule one large plan;
- unrelated metrics refresh even when their source changes only every minute/hour.

A dedicated summary table maintained by upstream jobs could reduce reads to one query per second, but that requires changing all upstream pipelines. The gateway scheduler gives almost the same downstream isolation without changing those pipelines.

## Files

```
config.json   -> StarRocks hosts, pool, scheduler and timeouts
metrics.json  -> metric id, SELECT SQL, refresh cadence
users.json    -> API key/secret mapping and metric ACL
```

Copy the examples:

```bash
cp realtime_gateway/config.example.json realtime_gateway/config.json
cp realtime_gateway/metrics.example.json realtime_gateway/metrics.json
cp realtime_gateway/users.example.json realtime_gateway/users.json
```

Then replace the sample metric definitions with your 100 real tables.

## Install

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r realtime_gateway/requirements.txt
```

Create a dedicated read-only StarRocks account. Do not use root or the CDC writer account.

Set secrets outside Git:

```bash
export STARROCKS_PASSWORD='...'
export SCREEN_A_SECRET='long-random-secret-a'
export SCREEN_B_SECRET='long-random-secret-b'
export OPS_ALL_SECRET='long-random-secret-c'
```

Start one worker:

```bash
granian \
  --interface rsgi \
  --loop uvloop \
  --workers 1 \
  --runtime-threads 1 \
  --host 127.0.0.1 \
  --port 8000 \
  --log-level warning \
  realtime_gateway.app:app
```

One worker is intentional: every process would otherwise own its own StarRocks refresh scheduler. The authenticated in-memory request path already benchmarked far above the target load on one worker.

## Metric scheduling

Each metrics.json entry supports:

- `id`: public metric/API id.
- `sql`: read-only SELECT against that metric's final StarRocks table/view.
- `refresh_ms`: how often the gateway reads that table.
- `max_stale_ms`: when readiness considers that metric stale.
- `max_rows`: hard safety bound for one metric result; defaults to `default_max_rows`.

The gateway fetches at most `max_rows + 1` rows and rejects the refresh if the configured result is unexpectedly large, retaining the previous last-good value.

The scheduler uses `refresh_concurrency` as a hard cap. With the default 12, no more than 12 metric reads are active at once.

Pools are created with lazy connections. A FE that is down when the gateway starts does not prevent startup; that FE is retried naturally on later pool acquisition, while other FE hosts continue serving refresh queries.

After startup, future reads are phase-shifted across each refresh interval so 100 one-second metrics are not intentionally fired at the same millisecond.

A refresh failure affects only that metric. Other metrics continue updating, and the failing metric retains its own last-good result.

## API responses

`GET /api/orders_now` returns one metric:

```json
{
  "code": 0,
  "metric": "orders_now",
  "updated_ms": 1791234567890,
  "data": [
    {"order_count": 1234, "updated_at": "2026-10-06 00:00:00"}
  ]
}
```

`GET /snapshot` returns every metric that user is allowed to see:

```json
{
  "code": 0,
  "snapshot_ms": 1791234567900,
  "data": {
    "orders_now": {
      "updated_ms": 1791234567890,
      "data": [{"order_count": 1234}]
    },
    "monthly_sales": {
      "updated_ms": 1791234500000,
      "data": [{"month": "2026-09", "sales": 999999}]
    }
  }
}
```

Notice that each metric has its own updated_ms. That is required when realtime and offline outputs have different freshness.

Prefer /snapshot for the dashboard. One dashboard user then makes one HTTP request per second instead of 100.

## Authentication and ACL

Each user has a different API key and secret.

Required headers:

```
X-Api-Key: screen-a
X-Timestamp: <unix-seconds>
X-Signature: <hex-hmac-sha256>
```

Canonical signed text:

```
GET
<path>
<timestamp>
```

The users file stores only environment variable names for secrets. ACLs are compiled into an integer bitset at startup.

The hot path is:

```
key lookup
-> HMAC-SHA256
-> ACL bit test
-> pre-serialized memory bytes
-> response
```

No Redis, SQL, filesystem read, or JSON serialization occurs on normal dashboard requests.

## Health

- `GET /healthz`: process is alive.
- `GET /readyz`: shows uninitialized, stale, failed and inflight metrics.

A source-table failure does not delete the metric's last-good value.

## Query Cache

Keep StarRocks Query Cache enabled as you requested. The example SELECTs carry a SET_VAR hint. For result tables that are already fully materialized and require almost no aggregation, Query Cache may contribute little; the main protection comes from fixed background refresh QPS and the in-memory final-result snapshot.

## Production starting values

For 100 small result-table reads:

```
refresh_concurrency = 8 to 16
pool_per_fe         = 2 to 4
workers             = 1
runtime_threads     = 1
```

Start with 12 concurrent refreshes and measure StarRocks FE/BE latency. Increase concurrency only if the one-second metrics cannot finish within their cadence.

## Client example

```bash
export GATEWAY_URL=http://127.0.0.1:8000
export API_KEY=screen-a
export API_SECRET='long-random-secret-a'
python realtime_gateway/client_example.py
```
