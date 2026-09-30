#!/usr/bin/env python3
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
VENVS = ROOT / ".dashboard_venvs"
RESULTS = ROOT / "results"
LOGS = RESULTS / "dashboard_logs"
URL = "http://127.0.0.1:8000/api/1"
WORKERS = 4
ROWS = 10

STEADY_RATE = 4000
STEADY_SECONDS = 8
STEADY_ROUNDS = 2
BURST_RATE = 20000
BURST_SECONDS = 0.2
BURST_ROUNDS = 2

DELAYS_MS = [2, 5, 10]

CASES = [
    {
        "name": "Flask + Gunicorn gthread",
        "slug": "flask",
        "kind": "flask",
        "packages": ["flask", "gunicorn", "pyreqwest"],
        "runner": "flask",
    },
    {
        "name": "Quart + Granian",
        "slug": "quart",
        "kind": "quart",
        "packages": ["quart", "granian", "pyreqwest"],
        "runner": "granian_asgi",
    },
    {
        "name": "Sanic",
        "slug": "sanic",
        "kind": "sanic",
        "packages": ["sanic", "pyreqwest"],
        "runner": "direct",
    },
    {
        "name": "BustAPI",
        "slug": "bustapi",
        "kind": "bustapi",
        "packages": ["bustapi", "pyreqwest"],
        "runner": "direct",
    },
    {
        "name": "Jero + Granian",
        "slug": "jero",
        "kind": "jero",
        "packages": ["jero", "granian", "msgspec", "pyreqwest"],
        "runner": "granian_asgi",
    },
    {
        "name": "Granian raw RSGI",
        "slug": "granian_rsgi",
        "kind": "granian_rsgi",
        "packages": ["granian", "pyreqwest"],
        "runner": "granian_rsgi",
    },
    {
        "name": "Litestar + Granian",
        "slug": "litestar",
        "kind": "litestar",
        "packages": ["litestar", "granian", "pyreqwest"],
        "runner": "granian_asgi",
    },
    {
        "name": "FastAPI + Granian",
        "slug": "fastapi",
        "kind": "fastapi",
        "packages": ["fastapi", "granian", "pyreqwest"],
        "runner": "granian_asgi",
    },
]


def run(cmd, *, env=None, timeout=None, check=True, input_bytes=None):
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=check,
    )


def install_case(case):
    path = VENVS / case["slug"]
    if path.exists():
        import shutil
        shutil.rmtree(path)
    subprocess.run([sys.executable, "-m", "venv", str(path)], check=True)
    py = path / "bin" / "python"
    proc = run(
        ["uv", "pip", "install", "--python", str(py), "--upgrade"] + case["packages"],
        timeout=600,
    )
    (LOGS / f"{case['slug']}.install.log").write_bytes(proc.stdout + proc.stderr)
    return py


def stop_process(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=8)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass


def wait_ready(proc, timeout=30):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"process exited with {proc.returncode}"
        try:
            with urllib.request.urlopen(URL, timeout=2) as response:
                body = json.loads(response.read())
                if response.status == 200 and body.get("code") == 0 and body.get("count") == ROWS:
                    return True, ""
                last = repr(body)
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.2)
    return False, last


def server_command(case, py):
    bindir = py.parent
    runner = case["runner"]

    if runner == "flask":
        return [
            str(bindir / "gunicorn"),
            "--bind", "127.0.0.1:8000",
            "--workers", str(WORKERS),
            "--worker-class", "gthread",
            "--threads", "32",
            "--keep-alive", "5",
            "--access-logfile", "/dev/null",
            "dashboard_apps:app",
        ]

    if runner == "direct":
        return [str(py), str(ROOT / "dashboard_apps.py")]

    interface = "rsgi" if runner == "granian_rsgi" else "asgi"
    return [
        str(bindir / "granian"),
        "--interface", interface,
        "--host", "127.0.0.1",
        "--port", "8000",
        "--workers", str(WORKERS),
        "--runtime-threads", "1",
        "--log-level", "warning",
        "dashboard_apps:app",
    ]


def make_targets(path, count):
    with path.open("w", encoding="utf-8") as f:
        for i in range(count):
            endpoint = (i % 20) + 1
            f.write(f"GET http://127.0.0.1:8000/api/{endpoint}\n")


def ns_to_ms(value):
    return value / 1_000_000.0


