# Realtime Gateway

Single-host, low-resource API gateway for a real-time dashboard backed by StarRocks 4.1.1.

## Design

The request hot path does not query StarRocks.

```
StarRocks 4.1.1
  -> background refresh every 1 second
  -> immutable in-memory snapshot
  -> pre-serialized JSON bytes
  -> HMAC + ACL
  -> Granian RSGI + uvloop
  -> dashboard
```

The preferred mode is one batch SQL that returns all already-computed metrics. With 100 metrics and many dashboard users, StarRocks query volume remains roughly one refresh query per second instead of 100 queries per user per second.

## Why one worker

Run one Granian worker initially. Every process owns its own refresh loop, so multiple workers would multiply StarRocks refresh traffic. The benchmark in this repository already sustained 20,000 QPS on one worker for the authenticated in-memory request path.

## Install

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r realtime_gateway/requirements.txt

cp realtime_gateway/config.example.json realtime_gateway/config.json
cp realtime_gateway/users.example.json realtime_gateway/users.json
```

Create a dedicated read-only StarRocks account. Do not use root or the CDC writer account.

Keep secrets outside Git:

```bash
export STARROCKS_PASSWORD='...'
export SCREEN_A_SECRET='long-random-secret-a'
export SCREEN_B_SECRET='long-random-secret-b'
export OPS_ALL_SECRET='long-random-secret-c'
```

Start:

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

Put Nginx or another TLS terminator in front if the service is exposed outside a trusted network.

## Recommended StarRocks shape

If possible, materialize the 100 final metrics into one table/view such as:

```
metric_id | value | updated_at
```

Then use one batch query:

```sql
SELECT /*+ SET_VAR(enable_query_cache=true, pipeline_dop=1) */
       metric_id,
       value,
       updated_at
FROM dashboard_metric;
```

The configured `metric_id_column` is removed from each metric payload. All other returned columns are passed through.

Multiple rows per metric are supported. Every metric endpoint returns `data` as a list.

If one batch query is impossible, use `mode=per_metric`, configure `metric_queries`, and use `refresh_concurrency` around 8-16. The HTTP request path remains unchanged.

## Endpoints

- `GET /api/{metric_id}`: one metric.
- `GET /snapshot`: every metric the authenticated user is allowed to view.
- `GET /healthz`: process liveness.
- `GET /readyz`: snapshot freshness and refresh status.

The dashboard should prefer `/snapshot`. One user then performs one request per second rather than 100 requests per second.

## Authentication

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

The signature is HMAC-SHA256. The server uses constant-time comparison. Use HTTPS in production.

The users JSON stores only the name of the environment variable containing the secret; it does not store the secret itself.

## ACL

Metric permissions are compiled once at startup into a Python integer bitset.

The request authorization path is:

```
api-key dict lookup
-> HMAC-SHA256
-> one ACL bit test
-> snapshot dict lookup
-> response_bytes
```

No Redis, SQL query, filesystem read or JSON serialization happens in the normal API request path.

## Refresh and failure behavior

- Default refresh interval is 1 second.
- Refresh cycles never overlap.
- FE hosts are attempted with round-robin failover.
- A failed refresh does not replace the last good snapshot.
- `serve_stale_on_error=true` keeps serving the last good snapshot.
- Every payload includes `updated_ms`, so the screen can see data age.
- `/readyz` returns 503 once the last good snapshot exceeds `max_stale_ms`.

## Production resource target

For the target workload, start with one process, one RSGI runtime thread, 2-4 CPU cores and 1-2 GB RAM. The actual production host can be larger, but adding workers is not the first scaling step because it would duplicate refresh activity.

## Client example

```bash
export GATEWAY_URL=http://127.0.0.1:8000
export API_KEY=screen-a
export API_SECRET='long-random-secret-a'
python realtime_gateway/client_example.py
```
