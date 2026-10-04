#!/usr/bin/env python3
import asyncio
import base64
import concurrent.futures
import importlib.metadata as metadata
import json
import os
import random
import statistics
import time
import urllib.request
from datetime import datetime, timezone

import pymysql

HOST = "127.0.0.1"
MYSQL_PORT = 9030
HTTP_PORT = 8030
BE_HTTP_PORT = 8040
FLIGHT_PORT = 9408
DB = "async_bench"
ROWS = int(os.getenv("SR_ASYNC_ROWS", "1000000"))
POOL_SIZE = int(os.getenv("SR_ASYNC_POOL", "160"))
FLIGHT_POOL = int(os.getenv("SR_ASYNC_FLIGHT_POOL", "64"))
WORKERS = int(os.getenv("SR_ASYNC_WORKERS", "512"))
REQUEST_TIMEOUT = float(os.getenv("SR_ASYNC_TIMEOUT", "2.0"))
DRAIN_LIMIT = float(os.getenv("SR_ASYNC_DRAIN_LIMIT", "5.0"))
LOADS = []
for item in os.getenv("SR_ASYNC_LOADS", "2000:3,4000:5,6000:3").split(","):
    rate, seconds = item.split(":")
    LOADS.append((int(rate), float(seconds)))

QC_HINT = "/*+ SET_VAR(enable_query_cache=true, pipeline_dop=1) */"
HTTP_URL = (
    f"http://{HOST}:{HTTP_PORT}/api/v1/catalogs/"
    f"default_catalog/databases/{DB}/sql"
)


def percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    idx = max(0, min(len(values) - 1, round((pct / 100) * (len(values) - 1))))
    return values[idx]


def package_version(name):
    try:
        return metadata.version(name)
    except Exception:
        return "unknown"


def wait_mysql(timeout=180):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            conn = pymysql.connect(
                host=HOST,
                port=MYSQL_PORT,
                user="root",
                password="",
                autocommit=True,
                connect_timeout=3,
                read_timeout=10,
                write_timeout=10,
            )
            with conn.cursor() as cur:
                cur.execute("SELECT current_version()")
                version = cur.fetchone()[0]
            conn.close()
            return version
        except Exception as exc:
            last = exc
            time.sleep(2)
    raise RuntimeError(f"StarRocks MySQL port not ready: {last!r}")


def wait_backend(timeout=180):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            conn = open_mysql()
            try:
                with conn.cursor() as cur:
                    cur.execute("SHOW BACKENDS")
                    rows = cur.fetchall()
                    columns = [x[0] for x in cur.description]
                items = [dict(zip(columns, row)) for row in rows]
                alive = [x for x in items if str(x.get("Alive", "")).lower() == "true"]
                if alive:
                    return alive
                last = items
            finally:
                conn.close()
        except Exception as exc:
            last = repr(exc)
        time.sleep(2)
    raise RuntimeError(f"StarRocks BE not ready: {last!r}")


def open_mysql(database=None):
    return pymysql.connect(
        host=HOST,
        port=MYSQL_PORT,
        user="root",
        password="",
        database=database,
        autocommit=True,
        connect_timeout=10,
        read_timeout=120,
        write_timeout=120,
        charset="utf8mb4",
    )


