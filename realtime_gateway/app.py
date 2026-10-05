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
    with open(path, "rb") as f:
        return json.load(f)


class GatewayApp:
    def __init__(self):
        self.config = None
        self.metric_ids = ()
        self.metric_index = {}
        self.users = {}
        self.pools = []
        self.pool_cursor = 0
        self.snapshot = None
        self.refresh_task = None
        self.refresh_failures = 0
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

        metrics = self.config.get("metrics") or []
        if not metrics:
            raise RuntimeError("config.metrics must not be empty")
        if len(metrics) > 4096:
            raise RuntimeError("too many metrics")
        if len(metrics) != len(set(metrics)):
            raise RuntimeError("duplicate metric id")

        for metric_id in metrics:
            if not isinstance(metric_id, str) or not ID_RE.fullmatch(metric_id):
                raise RuntimeError(f"invalid metric id: {metric_id!r}")

        self.metric_ids = tuple(metrics)
        self.metric_index = {
            metric_id: idx for idx, metric_id in enumerate(self.metric_ids)
        }

        users_file = Path(self.config.get("users_file", "users.json"))
        if not users_file.is_absolute():
            users_file = base / users_file
        self.users = self.load_users(users_file)

        sr = self.config["starrocks"]
        hosts = sr.get("hosts") or [sr.get("host", "127.0.0.1")]
        password = os.getenv(sr.get("password_env", "STARROCKS_PASSWORD"), "")
        pool_per_fe = int(sr.get("pool_per_fe", 2))

        for host in hosts:
            pool = await aiomysql.create_pool(
                host=host,
                port=int(sr.get("port", 9030)),
                user=sr["user"],
                password=password,
                db=sr["database"],
                minsize=1,
                maxsize=pool_per_fe,
                autocommit=True,
                charset="utf8mb4",
                connect_timeout=float(sr.get("connect_timeout_s", 2)),
            )
            self.pools.append(pool)

        await self.refresh_once()
        self.refresh_task = loop.create_task(self.refresh_loop())

    async def stop(self):
        if self.refresh_task is not None:
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass

        for pool in self.pools:
            pool.close()
        for pool in self.pools:
            await pool.wait_closed()

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

    async def query(self, sql):
        timeout = float(self.config.get("refresh_timeout_ms", 800)) / 1000.0
        errors = []
        total = len(self.pools)

        for offset in range(total):
            idx = (self.pool_cursor + offset) % total
            pool = self.pools[idx]
            try:
                async with pool.acquire() as conn:
                    async def run():
                        async with conn.cursor(aiomysql.DictCursor) as cur:
                            await cur.execute(sql)
                            return await cur.fetchall()

                    rows = await asyncio.wait_for(run(), timeout=timeout)

                self.pool_cursor = (idx + 1) % total
                return rows
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        raise RuntimeError("all FE queries failed: " + " | ".join(errors))

    async def load_metric_data(self):
        mode = self.config.get("mode", "batch")

        if mode == "batch":
            id_column = self.config.get("metric_id_column", "metric_id")
            rows = await self.query(self.config["batch_sql"])
            grouped = {metric_id: [] for metric_id in self.metric_ids}

            for row in rows:
                metric_id = str(row.get(id_column, ""))
                if metric_id not in grouped:
                    continue
                item = dict(row)
                item.pop(id_column, None)
                grouped[metric_id].append(item)

            if self.config.get("require_all_metrics", True):
                missing = [
                    metric_id
                    for metric_id, values in grouped.items()
                    if not values
                ]
                if missing:
                    raise RuntimeError(
                        "missing metric rows: " + ",".join(missing[:20])
                    )

            return grouped

        if mode == "per_metric":
            queries = self.config.get("metric_queries") or {}
            concurrency = int(self.config.get("refresh_concurrency", 8))
            sem = asyncio.Semaphore(concurrency)

            async def one(metric_id):
                sql = queries.get(metric_id)
                if not sql:
                    raise RuntimeError(f"missing SQL for {metric_id!r}")
                async with sem:
                    rows = await self.query(sql)
                return metric_id, [dict(row) for row in rows]

            pairs = await asyncio.gather(
                *(one(metric_id) for metric_id in self.metric_ids)
            )
            return dict(pairs)

        raise RuntimeError(f"unknown mode: {mode!r}")

    def build_snapshot(self, data, updated_ms, version):
        metric_bodies = {
            metric_id: dumps(
                {
                    "code": 0,
                    "metric": metric_id,
                    "updated_ms": updated_ms,
                    "data": data.get(metric_id, []),
                }
            )
            for metric_id in self.metric_ids
        }

        user_bodies = {}
        for key, (_secret, mask) in self.users.items():
            visible = {}
            for idx, metric_id in enumerate(self.metric_ids):
                if mask & (1 << idx):
                    visible[metric_id] = data.get(metric_id, [])

            user_bodies[key] = dumps(
                {
                    "code": 0,
                    "updated_ms": updated_ms,
                    "data": visible,
                }
            )

        return {
            "version": version,
            "updated_ms": updated_ms,
            "metric_bodies": metric_bodies,
            "user_bodies": user_bodies,
        }

    async def refresh_once(self):
        data = await self.load_metric_data()
        updated_ms = int(time.time() * 1000)
        version = 1 if self.snapshot is None else self.snapshot["version"] + 1

        # Atomic reference replacement: readers see either old or new snapshot.
        self.snapshot = self.build_snapshot(data, updated_ms, version)
        self.refresh_failures = 0
        self.last_error = ""

    async def refresh_loop(self):
        interval = float(self.config.get("refresh_interval_ms", 1000)) / 1000.0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + interval

        while True:
            delay = deadline - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)

            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.refresh_failures += 1
                self.last_error = f"{type(exc).__name__}: {exc}"[:500]

            deadline += interval
            now = loop.time()
            if deadline < now:
                # Never overlap refreshes. If one cycle overruns, skip ahead.
                deadline = now + interval

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

    def snapshot_ready(self):
        snapshot = self.snapshot
        if snapshot is None:
            return False

        max_stale_ms = int(self.config.get("max_stale_ms", 10000))
        age_ms = int(time.time() * 1000) - snapshot["updated_ms"]
        return age_ms <= max_stale_ms

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
            now_ms = int(time.time() * 1000)
            snapshot = self.snapshot
            ready = self.snapshot_ready()
            body = dumps(
                {
                    "ready": ready,
                    "updated_ms": snapshot["updated_ms"] if snapshot else None,
                    "age_ms": (
                        now_ms - snapshot["updated_ms"]
                        if snapshot
                        else None
                    ),
                    "refresh_failures": self.refresh_failures,
                    "last_error": self.last_error,
                }
            )
            proto.response_bytes(200 if ready else 503, JSON_HEADERS, body)
            return

        snapshot = self.snapshot
        if snapshot is None:
            proto.response_empty(503, [])
            return

        if (
            not self.snapshot_ready()
            and not self.config.get("serve_stale_on_error", True)
        ):
            proto.response_empty(503, [])
            return

        if path == "/snapshot":
            key = self.authenticate(scope)
            if not key:
                proto.response_empty(401, [])
                return
            proto.response_bytes(200, JSON_HEADERS, snapshot["user_bodies"][key])
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

            proto.response_bytes(
                200,
                JSON_HEADERS,
                snapshot["metric_bodies"][metric_id],
            )
            return

        proto.response_empty(404, [])


app = GatewayApp()
