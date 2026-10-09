"""Real StarRocks request-through benchmark; Python 3.13, Linux."""
import argparse
import asyncio
import importlib.metadata
import math
import os
import re
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

import aiomysql
import orjson

CONFIG = Path(os.getenv("BENCH_QUERIES", "realtime_gateway/local_benchmark/queries.toml"))
QUERIES = {}
POOL = None
POOL_LOCK = None
POOL_LOOP = None
ERROR_LOG_COUNTS = Counter()


def load_queries():
    with CONFIG.open("rb") as f:
        metrics = tomllib.load(f)["metrics"]
    result = {}
    for metric in metrics:
        name, sql = metric["id"], metric["sql"].strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
            raise ValueError("Invalid metric id")
        if name in result or not sql.lower().startswith("select"):
            raise ValueError("Duplicate id or SQL does not start with SELECT")
        result[name] = sql
    if not result:
        raise ValueError("No metrics")
    return result


async def get_pool():
    global POOL, POOL_LOCK, POOL_LOOP
    loop = asyncio.get_running_loop()
    if POOL_LOOP is not None and POOL_LOOP is not loop:
        raise RuntimeError("Framework uses multiple event loops per process; aiomysql pool cannot be shared")
    if POOL_LOCK is None:
        POOL_LOOP, POOL_LOCK = loop, asyncio.Lock()
    async with POOL_LOCK:
        if POOL is None:
            POOL = await aiomysql.create_pool(
                host=os.environ["SR_HOST"],
                port=int(os.getenv("SR_PORT", "9030")),
                user=os.environ["SR_USER"],
                password=os.environ["SR_PASSWORD"],
                db=os.environ["SR_DATABASE"],
                minsize=1, maxsize=int(os.getenv("SR_POOL_SIZE", "32")),
                autocommit=True, charset="utf8mb4",
                connect_timeout=5,
                init_command="SET enable_query_cache = true",
            )
    return POOL


class RowLimitExceeded(RuntimeError):
    pass


class QueryTimeout(TimeoutError):
    def __init__(self, phase):
        self.phase = phase
        super().__init__(f"SR_TIMEOUT exceeded during {phase}")


async def query_metric(name):
    phase = "pool_init"
    async def read():
        nonlocal phase
        pool = await get_pool()
        phase = "pool_wait"
        async with pool.acquire() as conn:
            phase = "execute_fetch"
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(QUERIES[name])
                limit = int(os.getenv("SR_MAX_ROWS", "1000"))
                rows = await cur.fetchmany(limit + 1)
                if len(rows) > limit:
                    raise RowLimitExceeded(
                        f"指标 {name} 返回至少 {len(rows)} 行，超过 SR_MAX_ROWS={limit}。"
                        "请在该 SELECT 中限定实际需要的结果，或将 SR_MAX_ROWS 调整为预期上限。"
                    )
                return list(rows)
    timeout = asyncio.timeout(float(os.getenv("SR_TIMEOUT", "5")))
    try:
        async with timeout:
            return await read()
    except TimeoutError as exc:
        if not timeout.expired():
            raise
        raise QueryTimeout(phase) from exc


async def result_for(path):
    if path == "/healthz":
        return 200, {"ok": True}
    if not path.startswith("/api/") or path[5:] not in QUERIES:
        return 404, {"code": 404, "message": "Unknown metric"}
    name = path[5:]
    try:
        rows = await query_metric(name)
        return 200, {"code": 0, "metric": name, "data": rows, "count": len(rows)}
    except Exception as exc:
        phase = getattr(exc, "phase", "query")
        key = (name, type(exc).__name__, phase)
        ERROR_LOG_COUNTS[key] += 1
        if ERROR_LOG_COUNTS[key] <= 3:
            detail = str(exc)
            password = os.getenv("SR_PASSWORD", "")
            if password:
                detail = detail.replace(password, "[REDACTED]")
            print(f"metric={name} phase={phase} error={type(exc).__name__}: {detail}",
                  file=sys.stderr, flush=True)
        return 502, {"code": 502, "message": type(exc).__name__, "phase": phase}


def encode(value):
    return orjson.dumps(value, default=str)


kind = os.getenv("BENCH_FRAMEWORK", "granian")
if kind == "granian":
    async def app(scope, proto):
        if scope.proto != "http":
            proto.response_empty(404, [])
            return
        if scope.method != "GET":
            proto.response_empty(405, [("allow", "GET")])
            return
        status, value = await result_for(scope.path)
        proto.response_bytes(status, [("content-type", "application/json")], encode(value))