def setup_data():
    conn = open_mysql()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {DB} FORCE")
            cur.execute(f"CREATE DATABASE {DB}")
            cur.execute(f"USE {DB}")
            cur.execute(
                """
                CREATE TABLE bench (
                    id BIGINT NOT NULL,
                    endpoint INT NOT NULL,
                    bucket INT NOT NULL,
                    v BIGINT NOT NULL
                )
                DUPLICATE KEY(id)
                DISTRIBUTED BY HASH(id) BUCKETS 8
                PROPERTIES ("replication_num" = "1")
                """
            )
            start = time.perf_counter()
            cur.execute(
                f"""
                INSERT INTO bench
                SELECT
                    generate_series,
                    generate_series % 20,
                    CAST(generate_series / 20 AS BIGINT) % 10,
                    generate_series * 3
                FROM TABLE(generate_series(1, {ROWS}))
                """
            )
            load_s = time.perf_counter() - start
            cur.execute("SELECT COUNT(*) FROM bench")
            loaded = cur.fetchone()[0]
            if loaded != ROWS:
                raise RuntimeError(f"expected {ROWS} rows, got {loaded}")
            cur.execute("SET enable_query_cache = true")
            cur.execute("SHOW VARIABLES LIKE 'enable_query_cache'")
            qc_var = cur.fetchone()
            return load_s, qc_var
    finally:
        conn.close()


def query_cache_stat():
    try:
        with urllib.request.urlopen(
            f"http://{HOST}:{BE_HTTP_PORT}/api/query_cache/stat",
            timeout=5,
        ) as response:
            return json.loads(response.read())
    except Exception as exc:
        return {"error": repr(exc)}