def vegeta_attack(targets, rate, seconds):
    attack = run(
        [
            "vegeta", "attack",
            f"-rate={rate}/s",
            f"-duration={seconds}s",
            "-workers=64",
            "-max-workers=8192",
            f"-targets={targets}",
        ],
        timeout=max(20, int(seconds) + 15),
    )
    if attack.returncode != 0:
        raise RuntimeError(attack.stderr.decode("utf-8", "replace"))

    report = run(
        ["vegeta", "report", "-type=json"],
        input_bytes=attack.stdout,
        timeout=20,
    )
    if report.returncode != 0:
        raise RuntimeError(report.stderr.decode("utf-8", "replace"))

    data = json.loads(report.stdout)
    lat = data["latencies"]
    return {
        "requests": data["requests"],
        "target_rate": rate,
        "throughput": data["throughput"],
        "success": data["success"],
        "p50_ms": ns_to_ms(lat["50th"]),
        "p95_ms": ns_to_ms(lat["95th"]),
        "p99_ms": ns_to_ms(lat["99th"]),
        "max_ms": ns_to_ms(lat["max"]),
        "status_codes": data.get("status_codes", {}),
        "errors": data.get("errors", []),
    }


def summarize_rounds(rounds):
    return {
        "throughput": statistics.median(x["throughput"] for x in rounds),
        "success": min(x["success"] for x in rounds),
        "p50_ms": statistics.median(x["p50_ms"] for x in rounds),
        "p95_ms": statistics.median(x["p95_ms"] for x in rounds),
        "p99_ms": statistics.median(x["p99_ms"] for x in rounds),
        "max_ms": max(x["max_ms"] for x in rounds),
    }


def benchmark_case(case, py, delay_ms, steady_targets, burst_targets):
    env = os.environ.copy()
    env["DASHBOARD_APP"] = case["kind"]
    env["DASHBOARD_WORKERS"] = str(WORKERS)
    env["DASHBOARD_ROWS"] = str(ROWS)
    env["DASHBOARD_STARROCKS_URL"] = "http://127.0.0.1:18030/sql"
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = f"{py.parent}:{env.get('PATH', '')}"

    log_path = LOGS / f"{case['slug']}.{delay_ms}ms.log"
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            server_command(case, py),
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            ok, detail = wait_ready(proc)
            if not ok:
                return {"status": "failed", "error": detail}

            steady_rounds = [
                vegeta_attack(steady_targets, STEADY_RATE, STEADY_SECONDS)
                for _ in range(STEADY_ROUNDS)
            ]
            burst_rounds = [
                vegeta_attack(burst_targets, BURST_RATE, BURST_SECONDS)
                for _ in range(BURST_ROUNDS)
            ]

            steady = summarize_rounds(steady_rounds)
            burst = summarize_rounds(burst_rounds)
            passes_target = (
                steady["throughput"] >= 3900
                and steady["success"] >= 0.999
            )

            return {
                "status": "ok",
                "steady": steady,
                "burst": burst,
                "passes_4000_qps": passes_target,
                "steady_rounds": steady_rounds,
                "burst_rounds": burst_rounds,
            }
        finally:
            stop_process(proc)


def start_mock(delay_ms):
    env = os.environ.copy()
    env["MOCK_QUERY_DELAY_MS"] = str(delay_ms)
    env["MOCK_ROWS"] = str(ROWS)
    env["PYTHONUNBUFFERED"] = "1"
    log_path = LOGS / f"mock.{delay_ms}ms.log"
    log = log_path.open("wb")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "dashboard_mock:app",
            "--host", "127.0.0.1",
            "--port", "18030",
            "--workers", "2",
            "--loop", "uvloop",
            "--no-access-log",
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            log.close()
            raise RuntimeError(f"mock exited with {proc.returncode}")
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:18030/sql",
                data=b'{"query":"select 1"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status == 200:
                    return proc, log
        except Exception:
            pass
        time.sleep(0.2)
    stop_process(proc)
    log.close()
    raise RuntimeError("mock did not become ready")