elif kind == "sanic":
    from sanic import Sanic
    from sanic.response import raw
    app = Sanic("real_starrocks")
    @app.get("/<path:path>")
    async def handler(request, path):
        status, value = await result_for("/" + path.lstrip("/"))
        return raw(encode(value), status=status, content_type="application/json")

elif kind == "bustapi":
    from bustapi import BustAPI
    app = BustAPI()
    def register(path):
        async def handler():
            status, value = await result_for(path)
            return encode(value).decode(), status, {"Content-Type": "application/json"}
        handler.__name__ = "metric_" + path.replace("/", "_")
        app.route(path, methods=["GET"])(handler)
    # Registration occurs in main after reading queries.

elif kind == "jero":
    from jero import BaseApp, BytesResponse, Endpoint

    def make_endpoint(path):
        class MetricEndpoint(Endpoint, path=path):
            async def get(self) -> BytesResponse:
                status, value = await result_for(path)
                return BytesResponse(content=encode(value), status_code=status,
                                     raw_headers={"content-type": "application/json"})
        MetricEndpoint.__name__ = "Metric_" + path.replace("/", "_")
        return MetricEndpoint

    class JeroApp(BaseApp):
        async def wire(self) -> None:
            for path in ["/healthz"] + ["/api/" + name for name in QUERIES]:
                self._include_endpoint(make_endpoint(path)())

    app = JeroApp()

elif kind == "robyn":
    from robyn import Robyn, Response
    app = Robyn(__file__)

    def register(path):
        async def handler(request):
            status, value = await result_for(path)
            return Response(status_code=status,
                            headers={"Content-Type": "application/json"},
                            description=encode(value).decode())
        handler.__name__ = "metric_" + path.replace("/", "_")
        app.get(path)(handler)

elif kind == "litestar":
    from litestar import Litestar, get, Response
    @get("/{path:path}")
    async def handler(path: str) -> Response:
        status, value = await result_for("/" + path.lstrip("/"))
        return Response(content=encode(value), status_code=status, media_type="application/json")
    app = Litestar(route_handlers=[handler], openapi_config=None)

else:
    raise ValueError("Unknown BENCH_FRAMEWORK")

# Imported by Granian, as opposed to running the load subcommand.
if __name__ != "__main__":
    QUERIES = load_queries()


async def check():
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT current_version()")
                version = (await cur.fetchone())[0]
                await cur.execute("SHOW VARIABLES LIKE 'enable_query_cache'")
                cache = await cur.fetchone()
        print("StarRocks:", version, "query_cache:", cache)
        if "4.1.1" not in str(version):
            print("NOTE: server version differs from expected 4.1.1")
        for name in QUERIES:
            begin = time.perf_counter()
            try:
                rows = await query_metric(name)
            except Exception as exc:
                detail = str(exc)
                password = os.getenv("SR_PASSWORD", "")
                if password:
                    detail = detail.replace(password, "[REDACTED]")
                raise RuntimeError(f"指标 {name} 查询失败：{type(exc).__name__}: {detail}") from None
            print(name, "rows:", len(rows), "query_ms:", round((time.perf_counter()-begin)*1000, 2),
                  "json_bytes:", len(encode(rows)), flush=True)
    finally:
        pool.close()
        await pool.wait_closed()


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered)-1, math.ceil(len(ordered)*pct/100)-1))]