def invalidate_query_cache():
    req = urllib.request.Request(
        f"http://{HOST}:{BE_HTTP_PORT}/api/query_cache/invalidate_all",
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8", "replace")
    except Exception as exc:
        return repr(exc)


def sql_for(endpoint):
    return (
        f"SELECT {QC_HINT} bucket, COUNT(*) AS c, SUM(v) AS s "
        f"FROM bench WHERE endpoint = {endpoint} "
        "GROUP BY bucket ORDER BY bucket"
    )


QUERIES = [sql_for(i) for i in range(20)]


def json_bytes_from_rows(rows):
    return json.dumps(rows, default=str, separators=(",", ":")).encode()


class AsyncmyAdapter:
    name = "asyncmy"
    package = "asyncmy"

    async def start(self):
        import asyncmy
        from asyncmy.cursors import DictCursor

        self.DictCursor = DictCursor
        self.pool = await asyncmy.create_pool(
            host=HOST,
            port=MYSQL_PORT,
            user="root",
            password="",
            db=DB,
            minsize=POOL_SIZE,
            maxsize=POOL_SIZE,
            autocommit=True,
            charset="utf8mb4",
        )

    async def query(self, endpoint):
        async with self.pool.acquire() as conn:
            async with conn.cursor(self.DictCursor) as cur:
                await cur.execute(QUERIES[endpoint])
                rows = await cur.fetchall()
        body = json_bytes_from_rows(rows)
        if len(rows) != 10:
            raise RuntimeError(f"asyncmy returned {len(rows)} rows")
        return len(body)

    async def close(self):
        self.pool.close()
        await self.pool.wait_closed()


class AiomysqlAdapter:
    name = "aiomysql"
    package = "aiomysql"

    async def start(self):
        import aiomysql

        self.aiomysql = aiomysql
        self.pool = await aiomysql.create_pool(
            host=HOST,
            port=MYSQL_PORT,
            user="root",
            password="",
            db=DB,
            minsize=POOL_SIZE,
            maxsize=POOL_SIZE,
            autocommit=True,
            charset="utf8mb4",
        )

    async def query(self, endpoint):
        async with self.pool.acquire() as conn:
            async with conn.cursor(self.aiomysql.DictCursor) as cur:
                await cur.execute(QUERIES[endpoint])
                rows = await cur.fetchall()
        body = json_bytes_from_rows(rows)
        if len(rows) != 10:
            raise RuntimeError(f"aiomysql returned {len(rows)} rows")
        return len(body)

    async def close(self):
        self.pool.close()
        await self.pool.wait_closed()


class MysqlConnectorAioAdapter:
    name = "mysql.connector.aio"
    package = "mysql-connector-python"

    async def start(self):
        from mysql.connector.aio import connect

        self.queue = asyncio.Queue()
        self.connections = await asyncio.gather(
            *[
                connect(
                    host=HOST,
                    port=MYSQL_PORT,
                    user="root",
                    password="",
                    database=DB,
                    autocommit=True,
                    connection_timeout=10,
                )
                for _ in range(POOL_SIZE)
            ]
        )
        for conn in self.connections:
            await self.queue.put(conn)

    async def query(self, endpoint):
        conn = await self.queue.get()
        cur = None
        try:
            cur = await conn.cursor(dictionary=True)
            await cur.execute(QUERIES[endpoint])
            rows = await cur.fetchall()
        finally:
            if cur is not None:
                await cur.close()
            await self.queue.put(conn)
        body = json_bytes_from_rows(rows)
        if len(rows) != 10:
            raise RuntimeError(f"mysql.connector.aio returned {len(rows)} rows")
        return len(body)

    async def close(self):
        await asyncio.gather(*(conn.close() for conn in self.connections))


class PyreqwestAdapter:
    name = "pyreqwest async HTTP"
    package = "pyreqwest"

    async def start(self):
        from pyreqwest.client import ClientBuilder

        self.client = (
            ClientBuilder()
            .pool_max_idle_per_host(POOL_SIZE)
            .error_for_status(True)
            .build()
        )
        self.sem = asyncio.Semaphore(POOL_SIZE)
        self.auth = "Basic " + base64.b64encode(b"root:").decode()

    async def query(self, endpoint):
        async with self.sem:
            req = self.client.post(HTTP_URL)
            if hasattr(req, "basic_auth"):
                req = req.basic_auth("root", "")
            elif hasattr(req, "header"):
                req = req.header("Authorization", self.auth)
            response = await (
                req
                .body_json(
                    {
                        "query": QUERIES[endpoint],
                        "sessionVariables": {
                            "enable_query_cache": "true",
                            "pipeline_dop": "1",
                        },
                    }
                )
                .build()
                .send()
            )
            text = await response.text()

        columns = None
        rows = []
        for line in text.splitlines():
            if not line:
                continue
            item = json.loads(line)
            if "meta" in item:
                columns = [x["name"] for x in item["meta"]]
            elif "data" in item:
                rows.append(dict(zip(columns, item["data"])))
            elif item.get("status") == "FAILED":
                raise RuntimeError(item)
        body = json_bytes_from_rows(rows)
        if len(rows) != 10:
            raise RuntimeError(f"HTTP returned {len(rows)} rows")
        return len(body)

    async def close(self):
        close = getattr(self.client, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


class FlightThreadAdapter:
    name = "Arrow Flight ADBC via threadpool"
    package = "adbc-driver-flightsql"

    async def start(self):
        import adbc_driver_manager
        import adbc_driver_flightsql.dbapi as flight_sql

        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=FLIGHT_POOL
        )
        self.queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def open_conn():
            conn = flight_sql.connect(
                uri=f"grpc://{HOST}:{FLIGHT_PORT}",
                db_kwargs={
                    adbc_driver_manager.DatabaseOptions.USERNAME.value: "root",
                    adbc_driver_manager.DatabaseOptions.PASSWORD.value: "",
                },
            )
            cur = conn.cursor()
            cur.execute(f"USE {DB}")
            try:
                cur.fetchallarrow()
            except Exception:
                pass
            cur.close()
            return conn

        self.connections = await asyncio.gather(
            *[
                loop.run_in_executor(self.executor, open_conn)
                for _ in range(FLIGHT_POOL)
            ]
        )
        for conn in self.connections:
            await self.queue.put(conn)

    async def query(self, endpoint):
        conn = await self.queue.get()
        loop = asyncio.get_running_loop()

        def run():
            cur = conn.cursor()
            try:
                cur.execute(QUERIES[endpoint])
                table = cur.fetchallarrow()
            finally:
                cur.close()
            rows = table.to_pylist()
            body = json_bytes_from_rows(rows)
            if len(rows) != 10:
                raise RuntimeError(f"Flight returned {len(rows)} rows")
            return len(body)

        try:
            return await loop.run_in_executor(self.executor, run)
        finally:
            await self.queue.put(conn)

    async def close(self):
        loop = asyncio.get_running_loop()
        await asyncio.gather(
            *[
                loop.run_in_executor(self.executor, conn.close)
                for conn in self.connections
            ],
            return_exceptions=True,
        )
        self.executor.shutdown(wait=True, cancel_futures=True)


async def warm_adapter(adapter):
    for endpoint in range(20):
        await asyncio.wait_for(
            adapter.query(endpoint),
            timeout=REQUEST_TIMEOUT,
        )


async def run_open_loop(adapter, rate, seconds):
    loop = asyncio.get_running_loop()
    total = int(rate * seconds)
    workers = min(WORKERS, total)
    service = []
    end_to_end = []
    schedule_lag = []
    sizes = []
    errors = {}
    completed = 0
    attempted = 0
    start_gate = loop.time() + 0.25
    hard_deadline = start_gate + seconds + DRAIN_LIMIT
    last_done = start_gate
    lock = asyncio.Lock()

    async def worker(worker_id):
        nonlocal completed, attempted, last_done
        local_service = []
        local_e2e = []
        local_lag = []
        local_sizes = []
        local_errors = {}
        local_completed = 0
        local_attempted = 0
        local_last_done = start_gate

        for i in range(worker_id, total, workers):
            target = start_gate + (i / rate)
            delay = target - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)

            if loop.time() >= hard_deadline:
                break

            begin = loop.time()
            local_lag.append(max(0.0, (begin - target) * 1000.0))
            local_attempted += 1
            endpoint = i % 20
            try:
                size = await asyncio.wait_for(
                    adapter.query(endpoint),
                    timeout=REQUEST_TIMEOUT,
                )
                done = loop.time()
                local_service.append((done - begin) * 1000.0)
                local_e2e.append((done - target) * 1000.0)
                local_sizes.append(size)
                local_completed += 1
                local_last_done = max(local_last_done, done)
            except Exception as exc:
                done = loop.time()
                key = f"{type(exc).__name__}: {str(exc)[:180]}"
                local_errors[key] = local_errors.get(key, 0) + 1
                local_last_done = max(local_last_done, done)

        async with lock:
            completed += local_completed
            attempted += local_attempted
            last_done = max(last_done, local_last_done)
            service.extend(local_service)
            end_to_end.extend(local_e2e)
            schedule_lag.extend(local_lag)
            sizes.extend(local_sizes)
            for key, value in local_errors.items():
                errors[key] = errors.get(key, 0) + value

    await asyncio.gather(*(worker(i) for i in range(workers)))
    actual = max(seconds, last_done - start_gate)
    dropped = total - attempted
    query_failed = attempted - completed
    failed = total - completed
    return {
        "offered_qps": rate,
        "duration_s": seconds,
        "requests": total,
        "attempted": attempted,
        "completed": completed,
        "query_failed": query_failed,
        "dropped": dropped,
        "failed": failed,
        "success_rate": completed / total if total else 0.0,
        "attempt_success_rate": completed / attempted if attempted else 0.0,
        "achieved_qps": completed / actual if actual > 0 else 0.0,
        "actual_elapsed_s": actual,
        "drain_exhausted": dropped > 0,
        "service_p50_ms": percentile(service, 50),
        "service_p95_ms": percentile(service, 95),
        "service_p99_ms": percentile(service, 99),
        "e2e_p50_ms": percentile(end_to_end, 50),
        "e2e_p95_ms": percentile(end_to_end, 95),
        "e2e_p99_ms": percentile(end_to_end, 99),
        "schedule_lag_p99_ms": percentile(schedule_lag, 99),
        "median_json_bytes": int(statistics.median(sizes)) if sizes else 0,
        "errors": errors,
    }

