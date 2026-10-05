#!/usr/bin/env python3
import hmac
import json
import os
import pathlib
import signal
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
RESULTS = ROOT / "results"
LOGS = RESULTS / "snapshot_gateway_logs"
URL = "http://127.0.0.1:8000"

METRIC_RATES = [1000, 5000, 10000, 20000]
METRIC_SECONDS = 4
BATCH_RATES = [100, 1000, 5000]
BATCH_SECONDS = 3

USERS = {
    "u0": b"secret-0-0123456789abcdef",
    "u1": b"secret-1-0123456789abcdef",
    "u2": b"secret-2-0123456789abcdef",
    "u3": b"secret-3-0123456789abcdef",
}

CASES = [
    {
        "name": "FastPySGI WSGI",
        "kind": "fastpysgi",
        "command": lambda: [sys.executable, str(ROOT / "snapshot_gateway_apps.py")],
    },
    {
        "name": "Granian RSGI + uvloop",
        "kind": "granian_rsgi",
        "command": lambda: [
            "granian", "--interface", "rsgi", "--loop", "uvloop",
            "--workers", "1", "--runtime-threads", "1",
            "--log-level", "warning", "snapshot_gateway_apps:app",
        ],
    },
    {
        "name": "Granian RSGI + rloop",
        "kind": "granian_rsgi",
        "command": lambda: [
            "granian", "--interface", "rsgi", "--loop", "rloop",
            "--workers", "1", "--runtime-threads", "1",
            "--log-level", "warning", "snapshot_gateway_apps:app",
        ],
    },
    {
        "name": "Granian RSGI + asyncio",
        "kind": "granian_rsgi",
        "command": lambda: [
            "granian", "--interface", "rsgi", "--loop", "asyncio",
            "--workers", "1", "--runtime-threads", "1",
            "--log-level", "warning", "snapshot_gateway_apps:app",
        ],
    },
    {
        "name": "Granian raw ASGI + uvloop",
        "kind": "granian_asgi",
        "command": lambda: [
            "granian", "--interface", "asgi", "--loop", "uvloop",
            "--workers", "1", "--runtime-threads", "1",
            "--log-level", "warning", "snapshot_gateway_apps:app",
        ],
    },
    {
        "name": "Sanic raw-bytes",
        "kind": "sanic",
        "command": lambda: [sys.executable, str(ROOT / "snapshot_gateway_apps.py")],
    },
]


def ns_to_ms(value):
    return value / 1_000_000.0


