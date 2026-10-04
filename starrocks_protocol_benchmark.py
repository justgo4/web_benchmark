#!/usr/bin/env python3
import base64
import json
import os
import random
import statistics
import time
import urllib.request

import pymysql
import adbc_driver_manager
import adbc_driver_flightsql.dbapi as flight_sql
from pyreqwest.client import SyncClientBuilder

HOST = "127.0.0.1"
MYSQL_PORT = 9030
HTTP_PORT = 8030
BE_HTTP_PORT = 8040
FLIGHT_PORT = 9408
DB = "protocol_bench"
ROWS = int(os.getenv("SR_BENCH_ROWS", "1000000"))
SIZES = [int(x) for x in os.getenv(
    "SR_BENCH_SIZES", "10,100,1000,10000,100000,500000"
).split(",")]
ROUNDS = int(os.getenv("SR_BENCH_ROUNDS", "5"))
JSON_ROUNDS = int(os.getenv("SR_BENCH_JSON_ROUNDS", "3"))

HTTP_URL = (
    f"http://{HOST}:{HTTP_PORT}/api/v1/catalogs/"
    f"default_catalog/databases/{DB}/sql"
)
QC_HINT = "/*+ SET_VAR(enable_query_cache=true, pipeline_dop=1) */"


def median(values):
    return statistics.median(values)


def p95(values):
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[94]


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
                cur.execute("SELECT VERSION()")
                version = cur.fetchone()[0]
            conn.close()
            return version
        except Exception as exc:
            last = exc
            time.sleep(2)
    raise RuntimeError(f"StarRocks MySQL port not ready: {last!r}")


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
                    grp INT NOT NULL,
                    v BIGINT NOT NULL,
                    payload VARCHAR(64) NOT NULL
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
                    generate_series % 100,
                    generate_series * 3,
                    concat('value-', cast(generate_series AS VARCHAR))
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


def build_http_client():
    return (
        SyncClientBuilder()
        .pool_max_idle_per_host(32)
        .error_for_status(True)
        .build()
    )


class HttpProtocol:
    name = "HTTP SQL API + pyreqwest"

    def __init__(self):
        self.client = build_http_client()
        self.auth = "Basic " + base64.b64encode(b"root:").decode()

    def close(self):
        close = getattr(self.client, "close", None)
        if close:
            close()

    def request_text(self, sql):
        req = self.client.post(HTTP_URL)
        if hasattr(req, "basic_auth"):
            req = req.basic_auth("root", "")
        elif hasattr(req, "header"):
            req = req.header("Authorization", self.auth)
        else:
            raise RuntimeError("pyreqwest RequestBuilder has no auth/header API")
        response = (
            req
            .body_json(
                {
                    "query": sql,
                    "sessionVariables": {
                        "enable_query_cache": "true",
                        "pipeline_dop": "1",
                    },
                }
            )
            .build()
            .send()
        )
        return response.text()

    @staticmethod
    def parse_rows(text):
        columns = None
        rows = []
        for line in text.splitlines():
            if not line:
                continue
            item = json.loads(line)
            if "meta" in item:
                columns = [x["name"] for x in item["meta"]]
            elif "data" in item:
                if columns:
                    rows.append(dict(zip(columns, item["data"])))
                else:
                    rows.append(item["data"])
            elif item.get("status") == "FAILED":
                raise RuntimeError(item)
        return rows

    def native(self, sql):
        start = time.perf_counter()
        text = self.request_text(sql)
        elapsed = time.perf_counter() - start
        rows = self.parse_rows(text)
        return elapsed, len(rows), len(text.encode())

    def json_ready(self, sql):
        start = time.perf_counter()
        text = self.request_text(sql)
        rows = self.parse_rows(text)
        body = json.dumps(rows, separators=(",", ":")).encode()
        elapsed = time.perf_counter() - start
        return elapsed, len(rows), len(body)


class MysqlProtocol:
    name = "MySQL protocol + PyMySQL"

    def __init__(self):
        self.conn = open_mysql(DB)
        with self.conn.cursor() as cur:
            cur.execute("SET enable_query_cache = true")
            cur.execute("SET pipeline_dop = 1")

    def close(self):
        self.conn.close()

    def _fetch(self, sql):
        with self.conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            columns = [d[0] for d in cur.description]
        return columns, rows

    def native(self, sql):
        start = time.perf_counter()
        columns, rows = self._fetch(sql)
        elapsed = time.perf_counter() - start
        approx = len(json.dumps(rows, default=str).encode())
        return elapsed, len(rows), approx

    def json_ready(self, sql):
        start = time.perf_counter()
        columns, rows = self._fetch(sql)
        items = [dict(zip(columns, row)) for row in rows]
        body = json.dumps(items, default=str, separators=(",", ":")).encode()
        elapsed = time.perf_counter() - start
        return elapsed, len(rows), len(body)