async def bench_adapter(adapter_cls):
    adapter = adapter_cls()
    row = {
        "name": adapter.name,
        "package": adapter.package,
        "version": package_version(adapter.package),
        "pool_size": FLIGHT_POOL if isinstance(adapter, FlightThreadAdapter) else POOL_SIZE,
        "native_async": not isinstance(adapter, FlightThreadAdapter),
        "status": "failed",
        "loads": [],
    }
    try:
        started = time.perf_counter()
        await asyncio.wait_for(adapter.start(), timeout=30.0)
        row["startup_s"] = time.perf_counter() - started
        await asyncio.wait_for(warm_adapter(adapter), timeout=15.0)
        row["warm_ok"] = True

        for rate, seconds in LOADS:
            print(
                f"{adapter.name}: {rate:,} QPS for {seconds:.0f}s",
                flush=True,
            )
            result = await run_open_loop(adapter, rate, seconds)
            row["loads"].append(result)
            print(json.dumps(result, indent=2), flush=True)
            if result["drain_exhausted"]:
                print(
                    f"{adapter.name}: capacity exhausted at {rate:,} QPS; "
                    "skipping higher loads",
                    flush=True,
                )
                break
            await asyncio.sleep(1.0)
        row["status"] = "ok"
    except Exception as exc:
        row["error"] = repr(exc)
        print(f"{adapter.name} failed: {exc!r}", flush=True)
    finally:
        try:
            await asyncio.wait_for(adapter.close(), timeout=10.0)
        except Exception as exc:
            row["close_error"] = repr(exc)
    return row

