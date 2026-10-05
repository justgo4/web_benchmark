import hmac
import json
import os
import pathlib
import signal
import subprocess
import time
import urllib.error
import urllib.request

import pymysql


ROOT = pathlib.Path(__file__).resolve().parents[1]
HERE = ROOT / "realtime_gateway"
SECRET = "ci-secret-0123456789abcdef"


def wait_starrocks():
    deadline = time.time() + 180
    last = None
    while time.time() < deadline:
        try:
            conn = pymysql.connect(
                host="127.0.0.1",
                port=9030,
                user="root",
                password="",
                autocommit=True,
            )
            with conn.cursor() as cur:
                cur.execute("SHOW BACKENDS")
                rows = cur.fetchall()
                names = [x[0] for x in cur.description]
            conn.close()
            items = [dict(zip(names, row)) for row in rows]
            if any(str(x.get("Alive", "")).lower() == "true" for x in items):
                return
        except Exception as exc:
            last = exc
        time.sleep(2)
    raise RuntimeError(f"StarRocks not ready: {last!r}")


def setup_data():
    conn = pymysql.connect(
        host="127.0.0.1",
        port=9030,
        user="root",
        password="",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("DROP DATABASE IF EXISTS gateway_ci FORCE")
            cur.execute("CREATE DATABASE gateway_ci")
            cur.execute("USE gateway_ci")
            cur.execute(
                """
                CREATE TABLE metric_values (
                    metric_id VARCHAR(16) NOT NULL,
                    value BIGINT NOT NULL
                )
                DUPLICATE KEY(metric_id)
                DISTRIBUTED BY HASH(metric_id) BUCKETS 4
                PROPERTIES ("replication_num" = "1")
                """
            )
            values = ",".join(
                f"('m{i:03d}',{i})" for i in range(100)
            )
            cur.execute("INSERT INTO metric_values VALUES " + values)
    finally:
        conn.close()


def write_runtime_config():
    metrics = [f"m{i:03d}" for i in range(100)]
    config = {
        "users_file": "users.ci.json",
        "mode": "batch",
        "refresh_interval_ms": 500,
        "refresh_timeout_ms": 1500,
        "max_stale_ms": 5000,
        "serve_stale_on_error": True,
        "auth_window_seconds": 30,
        "require_all_metrics": True,
        "metric_id_column": "metric_id",
        "starrocks": {
            "hosts": ["127.0.0.1"],
            "port": 9030,
            "user": "root",
            "password_env": "STARROCKS_PASSWORD",
            "database": "gateway_ci",
            "pool_per_fe": 2
        },
        "batch_sql": (
            "SELECT /*+ SET_VAR(enable_query_cache=true, pipeline_dop=1) */ "
            "metric_id, value FROM metric_values ORDER BY metric_id"
        ),
        "metrics": metrics
    }
    users = {
        "users": [
            {
                "key": "ci-user",
                "secret_env": "CI_DASHBOARD_SECRET",
                "metrics": metrics[:50]
            }
        ]
    }
    (HERE / "config.ci.json").write_text(json.dumps(config), encoding="utf-8")
    (HERE / "users.ci.json").write_text(json.dumps(users), encoding="utf-8")


def sign(path):
    ts = str(int(time.time()))
    signature = hmac.digest(
        SECRET.encode(),
        ("GET\n" + path + "\n" + ts).encode(),
        "sha256",
    ).hex()
    return {
        "X-Api-Key": "ci-user",
        "X-Timestamp": ts,
        "X-Signature": signature
    }


def get(path):
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        headers=sign(path),
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return response.status, json.loads(response.read())


def wait_gateway(proc):
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"gateway exited: {proc.returncode}")
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/readyz",
                timeout=1,
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("gateway not ready")


def main():
    wait_starrocks()
    setup_data()
    write_runtime_config()

    env = os.environ.copy()
    env["GATEWAY_CONFIG"] = str(HERE / "config.ci.json")
    env["STARROCKS_PASSWORD"] = ""
    env["CI_DASHBOARD_SECRET"] = SECRET

    proc = subprocess.Popen(
        [
            "granian",
            "--interface", "rsgi",
            "--loop", "uvloop",
            "--workers", "1",
            "--runtime-threads", "1",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--log-level", "warning",
            "realtime_gateway.app:app"
        ],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )

    try:
        wait_gateway(proc)

        status, body = get("/api/m000")
        assert status == 200
        assert body["data"][0]["value"] == 0

        status, body = get("/snapshot")
        assert status == 200
        assert len(body["data"]) == 50
        assert "m000" in body["data"]
        assert "m050" not in body["data"]

        try:
            get("/api/m050")
            raise AssertionError("ACL should reject m050")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403

        conn = pymysql.connect(
            host="127.0.0.1",
            port=9030,
            user="root",
            password="",
            database="gateway_ci",
            autocommit=True,
        )
        with conn.cursor() as cur:
            cur.execute("INSERT INTO metric_values VALUES ('m000',999)")
        conn.close()

        time.sleep(1.2)
        _, body = get("/api/m000")
        values = [row["value"] for row in body["data"]]
        assert 999 in values

        print("realtime gateway smoke test: PASS", flush=True)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        for path in [HERE / "config.ci.json", HERE / "users.ci.json"]:
            try:
                path.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    main()