def write_results(rows):
    payload = {
        "workload": {
            "interfaces": 20,
            "qps_per_interface": 200,
            "aggregate_qps": 4000,
            "rows_per_response": ROWS,
            "workers": WORKERS,
            "steady_seconds": STEADY_SECONDS,
            "burst": "4000 total requests scheduled inside 200ms",
            "starrocks_query_cache": "modeled as repeated per-endpoint query with low upstream latency",
            "local_api_cache": False,
            "singleflight": False,
        },
        "results": rows,
    }
    (RESULTS / "dashboard_latest.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Dashboard workload benchmark",
        "",
        "User workload modeled directly:",
        "",
        "- 20 API endpoints.",
        "- 200 requests/second per endpoint.",
        "- 4,000 aggregate API requests/second worst case.",
        "- Each API request makes one outbound StarRocks-style HTTP SQL request.",
        "- 10-row small dashboard response.",
        "- No API local cache and no singleflight in the ranking.",
        "- StarRocks Query Cache is approximated by repeated per-endpoint SQL and low upstream latency.",
        "- 4 application workers on a 4-vCPU GitHub runner.",
        "- Burst test schedules 4,000 total requests into a 200ms window to approximate synchronized dashboards.",
        "",
    ]

    for delay in DELAYS_MS:
        subset = [x for x in rows if x["delay_ms"] == delay and x["result"]["status"] == "ok"]
        subset.sort(
            key=lambda x: (
                x["result"]["passes_4000_qps"],
                x["result"]["steady"]["success"],
                -x["result"]["steady"]["p99_ms"],
            ),
            reverse=True,
        )
        lines += [
            f"## Simulated cached StarRocks latency: {delay}ms",
            "",
            "| Rank | Stack | 4k target | Throughput | Success | steady p95 | steady p99 | burst p95 | burst p99 |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for rank, row in enumerate(subset, 1):
            result = row["result"]
            steady = result["steady"]
            burst = result["burst"]
            lines.append(
                f"| {rank} | {row['name']} | {'PASS' if result['passes_4000_qps'] else 'FAIL'} | "
                f"{steady['throughput']:,.0f} | {steady['success'] * 100:.3f}% | "
                f"{steady['p95_ms']:.2f}ms | {steady['p99_ms']:.2f}ms | "
                f"{burst['p95_ms']:.2f}ms | {burst['p99_ms']:.2f}ms |"
            )
        failed = [x for x in rows if x["delay_ms"] == delay and x["result"]["status"] != "ok"]
        if failed:
            lines += ["", "Failed: " + "; ".join(
                f"{x['name']} ({x['result'].get('error', 'unknown')})" for x in failed
            )]
        lines.append("")

    eligible = {}
    for row in rows:
        if row["result"]["status"] != "ok":
            continue
        eligible.setdefault(row["name"], []).append(row["result"])

    scored = []
    for name, values in eligible.items():
        if len(values) != len(DELAYS_MS):
            continue
        passes = sum(v["passes_4000_qps"] for v in values)
        avg_p99 = statistics.mean(v["steady"]["p99_ms"] for v in values)
        avg_success = statistics.mean(v["steady"]["success"] for v in values)
        scored.append((passes, avg_success, -avg_p99, name, avg_p99))

    scored.sort(reverse=True)
    lines += [
        "## Overall decision",
        "",
        "Primary score: number of StarRocks latency scenarios that sustain at least 3,900 completed requests/s with >=99.9% success. Ties use success rate and lower steady-state p99.",
        "",
        "| Rank | Stack | Scenarios passing 4k target | Mean steady p99 |",
        "|---:|---|---:|---:|",
    ]
    for rank, item in enumerate(scored, 1):
        passes, _, _, name, avg_p99 = item
        lines.append(f"| {rank} | {name} | {passes}/{len(DELAYS_MS)} | {avg_p99:.2f}ms |")

    if scored:
        lines += [
            "",
            f"Measured winner for this exact 4-vCPU CI workload: **{scored[0][3]}**.",
            "",
            "Production capacity must still be verified on the real 16-core API host against the real StarRocks FE/LB. The CI benchmark is intended to choose the framework, not to predict absolute 16-core capacity.",
        ]

    (ROOT / "DASHBOARD_BENCHMARK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    VENVS.mkdir(exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(exist_ok=True)

    steady_targets = RESULTS / "targets_steady.txt"
    burst_targets = RESULTS / "targets_burst.txt"
    make_targets(steady_targets, STEADY_RATE * STEADY_SECONDS)
    make_targets(burst_targets, int(BURST_RATE * BURST_SECONDS))

    pythons = {}
    for case in CASES:
        print(f"install {case['name']}", flush=True)
        try:
            pythons[case["slug"]] = install_case(case)
        except Exception as exc:
            print(f"install failed {case['name']}: {exc}", flush=True)
            pythons[case["slug"]] = None

    rows = []
    for delay in DELAYS_MS:
        print(f"\n=== mock StarRocks latency {delay}ms ===", flush=True)
        mock, mock_log = start_mock(delay)
        try:
            for case in CASES:
                py = pythons[case["slug"]]
                print(f"--- {case['name']} ---", flush=True)
                if py is None:
                    result = {"status": "failed", "error": "install failed"}
                else:
                    try:
                        result = benchmark_case(
                            case,
                            py,
                            delay,
                            steady_targets,
                            burst_targets,
                        )
                    except Exception as exc:
                        result = {"status": "failed", "error": repr(exc)}
                row = {
                    "name": case["name"],
                    "slug": case["slug"],
                    "delay_ms": delay,
                    "result": result,
                }
                rows.append(row)
                print(json.dumps(row, indent=2), flush=True)
        finally:
            stop_process(mock)
            mock_log.close()

    write_results(rows)


if __name__ == "__main__":
    main()