async def main_async(version, load_s, qc_var):
    invalidate_query_cache()
    qc_before = query_cache_stat()

    conn = open_mysql(DB)
    try:
        with conn.cursor() as cur:
            for query in QUERIES:
                cur.execute(query)
                cur.fetchall()
    finally:
        conn.close()
    qc_warm = query_cache_stat()

    adapters = [
        AsyncmyAdapter,
        AiomysqlAdapter,
        MysqlConnectorAioAdapter,
        PyreqwestAdapter,
    ]
    random.Random(20261005).shuffle(adapters)

    results = []
    for adapter_cls in adapters:
        print(f"\n=== {adapter_cls.name} ===", flush=True)
        results.append(await bench_adapter(adapter_cls))

    qc_after = query_cache_stat()
    return {
        "meta": {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "starrocks_version": version,
            "rows_loaded": ROWS,
            "load_seconds": load_s,
            "query_cache_variable": list(qc_var) if qc_var else None,
            "query_cache_before": qc_before,
            "query_cache_after_warm": qc_warm,
            "query_cache_after": qc_after,
            "pool_size": POOL_SIZE,
            "flight_pool_size": FLIGHT_POOL,
            "scheduler_workers": WORKERS,
            "request_timeout_s": REQUEST_TIMEOUT,
            "drain_limit_s": DRAIN_LIMIT,
            "loads": LOADS,
            "endpoints": 20,
            "primary_target_qps": 4000,
            "per_endpoint_qps_at_primary": 200,
            "result_rows_per_request": 10,
        },
        "results": results,
    }