async def load(args):
    import aiohttp
    names = list(QUERIES)
    errors = Counter()
    service, e2e, successful = [], [], []
    per_metric = {name: Counter() for name in names}
    active = set()
    offered = int(args.qps * args.seconds)
    completed = 0
    start = asyncio.get_running_loop().time()
    last_done = start
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=args.concurrency),
        timeout=aiohttp.ClientTimeout(total=args.timeout),
    ) as session:
        # Validate every endpoint and warm each framework before measured requests.
        for name in names:
            async with session.get(args.url.rstrip("/") + "/api/" + name) as r:
                value = orjson.loads(await r.read())
                if r.status != 200 or value.get("code") != 0 or value.get("metric") != name or not isinstance(value.get("data"), list):
                    raise RuntimeError("Preflight failed: " + name + ": " + str(value))
        start = asyncio.get_running_loop().time()
        last_done = start
        async def one(name, target):
            nonlocal completed, last_done
            begin = asyncio.get_running_loop().time()
            ok = False
            try:
                async with session.get(args.url.rstrip("/") + "/api/" + name) as r:
                    value = orjson.loads(await r.read())
                    if r.status != 200 or value.get("code") != 0 or value.get("metric") != name or not isinstance(value.get("data"), list):
                        raise RuntimeError(f"HTTP {r.status}: {value.get('message', 'invalid body')} phase={value.get('phase', 'unknown')}")
                ok = True
                completed += 1
                per_metric[name]["ok"] += 1
            except Exception as exc:
                errors[type(exc).__name__ + ": " + str(exc)[:100]] += 1
                per_metric[name]["failed"] += 1
            finally:
                done = asyncio.get_running_loop().time()
                last_done = max(last_done, done)
                if ok:
                    successful.append((done - begin)*1000)
                service.append((done - begin)*1000)
                e2e.append((done - target)*1000)
        for i in range(offered):
            target = start + i/args.qps
            now = asyncio.get_running_loop().time()
            if target > now:
                await asyncio.sleep(target-now)
            name = names[i % len(names)]
            if len(active) >= args.concurrency:
                errors["load_generator_concurrency_limit"] += 1
                per_metric[name]["dropped"] += 1
                continue
            task = asyncio.create_task(one(name, target))
            active.add(task)
            task.add_done_callback(active.discard)
        if active:
            await asyncio.gather(*list(active))
    versions = {}
    for pkg in ["aiomysql", "orjson", "aiohttp", "granian", "sanic", "bustapi", "litestar", "jero", "robyn", "uvloop"]:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            pass
    out = {
        "url": args.url, "label": args.label, "versions_on_load_host": versions,
        "metrics": len(names), "offered_qps": args.qps,
        "qps_per_metric": args.qps / len(names),
        "offered": offered, "completed": completed,
        "success_rate": completed/offered,
        "achieved_qps_including_drain": completed/max(args.seconds, last_done-start),
        "successful_response_p99_ms": percentile(successful, 99),
        "response_p50_ms": percentile(service, 50),
        "response_p95_ms": percentile(service, 95),
        "response_p99_ms": percentile(service, 99),
        "scheduled_e2e_p99_ms": percentile(e2e, 99),
        "errors": dict(errors), "per_metric": per_metric,
        "latency_includes_failures": True,
        "api_cache": False, "singleflight": False, "authentication": False,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_bytes(orjson.dumps(out, option=orjson.OPT_INDENT_2))
    print(orjson.dumps(out, option=orjson.OPT_INDENT_2).decode())


def main():
    global QUERIES
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["serve", "check", "load"])
    p.add_argument("--url", default="http://127.0.0.1:33335")
    p.add_argument("--qps", type=int, default=100)
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--concurrency", type=int, default=512)
    p.add_argument("--timeout", type=float, default=10)
    p.add_argument("--label", default="manual")
    p.add_argument("--log-level", default="WARNING", help="Robyn logging level")
    p.add_argument("--output", default="results/local_starrocks.json")
    args = p.parse_args()
    if min(args.qps, args.seconds, args.concurrency, args.timeout) <= 0:
        p.error("Load parameters must be positive")
    QUERIES = load_queries()
    if args.mode in ("check", "load"):
        asyncio.run(check() if args.mode == "check" else load(args))
        return
    host = os.getenv("BENCH_BIND", "0.0.0.0")
    port = int(os.getenv("BENCH_PORT", "33335"))
    workers = int(os.getenv("BENCH_WORKERS", "1"))
    if kind == "sanic":
        app.run(host=host, port=port, workers=workers, single_process=(workers == 1), access_log=False, motd=False)
    elif kind == "bustapi":
        for path in ["/healthz"] + ["/api/" + name for name in QUERIES]:
            register(path)
        app.run(host=host, port=port, workers=workers, debug=False)
    elif kind == "robyn":
        for path in ["/healthz"] + ["/api/" + name for name in QUERIES]:
            register(path)
        app.config.processes = workers
        app.config.workers = 1
        app.config.disable_openapi = True
        app.start(host=host, port=port)
    else:
        p.error("Use granian CLI for this framework; see README")


if __name__ == "__main__":
    main()