def stop_process(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass


def signature(key, path, ts):
    return hmac.digest(
        USERS[key],
        ("GET\n" + path + "\n" + ts).encode(),
        "sha256",
    ).hex()


def key_for_metric(metric):
    return f"u{metric // 25}"


def write_metric_targets(path, requests):
    ts = str(int(time.time()))
    with path.open("w", encoding="utf-8") as f:
        for i in range(requests):
            metric = i % 100
            key = key_for_metric(metric)
            route = f"/api/{metric}"
            sig = signature(key, route, ts)
            f.write(f"GET {URL}{route}\n")
            f.write(f"X-Api-Key: {key}\n")
            f.write(f"X-Timestamp: {ts}\n")
            f.write(f"X-Signature: {sig}\n\n")


def write_batch_targets(path, requests):
    ts = str(int(time.time()))
    with path.open("w", encoding="utf-8") as f:
        for i in range(requests):
            key = f"u{i % 4}"
            route = "/snapshot"
            sig = signature(key, route, ts)
            f.write(f"GET {URL}{route}\n")
            f.write(f"X-Api-Key: {key}\n")
            f.write(f"X-Timestamp: {ts}\n")
            f.write(f"X-Signature: {sig}\n\n")


def vegeta(path, rate, seconds):
    attack = subprocess.run(
        [
            "vegeta", "attack",
            f"-rate={rate}/s",
            f"-duration={seconds}s",
            "-workers=64",
            "-max-workers=8192",
            f"-targets={path}",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=seconds + 30,
    )
    if attack.returncode != 0:
        raise RuntimeError(attack.stderr.decode("utf-8", "replace"))
    report = subprocess.run(
        ["vegeta", "report", "-type=json"],
        cwd=ROOT,
        input=attack.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    data = json.loads(report.stdout)
    lat = data["latencies"]
    return {
        "rate": rate,
        "throughput": data["throughput"],
        "success": data["success"],
        "p50_ms": ns_to_ms(lat["50th"]),
        "p95_ms": ns_to_ms(lat["95th"]),
        "p99_ms": ns_to_ms(lat["99th"]),
        "max_ms": ns_to_ms(lat["max"]),
        "status_codes": data.get("status_codes", {}),
        "errors": data.get("errors", []),
    }


def wait_ready(proc):
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        ts = str(int(time.time()))
        route = "/api/0"
        sig = signature("u0", route, ts)
        req = urllib.request.Request(
            URL + route,
            headers={
                "X-Api-Key": "u0",
                "X-Timestamp": ts,
                "X-Signature": sig,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=1) as response:
                if response.status == 200 and b'"metric":0' in response.read():
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def run_case(case):
    env = os.environ.copy()
    env["SNAPSHOT_APP"] = case["kind"]
    env["PYTHONUNBUFFERED"] = "1"
    slug = case["name"].lower().replace(" ", "_").replace("+", "plus")
    with (LOGS / f"{slug}.log").open("wb") as log:
        proc = subprocess.Popen(
            case["command"](),
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            if not wait_ready(proc):
                return {"status": "failed", "error": "readiness failed"}

            metric = []
            for rate in METRIC_RATES:
                target = RESULTS / f"snapshot_metric_{rate}.targets"
                write_metric_targets(target, rate * METRIC_SECONDS)
                metric.append(vegeta(target, rate, METRIC_SECONDS))
                time.sleep(0.5)

            batch = []
            for rate in BATCH_RATES:
                target = RESULTS / f"snapshot_batch_{rate}.targets"
                write_batch_targets(target, rate * BATCH_SECONDS)
                batch.append(vegeta(target, rate, BATCH_SECONDS))
                time.sleep(0.5)

            return {"status": "ok", "metric": metric, "batch": batch}
        finally:
            stop_process(proc)


def best_stable(loads):
    best = 0
    for row in loads:
        if row["success"] >= 0.999 and row["throughput"] >= row["rate"] * 0.975:
            best = row["rate"]
    return best


def write_report(rows):
    RESULTS.mkdir(exist_ok=True)
    payload = {
        "workload": {
            "metrics": 100,
            "refresh_interval_s": 1,
            "auth": "HMAC-SHA256 + timestamp + ACL bitset",
            "response": "pre-serialized immutable JSON bytes",
            "starrocks_query_per_request": False,
            "metric_rates": METRIC_RATES,
            "batch_rates": BATCH_RATES,
        },
        "results": rows,
    }
    (RESULTS / "snapshot_gateway_latest.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Snapshot gateway benchmark",
        "",
        "The request hot path performs no StarRocks query.",
        "",
        "- 100 metric endpoints.",
        "- Immutable snapshot is rebuilt once per second.",
        "- JSON is serialized during refresh, not per request.",
        "- Every request verifies HMAC-SHA256, timestamp window, and a per-user ACL bitset.",
        "- Four users have disjoint 25-metric permissions.",
        "- /api/{metric} serves one metric.",
        "- /snapshot serves all metrics visible to the authenticated user in one response.",
        "- One server process/worker on a 4-vCPU GitHub runner; load generator shares the same runner.",
        "",
        "## Individual metric endpoint",
        "",
        "| Stack | Max stable tested QPS | 1k p99 | 5k p99 | 10k p99 | 20k p99 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    good = [x for x in rows if x["result"]["status"] == "ok"]
    good.sort(
        key=lambda x: (
            best_stable(x["result"]["metric"]),
            -statistics.mean(y["p99_ms"] for y in x["result"]["metric"]),
        ),
        reverse=True,
    )
    for row in good:
        by_rate = {x["rate"]: x for x in row["result"]["metric"]}
        lines.append(
            f"| {row['name']} | {best_stable(row['result']['metric']):,} | "
            f"{by_rate[1000]['p99_ms']:.2f} ms | "
            f"{by_rate[5000]['p99_ms']:.2f} ms | "
            f"{by_rate[10000]['p99_ms']:.2f} ms | "
            f"{by_rate[20000]['p99_ms']:.2f} ms |"
        )

    lines += [
        "",
        "## Batch snapshot endpoint",
        "",
        "| Stack | Max stable tested QPS | 100 p99 | 1k p99 | 5k p99 |",
        "|---|---:|---:|---:|---:|",
    ]
    good_batch = sorted(
        good,
        key=lambda x: (
            best_stable(x["result"]["batch"]),
            -statistics.mean(y["p99_ms"] for y in x["result"]["batch"]),
        ),
        reverse=True,
    )
    for row in good_batch:
        by_rate = {x["rate"]: x for x in row["result"]["batch"]}
        lines.append(
            f"| {row['name']} | {best_stable(row['result']['batch']):,} | "
            f"{by_rate[100]['p99_ms']:.2f} ms | "
            f"{by_rate[1000]['p99_ms']:.2f} ms | "
            f"{by_rate[5000]['p99_ms']:.2f} ms |"
        )

    failed = [x for x in rows if x["result"]["status"] != "ok"]
    if failed:
        lines += ["", "## Failed cases", ""]
        for row in failed:
            lines.append(f"- {row['name']}: {row['result'].get('error', 'unknown')}")

    lines += [
        "",
        "## Interpretation",
        "",
        "- This measures the proposed production request path: authentication, authorization, memory lookup, and raw-byte response.",
        "- StarRocks load is controlled by the refresh scheduler, so downstream user count does not multiply StarRocks QPS.",
        "- If the dashboard can use /snapshot, 100 per-metric calls per second become one call per second per user.",
        "",
    ]
    (ROOT / "SNAPSHOT_GATEWAY_BENCHMARK.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    print("\n".join(lines), flush=True)


def main():
    RESULTS.mkdir(exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    rows = []
    for case in CASES:
        print(f"=== {case['name']} ===", flush=True)
        try:
            result = run_case(case)
        except Exception as exc:
            result = {"status": "failed", "error": repr(exc)}
        row = {"name": case["name"], "kind": case["kind"], "result": result}
        rows.append(row)
        print(json.dumps(row, indent=2), flush=True)
    write_report(rows)


if __name__ == "__main__":
    main()