def write_results(payload):
    os.makedirs("results", exist_ok=True)
    with open("results/starrocks_async_latest.json", "w") as f:
        json.dump(payload, f, indent=2)

    meta = payload["meta"]
    good = [x for x in payload["results"] if x["status"] == "ok"]

    lines = [
        "# StarRocks async client benchmark",
        "",
        f"- StarRocks: {meta['starrocks_version']}",
        f"- Rows loaded: {meta['rows_loaded']:,}",
        f"- Query Cache variable: {meta['query_cache_variable']}",
        f"- Main pool size: {meta['pool_size']}",
        f"- Flight thread/connection pool: {meta['flight_pool_size']}",
        "- 20 fixed dashboard endpoint queries, each returning 10 aggregate rows.",
        "- Primary load: 4,000 QPS = 20 endpoints × 200 QPS.",
        "- Every request includes Query Cache + pipeline_dop=1 SET_VAR hints.",
        "- Latency is JSON-ready latency and includes pool/semaphore wait.",
        "",
        "## Query Cache verification",
        "",
    ]
    for key in ["query_cache_before", "query_cache_after_warm", "query_cache_after"]:
        stat = meta.get(key, {})
        lines.append(
            f"- **{key}**: lookup={stat.get('lookup_count')}, "
            f"hit={stat.get('hit_count')}, "
            f"hit_ratio={stat.get('hit_ratio')}, usage={stat.get('usage')}"
        )

    for rate, _seconds in LOADS:
        lines.extend([
            "",
            f"## {rate:,} offered QPS",
            "",
            "| Client | Async model | Success | Achieved QPS | p50 | p95 | p99 | E2E p99 | Errors |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        rows = []
        for case in good:
            load = next(
                (x for x in case["loads"] if x["offered_qps"] == rate),
                None,
            )
            if load:
                rows.append((case, load))
        rows.sort(
            key=lambda x: (
                x[1]["success_rate"] >= 0.999,
                x[1]["achieved_qps"],
                -x[1]["service_p99_ms"],
            ),
            reverse=True,
        )
        for case, load in rows:
            model = "native asyncio" if case["native_async"] else "threadpool adapter"
            lines.append(
                f"| {case['name']} | {model} | "
                f"{load['success_rate'] * 100:.2f}% | "
                f"{load['achieved_qps']:,.0f} | "
                f"{load['service_p50_ms']:.2f} ms | "
                f"{load['service_p95_ms']:.2f} ms | "
                f"{load['service_p99_ms']:.2f} ms | "
                f"{load['e2e_p99_ms']:.2f} ms | "
                f"{load['failed']} |"
            )

    failed = [x for x in payload["results"] if x["status"] != "ok"]
    if failed:
        lines.extend(["", "## Compatibility/startup failures", ""])
        for case in failed:
            lines.append(
                f"- **{case['name']} {case['version']}**: {case.get('error', 'unknown')}"
            )

    primary = []
    for case in good:
        load = next(
            (x for x in case["loads"] if x["offered_qps"] == 4000),
            None,
        )
        if load:
            primary.append((case, load))
    primary.sort(
        key=lambda x: (
            x[1]["success_rate"] >= 0.999,
            x[1]["achieved_qps"],
            -x[1]["service_p99_ms"],
        ),
        reverse=True,
    )

    lines.extend(["", "## Decision rule", ""])
    if primary:
        best, load = primary[0]
        lines.append(
            f"- Best 4,000-QPS result in this run: **{best['name']}** "
            f"({load['success_rate'] * 100:.2f}% success, "
            f"{load['achieved_qps']:,.0f} achieved QPS, "
            f"p99 {load['service_p99_ms']:.2f} ms)."
        )
    lines.extend([
        "- Prefer native asyncio clients for the Sanic hot path; Arrow Flight ADBC is shown separately because the Python ADBC API is blocking and needs a thread executor.",
        "- This GitHub-hosted runner is a comparative 4-vCPU environment; production sizing still needs a run on the 16-core API host against the real 3-FE/4-BE cluster.",
        "",
    ])

    with open("STARROCKS_ASYNC_BENCHMARK.md", "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines), flush=True)


def main():
    print("waiting for StarRocks...", flush=True)
    version = wait_mysql()
    print("StarRocks:", version, flush=True)
    alive = wait_backend()
    print(f"alive backends: {len(alive)}", flush=True)
    load_s, qc_var = setup_data()
    print(f"loaded {ROWS:,} rows in {load_s:.3f}s", flush=True)
    payload = asyncio.run(main_async(version, load_s, qc_var))
    write_results(payload)


if __name__ == "__main__":
    main()
