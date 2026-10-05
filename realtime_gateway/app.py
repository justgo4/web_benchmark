import asyncio
import hmac
import json
import os
import re
import time
from pathlib import Path

import aiomysql
import orjson


JSON_HEADERS = [
    ("content-type", "application/json"),
    ("cache-control", "no-store"),
    ("x-content-type-options", "nosniff"),
]
OK = b'{"ok":true}'
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def dumps(value):
    return orjson.dumps(value, default=str)


def read_json(path):
    with open(path, "rb") as fp:
        return json.load(fp)


class GatewayApp:
    def __init__(self):
        self.config = None
        self.metric_specs = {}
        self.metric_ids = ()
        self.metric_index = {}
        self.metric_state = {}
        self.next_due = {}
        self.users = {}
        self.pools = []
        self.pool_cursor = 0
        self.snapshot = None
        self.scheduler_task = None
        self.snapshot_task = None
        self.inflight = {}
        self.snapshot_dirty = False
        self.last_error = ""

    def __rsgi_init__(self, loop):
        loop.run_until_complete(self.start(loop))

    def __rsgi_del__(self, loop):
        loop.run_until_complete(self.stop())

    async def start(self, loop):
        config_path = Path(
            os.getenv("GATEWAY_CONFIG", "realtime_gateway/config.json")
        ).resolve()
        self.config = read_json(config_path)
        base = config_path.parent

        metrics_file = Path(self.config.get("metrics_file", "metrics.json"))
        if not metrics_file.is_absolute():
            metrics_file = base / metrics_file
        self.load_metrics(metrics_file)

        users_file = Path(self.config.get("users_file", "users.json"))
        if not users_file.is_absolute():
            users_file = base / users_file
        self.users = self.load_users(users_file)

        sr = self.config["starrocks"]
        hosts = sr.get("hosts") or [sr.get("host", "127.0.0.1")]
        password = os.getenv(sr.get("password_env", "STARROCKS_PASSWORD"), "")
        pool_per_fe = int(sr.get("pool_per_fe", 4))

        for host in hosts:
            self.pools.append(
                await aiomysql.create_pool(
                    host=host,
                    port=int(sr.get("port", 9030)),
                    user=sr["user"],
                    password=password,
                    db=sr.get("database"),
                    minsize=0,
                    maxsize=pool_per_fe,
                    autocommit=True,
                    charset="utf8mb4",
                    connect_timeout=float(sr.get("connect_timeout_s", 2)),
                )
            )

        await self.initial_refresh()

        now = loop.time()
        total = len(self.metric_ids)
        for pos, metric_id in enumerate(self.metric_ids):
            interval = self.metric_specs[metric_id]["refresh_ms"] / 1000.0
            # Spread future reads across each metric's refresh window.
            self.next_due[metric_id] = now + interval * (pos + 1) / total

        self.rebuild_snapshot()
        self.scheduler_task = loop.create_task(self.scheduler_loop())
        self.snapshot_task = loop.create_task(self.snapshot_loop())

    async def stop(self):
        for task in [self.scheduler_task, self.snapshot_task]:
            if task is not None:
                task.cancel()

        for task in list(self.inflight.values()):
            task.cancel()

        tasks = [
            task
            for task in [self.scheduler_task, self.snapshot_task]
            if task is not None
        ] + list(self.inflight.values())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for pool in self.pools:
            pool.close()
        for pool in self.pools:
            await pool.wait_closed()

    def load_metrics(self, path):
        data = read_json(path)
        rows = data.get("metrics") or []
        if not rows:
            raise RuntimeError("metrics file contains no metrics")
        if len(rows) > 4096:
            raise RuntimeError("too many metrics")

        default_refresh = int(self.config.get("default_refresh_ms", 1000))
        default_stale = int(self.config.get("default_max_stale_ms", 10000))
        default_max_rows = int(self.config.get("default_max_rows", 1000))
        specs = {}

        for row in rows:
            metric_id = row.get("id", "")
            if not isinstance(metric_id, str) or not ID_RE.fullmatch(metric_id):
                raise RuntimeError(f"invalid metric id: {metric_id!r}")
            if metric_id in specs:
                raise RuntimeError(f"duplicate metric id: {metric_id!r}")

            sql = row.get("sql", "").strip()
            if not sql:
                raise RuntimeError(f"{metric_id!r} has no SQL")
            if not sql.lower().startswith("select"):
                raise RuntimeError(f"{metric_id!r} SQL must be SELECT")

            refresh_ms = int(row.get("refresh_ms", default_refresh))
            max_stale_ms = int(
                row.get(
                    "max_stale_ms",
                    max(default_stale, refresh_ms * 3),
                )
            )
            if refresh_ms < 100:
                raise RuntimeError(
                    f"{metric_id!r} refresh_ms must be >= 100"
                )

            max_rows = int(row.get("max_rows", default_max_rows))
            if max_rows < 1 or max_rows > 100000:
                raise RuntimeError(
                    f"{metric_id!r} max_rows must be between 1 and 100000"
                )

            specs[metric_id] = {
                "id": metric_id,
                "sql": sql,
                "refresh_ms": refresh_ms,
                "max_stale_ms": max_stale_ms,
                "max_rows": max_rows,
            }

        self.metric_specs = specs
        self.metric_ids = tuple(specs)
        self.metric_index = {
            metric_id: idx for idx, metric_id in enumerate(self.metric_ids)
        }
        self.metric_state = {
            metric_id: {
                "data": [],
                "updated_ms": None,
                "failures": 0,
                "last_error": "",
            }
            for metric_id in self.metric_ids
        }

    def load_users(self, path):
        data = read_json(path)
        users = {}
        full_mask = (1 << len(self.metric_ids)) - 1

        for row in data.get("users", []):
            key = row.get("key", "")
            if not key or key in users:
                raise RuntimeError(f"invalid or duplicate api key: {key!r}")

            secret_env = row.get("secret_env")
            if not secret_env:
                raise RuntimeError(f"{key!r} missing secret_env")
            secret = os.getenv(secret_env)
            if not secret:
                raise RuntimeError(
                    f"environment variable {secret_env!r} is empty"
                )
            if len(secret) < 16:
                raise RuntimeError(f"secret for {key!r} is too short")

            allowed = row.get("metrics", [])
            if allowed == "*":
                mask = full_mask
            else:
                mask = 0
                for metric_id in allowed:
                    idx = self.metric_index.get(metric_id)
                    if idx is None:
                        raise RuntimeError(
                            f"{key!r} references unknown metric {metric_id!r}"
                        )
                    mask |= 1 << idx

            users[key] = (secret.encode(), mask)

        if not users:
            raise RuntimeError("users file contains no users")
        return users

    async def query(self, sql, max_rows):
        timeout = float(self.config.get("refresh_timeout_ms", 800)) / 1000.0
        errors = []
        total = len(self.pools)

        start_idx = self.pool_cursor
        self.pool_cursor = (self.pool_cursor + 1) % total

        for offset in range(total):
            idx = (start_idx + offset) % total
            pool = self.pools[idx]
            try:
                async with pool.acquire() as conn:
                    async def run():
                        async with conn.cursor(aiomysql.DictCursor) as cur:
                            await cur.execute(sql)
                            rows = await cur.fetchmany(max_rows + 1)
                            if len(rows) > max_rows:
                                raise RuntimeError(
                                    f"query exceeded max_rows={max_rows}"
                                )
                            return rows

                    return await asyncio.wait_for(run(), timeout=timeout)
            except Exception as exc:
                errors.append(
                    f"{idx}:{type(exc).__name__}:{str(exc)[:120]}"
                )

        raise RuntimeError("all FE queries failed: " + " | ".join(errors))

    async def refresh_metric(self, metric_id):
        spec = self.metric_specs[metric_id]
        state = self.metric_state[metric_id]

        try:
            rows = await self.query(spec["sql"], spec["max_rows"])
            state["data"] = [dict(row) for row in rows]
            state["updated_ms"] = int(time.time() * 1000)
            state["failures"] = 0
            state["last_error"] = ""
            self.snapshot_dirty = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state["failures"] += 1
            state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            self.last_error = f"{metric_id}: {state['last_error']}"[:500]
        finally:
            self.inflight.pop(metric_id, None)

    async def initial_refresh(self):
        concurrency = int(self.config.get("refresh_concurrency", 12))
        sem = asyncio.Semaphore(concurrency)

        async def one(metric_id):
            async with sem:
                await self.refresh_metric(metric_id)

        await asyncio.gather(
            *(one(metric_id) for metric_id in self.metric_ids)
        )

    async def scheduler_loop(self):
        tick = float(self.config.get("scheduler_tick_ms", 20)) / 1000.0
        concurrency = int(self.config.get("refresh_concurrency", 12))
        loop = asyncio.get_running_loop()

        while True:
            now = loop.time()
            free = max(0, concurrency - len(self.inflight))

            if free:
                due = [
                    metric_id
                    for metric_id in self.metric_ids
                    if metric_id not in self.inflight
                    and self.next_due[metric_id] <= now
                ]
                due.sort(key=self.next_due.__getitem__)

                for metric_id in due[:free]:
                    spec = self.metric_specs[metric_id]
                    interval = spec["refresh_ms"] / 1000.0
                    next_due = self.next_due[metric_id] + interval
                    while next_due <= now:
                        next_due += interval
                    self.next_due[metric_id] = next_due

                    task = loop.create_task(self.refresh_metric(metric_id))
                    self.inflight[metric_id] = task

            await asyncio.sleep(tick)

    async def snapshot_loop(self):
        interval = (
            float(self.config.get("snapshot_rebuild_ms", 20)) / 1000.0
        )
        while True:
            await asyncio.sleep(interval)
            if self.snapshot_dirty:
                self.rebuild_snapshot()
                self.snapshot_dirty = False

    def rebuild_snapshot(self):
        metric_bodies = {}
        metric_values = {}

        for metric_id in self.metric_ids:
            state = self.metric_state[metric_id]
            value = {
                "updated_ms": state["updated_ms"],
                "data": state["data"],
            }
            metric_values[metric_id] = value
            metric_bodies[metric_id] = dumps(
                {
                    "code": 0,
                    "metric": metric_id,
                    **value,
                }
            )

        user_bodies = {}
        for key, (_secret, mask) in self.users.items():
            visible = {}
            for idx, metric_id in enumerate(self.metric_ids):
                if mask & (1 << idx):
                    visible[metric_id] = metric_values[metric_id]

            user_bodies[key] = dumps(
                {
                    "code": 0,
                    "snapshot_ms": int(time.time() * 1000),
                    "data": visible,
                }
            )

        self.snapshot = {
            "built_ms": int(time.time() * 1000),
            "metric_bodies": metric_bodies,
            "user_bodies": user_bodies,
        }

    def metric_is_stale(self, metric_id, now_ms=None):
        now_ms = now_ms or int(time.time() * 1000)
        state = self.metric_state[metric_id]
        updated_ms = state["updated_ms"]
        if updated_ms is None:
            return True
        return (
            now_ms - updated_ms
            > self.metric_specs[metric_id]["max_stale_ms"]
        )

    def readiness(self):
        now_ms = int(time.time() * 1000)
        uninitialized = []
        stale = []
        failed = []

        for metric_id in self.metric_ids:
            state = self.metric_state[metric_id]
            if state["updated_ms"] is None:
                uninitialized.append(metric_id)
            elif self.metric_is_stale(metric_id, now_ms):
                stale.append(metric_id)
            if state["failures"]:
                failed.append(metric_id)

        return {
            "ready": not uninitialized and not stale,
            "metrics": len(self.metric_ids),
            "inflight": len(self.inflight),
            "uninitialized": uninitialized,
            "stale": stale,
            "failed": failed,
            "last_error": self.last_error,
        }

    def authenticate(self, scope, metric_id=None):
        headers = scope.headers
        key = headers.get("x-api-key")
        ts = headers.get("x-timestamp")
        signature = headers.get("x-signature")

        if not key or not ts or not signature:
            return None

        user = self.users.get(key)
        if user is None:
            return None

        try:
            ts_i = int(ts)
        except Exception:
            return None

        window = int(self.config.get("auth_window_seconds", 30))
        if abs(int(time.time()) - ts_i) > window:
            return None

        secret, mask = user
        canonical = (
            scope.method + "\n" + scope.path + "\n" + ts
        ).encode()
        expected = hmac.digest(secret, canonical, "sha256").hex()

        if not hmac.compare_digest(expected, signature):
            return None

        if metric_id is not None:
            idx = self.metric_index.get(metric_id)
            if idx is None or not (mask & (1 << idx)):
                return False

        return key

    async def __rsgi__(self, scope, proto):
        if scope.proto != "http":
            proto.response_empty(404, [])
            return

        if scope.method != "GET":
            proto.response_empty(405, [("allow", "GET")])
            return

        path = scope.path

        if path == "/healthz":
            proto.response_bytes(200, JSON_HEADERS, OK)
            return

        if path == "/readyz":
            ready = self.readiness()
            proto.response_bytes(
                200 if ready["ready"] else 503,
                JSON_HEADERS,
                dumps(ready),
            )
            return

        snapshot = self.snapshot
        if snapshot is None:
            proto.response_empty(503, [])
            return

        if path == "/snapshot":
            key = self.authenticate(scope)
            if not key:
                proto.response_empty(401, [])
                return
            proto.response_bytes(
                200,
                JSON_HEADERS,
                snapshot["user_bodies"][key],
            )
            return

        if path.startswith("/api/"):
            metric_id = path[5:]
            if metric_id not in self.metric_index:
                proto.response_empty(404, [])
                return

            auth = self.authenticate(scope, metric_id)
            if auth is None:
                proto.response_empty(401, [])
                return
            if auth is False:
                proto.response_empty(403, [])
                return

            if self.metric_state[metric_id]["updated_ms"] is None:
                proto.response_empty(503, [])
                return

            proto.response_bytes(
                200,
                JSON_HEADERS,
                snapshot["metric_bodies"][metric_id],
            )
            return

        proto.response_empty(404, [])


app = GatewayApp()