class FlightProtocol:
    name = "Arrow Flight SQL ADBC"

    def __init__(self):
        self.conn = flight_sql.connect(
            uri=f"grpc://{HOST}:{FLIGHT_PORT}",
            db_kwargs={
                adbc_driver_manager.DatabaseOptions.USERNAME.value: "root",
                adbc_driver_manager.DatabaseOptions.PASSWORD.value: "",
            },
        )
        cur = self.conn.cursor()
        cur.execute(f"USE {DB}")
        try:
            cur.fetchallarrow()
        except Exception:
            pass
        cur.execute("SET enable_query_cache = true")
        try:
            cur.fetchallarrow()
        except Exception:
            pass
        cur.execute("SET pipeline_dop = 1")
        try:
            cur.fetchallarrow()
        except Exception:
            pass
        cur.close()

    def close(self):
        self.conn.close()

    def _fetch(self, sql):
        cur = self.conn.cursor()
        try:
            cur.execute(sql)
            return cur.fetchallarrow()
        finally:
            cur.close()

    def native(self, sql):
        start = time.perf_counter()
        table = self._fetch(sql)
        elapsed = time.perf_counter() - start
        return elapsed, table.num_rows, table.nbytes

    def json_ready(self, sql):
        start = time.perf_counter()
        table = self._fetch(sql)
        items = table.to_pylist()
        body = json.dumps(items, default=str, separators=(",", ":")).encode()
        elapsed = time.perf_counter() - start
        return elapsed, table.num_rows, len(body)


def wait_flight(timeout=120):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            p = FlightProtocol()
            p.close()
            return
        except Exception as exc:
            last = exc
            time.sleep(2)
    raise RuntimeError(f"Arrow Flight SQL not ready: {last!r}")


def run_case(protocols, sql, expected_rows, rounds, mode):
    for protocol in protocols:
        elapsed, rows, _ = getattr(protocol, mode)(sql)
        if rows != expected_rows:
            raise RuntimeError(
                f"{protocol.name} warmup returned {rows}, expected {expected_rows}"
            )

    samples = {p.name: [] for p in protocols}
    sizes = {p.name: [] for p in protocols}
    rng = random.Random(20261004 + expected_rows + rounds)
    for round_idx in range(rounds):
        order = list(protocols)
        rng.shuffle(order)
        for protocol in order:
            elapsed, rows, size_bytes = getattr(protocol, mode)(sql)
            if rows != expected_rows:
                raise RuntimeError(
                    f"{protocol.name} returned {rows}, expected {expected_rows}"
                )
            samples[protocol.name].append(elapsed * 1000.0)
            sizes[protocol.name].append(size_bytes)

    out = {}
    for name, values in samples.items():
        med = median(values)
        out[name] = {
            "median_ms": med,
            "p95_ms": p95(values),
            "rows_per_s": (
                expected_rows / (med / 1000.0) if med > 0 else 0
            ),
            "median_bytes": int(median(sizes[name])),
            "samples_ms": values,
        }
    return out


def best_name(result):
    return min(result, key=lambda x: result[x]["median_ms"])


