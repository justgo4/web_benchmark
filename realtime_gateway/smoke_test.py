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


def wait_mysql():
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
                cur.execute("SELECT 1")
            conn.close()
            return
        except Exception as exc:
            last = exc
        time.sleep(2)
    raise RuntimeError(f"StarRocks MySQL not ready: {last!r}")


def setup_data():
    deadline = time.time() + 120
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
            try:
                with conn.cursor() as cur:
                    cur.execute("DROP DATABASE IF EXISTS gateway_ci FORCE")
                    cur.execute("CREATE DATABASE gateway_ci")
                    cur.execute("USE gateway_ci")
                    for name in ["metric_a", "metric_b", "metric_c"]:
                        cur.execute(
                            f"""
                            CREATE TABLE {name} (
                                value BIGINT NOT NULL
                            )
                            DUPLICATE KEY(value)
                            DISTRIBUTED BY HASH(value) BUCKETS 1
                            PROPERTIES ("replication_num" = "1")
                            """
                        )
                    cur.execute("INSERT INTO metric_a VALUES (10)")
                    cur.execute("INSERT INTO metric_b VALUES (20)")
                    cur.execute("INSERT INTO metric_c VALUES (30)")
                return
            finally:
                conn.close()
        except Exception as exc:
            last = exc
            time.sleep(2)

    raise RuntimeError(f"StarRocks BE not ready for tables: {last!r}")


def write_runtime_config():
    config = {
        "users_file": "users.ci.json",
        "metrics_file": "metrics.ci.json",
        "scheduler_tick_ms": 20,
        "snapshot_rebuild_ms": 20,
        "refresh_concurrency": 2,
        "refresh_timeout_ms": 1500,
        "default_refresh_ms": 500,
        "default_max_stale_ms": 5000,
        "auth_window_seconds": 30,
        "starrocks": {
            "hosts": ["127.0.0.1"],
            "port": 9030,
            "user": "root",
            "password_env": "STARROCKS_PASSWORD",
            "database": "gateway_ci",
            "pool_per_fe": 2
        }
    }
    metrics = {
        "metrics": [
            {
                "id": "m000",
                "sql": "SELECT value FROM metric_a ORDER BY value",
                "refresh_ms": 500
            },
            {
                "id": "m001",
                "sql": "SELECT value FROM metric_b ORDER BY value",
                "refresh_ms": 1000
            },
            {
                "id": "m002",
                "sql": "SELECT value FROM metric_c ORDER BY value",
                "refresh_ms": 5000
            }
        ]
    }
    users = {
        "users": [
            {
                "key": "ci-user",
                "secret_env": "CI_DASHBOARD_SECRET",
                "metrics": ["m000", "m001"]
            }
        ]
    }

    (HERE / "config.ci.json").write_text(json.dumps(config), encoding="utf-8")
    (HERE / "metrics.ci.json").write_text(json.dumps(metrics), encoding="utf-8")
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
        "X-Signature": signature,
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
    wait_mysql()
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
            "realtime_gateway.app:app",
        ],
        cwd=ROOT,
        env=env,
        start_new_session=True,
    )

    try:
        wait_gateway(proc)

        _, body = get("/api/m000")
        assert body["data"][0]["value"] == 10

        _, body = get("/api/m001")
        assert body["data"][0]["value"] == 20

        _, body = get("/snapshot")
        assert set(body["data"]) == {"m000", "m001"}
        assert body["data"]["m000"]["data"][0]["value"] == 10
        assert body["data"]["m001"]["data"][0]["value"] == 20

        try:
            get("/api/m002")
            raise AssertionError("ACL should reject m002")
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
            cur.execute("INSERT INTO metric_a VALUES (999)")
        conn.close()

        time.sleep(1.2)
        _, body = get("/api/m000")
        values = [row["value"] for row in body["data"]]
        assert 999 in values

        print("realtime gateway multi-table smoke test: PASS", flush=True)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

        for name in [
            "config.ci.json",
            "metrics.ci.json",
            "users.ci.json",
        ]:
            try:
                (HERE / name).unlink()
            except Exception:
                pass


if __name__ == "__main__":
    main()