def main():
    os.makedirs("results", exist_ok=True)
    print("waiting for StarRocks 4.1.1...", flush=True)
    version = wait_mysql()
    print("version:", version, flush=True)

    wait_flight()
    load_s, qc_var = setup_data()
    print(f"loaded {ROWS:,} rows in {load_s:.3f}s", flush=True)
    print("query_cache variable:", qc_var, flush=True)

    protocols = [
        HttpProtocol(),
        MysqlProtocol(),
        FlightProtocol(),
    ]

    result = {
        "starrocks_version": version,
        "rows_loaded": ROWS,
        "load_seconds": load_s,
        "query_cache_variable": list(qc_var) if qc_var else None,
        "query_cache": {},
        "cached_aggregate": {},
        "raw_fetch": {},
        "json_ready": {},
    }

    try:
        invalidate_query_cache()
        result["query_cache"]["after_invalidate"] = query_cache_stat()

        aggregate_sql = (
            f"SELECT {QC_HINT} grp, COUNT(*) AS c, SUM(v) AS s "
            "FROM bench GROUP BY grp ORDER BY grp"
        )

        # Populate once, then verify cache metrics before measured runs.
        protocols[0].native(aggregate_sql)
        result["query_cache"]["after_warm"] = query_cache_stat()

        result["cached_aggregate"]["native"] = run_case(
            protocols,
            aggregate_sql,
            100,
            ROUNDS,
            "native",
        )
        result["cached_aggregate"]["json_ready"] = run_case(
            protocols,
            aggregate_sql,
            100,
            JSON_ROUNDS,
            "json_ready",
        )
        result["query_cache"]["after_benchmark"] = query_cache_stat()

        for n in SIZES:
            if n > ROWS:
                continue
            sql = (
                f"SELECT {QC_HINT} id, grp, v, payload "
                f"FROM bench WHERE id <= {n}"
            )
            print(f"raw fetch {n:,} rows", flush=True)
            result["raw_fetch"][str(n)] = run_case(
                protocols,
                sql,
                n,
                ROUNDS,
                "native",
            )
            result["json_ready"][str(n)] = run_case(
                protocols,
                sql,
                n,
                JSON_ROUNDS,
                "json_ready",
            )
    finally:
        for protocol in protocols:
            try:
                protocol.close()
            except Exception:
                pass

    with open("results/starrocks_protocol_latest.json", "w") as f:
        json.dump(result, f, indent=2)

    lines = [
        "# StarRocks 4.1.1 protocol benchmark",
        "",
        f"- StarRocks reported version: `{version}`",
        f"- Rows loaded: {ROWS:,}",
        f"- Query Cache session variable: `{qc_var}`",
        "- Query Cache hint on every query: "
        "`SET_VAR(enable_query_cache=true, pipeline_dop=1)`",
        "- Arrow Flight proxy: StarRocks default (enabled).",
        "- HTTP client: pyreqwest persistent Rust/reqwest connection pool.",
        f"- Native rounds: {ROUNDS}; JSON-ready rounds: {JSON_ROUNDS}.",
        "",
        "## Query Cache verification",
        "",
    ]

    for label in ["after_invalidate", "after_warm", "after_benchmark"]:
        stat = result["query_cache"].get(label, {})
        lines.append(
            f"- **{label}**: lookup={stat.get('lookup_count')}, "
            f"hit={stat.get('hit_count')}, "
            f"hit_ratio={stat.get('hit_ratio')}, "
            f"usage={stat.get('usage')}"
        )

    def append_table(title, block, expected_rows):
        lines.extend([
            "",
            f"## {title}",
            "",
            "| Protocol | Median | p95 | Rows/s | Median bytes |",
            "|---|---:|---:|---:|---:|",
        ])
        ordered = sorted(
            block.items(),
            key=lambda kv: kv[1]["median_ms"],
        )
        for name, item in ordered:
            lines.append(
                f"| {name} | {item['median_ms']:.3f} ms | "
                f"{item['p95_ms']:.3f} ms | "
                f"{item['rows_per_s']:,.0f} | "
                f"{item['median_bytes']:,} |"
            )
        lines.append("")
        lines.append(f"Winner: **{ordered[0][0]}**.")

    append_table(
        "Cached aggregate — native result form (100 rows)",
        result["cached_aggregate"]["native"],
        100,
    )
    append_table(
        "Cached aggregate — converted to JSON-ready body (100 rows)",
        result["cached_aggregate"]["json_ready"],
        100,
    )

    lines.extend([
        "",
        "## Raw fetch by result size",
        "",
        "Query Cache is enabled but plain row retrieval is not a Query Cache "
        "application scenario; these rows measure protocol/serialization transfer.",
        "",
        "| Rows | HTTP ms | PyMySQL ms | Flight ms | Winner |",
        "|---:|---:|---:|---:|---|",
    ])
    names = [p.name for p in [
        type("P", (), {"name": "HTTP SQL API + pyreqwest"})(),
        type("P", (), {"name": "MySQL protocol + PyMySQL"})(),
        type("P", (), {"name": "Arrow Flight SQL ADBC"})(),
    ]]
    for n in SIZES:
        block = result["raw_fetch"].get(str(n))
        if not block:
            continue
        lines.append(
            f"| {n:,} | "
            f"{block[names[0]]['median_ms']:.3f} | "
            f"{block[names[1]]['median_ms']:.3f} | "
            f"{block[names[2]]['median_ms']:.3f} | "
            f"{best_name(block)} |"
        )

    lines.extend([
        "",
        "## JSON-ready by result size",
        "",
        "This includes conversion into JSON-compatible Python objects and "
        "JSON serialization, approximating a web API response path.",
        "",
        "| Rows | HTTP ms | PyMySQL ms | Flight ms | Winner |",
        "|---:|---:|---:|---:|---|",
    ])
    for n in SIZES:
        block = result["json_ready"].get(str(n))
        if not block:
            continue
        lines.append(
            f"| {n:,} | "
            f"{block[names[0]]['median_ms']:.3f} | "
            f"{block[names[1]]['median_ms']:.3f} | "
            f"{block[names[2]]['median_ms']:.3f} | "
            f"{best_name(block)} |"
        )

    lines.extend([
        "",
        "## Interpretation",
        "",
        "- Use the cached aggregate section for the real-time dashboard/API case.",
        "- Use raw-fetch results to decide when Arrow Flight becomes worthwhile "
        "for large result sets or exports.",
        "- GitHub-hosted runner results are comparative only; they are not an "
        "absolute production QPS estimate for the 16-core deployment.",
        "",
    ])

    with open("STARROCKS_PROTOCOL_BENCHMARK.md", "w") as f:
        f.write("\n".join(lines))

    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
