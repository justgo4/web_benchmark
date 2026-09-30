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
DELAYS_MS = [2, 5, 10]

BASE_RATE = 4000
BASE_SECONDS = 8
BASE_ROUNDS = 2

HEADROOM_RATES = [6000, 8000]
HEADROOM_SECONDS = 4

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
                if (
                    response.status == 200
                    and body.get("code") == 0
                    and body.get("count") == ROWS
                ):
                    return True, ""
                last = repr(body)
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.2)
    return False, last


def install_case(case):
    import shutil

    path = VENVS / case["slug"]
    if path.exists():
        shutil.rmtree(path)
    subprocess.run([sys.executable, "-m", "venv", str(path)], check=True)
    py = path / "bin" / "python"
    proc = run(
        ["uv", "pip", "install", "--python", str(py), "--upgrade"]
        + case["packages"],
        timeout=600,
    )
    (LOGS / f"{case['slug']}.install.log").write_bytes(
        proc.stdout + proc.stderr
    )
    return py


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
        timeout=seconds + 45,
    )
    if attack.returncode != 0:
        raise RuntimeError(
            attack.stderr.decode("utf-8", "replace")
        )

    report = run(
        ["vegeta", "report", "-type=json"],
        input_bytes=attack.stdout,
        timeout=20,
    )
    if report.returncode != 0:
        raise RuntimeError(
            report.stderr.decode("utf-8", "replace")
        )

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
        "throughput": statistics.median(
            x["throughput"] for x in rounds
        ),
        "success": min(x["success"] for x in rounds),
        "p50_ms": statistics.median(x["p50_ms"] for x in rounds),
        "p95_ms": statistics.median(x["p95_ms"] for x in rounds),
        "p99_ms": statistics.median(x["p99_ms"] for x in rounds),
        "max_ms": max(x["max_ms"] for x in rounds),
    }


def rate_pass(result, target_rate, tolerance=0.975):
    return (
        result["throughput"] >= target_rate * tolerance
        and result["success"] >= 0.999
    )


def benchmark_case(case, py, delay_ms, target_files):
    env = os.environ.copy()
    env["DASHBOARD_APP"] = case["kind"]
    env["DASHBOARD_WORKERS"] = str(WORKERS)
    env["DASHBOARD_ROWS"] = str(ROWS)
    env["DASHBOARD_STARROCKS_URL"] = (
        "http://127.0.0.1:18030/sql"
    )
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
                return {
                    "status": "failed",
                    "error": f"startup/readiness: {detail}",
                }

            base_rounds = []
            for _ in range(BASE_ROUNDS):
                base_rounds.append(
                    vegeta_attack(
                        target_files[BASE_RATE],
                        BASE_RATE,
                        BASE_SECONDS,
                    )
                )
            base = summarize_rounds(base_rounds)

            headroom = {}
            for rate in HEADROOM_RATES:
                try:
                    result = vegeta_attack(
                        target_files[rate],
                        rate,
                        HEADROOM_SECONDS,
                    )
                    result["pass"] = rate_pass(result, rate)
                    headroom[str(rate)] = result
                except Exception as exc:
                    headroom[str(rate)] = {
                        "pass": False,
                        "error": repr(exc),
                    }

            return {
                "status": "ok",
                "base": base,
                "passes_4000_qps": rate_pass(
                    base,
                    BASE_RATE,
                ),
                "base_rounds": base_rounds,
                "headroom": headroom,
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
            raise RuntimeError(
                f"mock exited with {proc.returncode}"
            )
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:18030/sql",
                data=b'{"query":"select 1"}',
                headers={
                    "Content-Type": "application/json"
                },
                method="POST",
            )
            with urllib.request.urlopen(
                req,
                timeout=2,
            ) as response:
                if response.status == 200:
                    return proc, log
        except Exception:
            pass
        time.sleep(0.2)

    stop_process(proc)
    log.close()
    raise RuntimeError("mock did not become ready")


def highest_headroom(result):
    if result["status"] != "ok":
        return 0
    highest = BASE_RATE if result["passes_4000_qps"] else 0
    for rate in HEADROOM_RATES:
        item = result["headroom"].get(str(rate), {})
        if item.get("pass"):
            highest = rate
    return highest


def write_results(rows):
    payload = {
        "workload": {
            "interfaces": 20,
            "qps_per_interface": 200,
            "aggregate_qps": 4000,
            "rows_per_response": ROWS,
            "workers": WORKERS,
            "base_rate": BASE_RATE,
            "base_seconds": BASE_SECONDS,
            "base_rounds": BASE_ROUNDS,
            "headroom_rates": HEADROOM_RATES,
            "headroom_seconds": HEADROOM_SECONDS,
            "starrocks_query_cache": (
                "modeled as repeated endpoint SQL with "
                "2/5/10ms upstream latency"
            ),
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
        "# Dashboard 20-endpoint / 4000-QPS benchmark",
        "",
        "Workload modeled from the target deployment:",
        "",
        "- 20 API endpoints.",
        "- 200 requests/second per endpoint.",
        "- 4,000 aggregate requests/second.",
        "- Every API request performs one StarRocks-style HTTP SQL call.",
        "- Small 10-row dashboard result.",
        "- No local result cache and no singleflight.",
        "- Repeated per-endpoint SQL approximates a hot Query Cache workload.",
        "- 4 application workers on a 4-vCPU GitHub runner.",
        "- Primary test: 4,000 QPS for 8 seconds, repeated twice.",
        "- Headroom tests: 6,000 and 8,000 QPS.",
        "",
    ]

    for delay in DELAYS_MS:
        subset = [
            x for x in rows
            if x["delay_ms"] == delay
        ]

        def sort_key(row):
            result = row["result"]
            if result["status"] != "ok":
                return (-1, -1, -999999)
            return (
                int(result["passes_4000_qps"]),
                highest_headroom(result),
                -result["base"]["p99_ms"],
            )

        subset.sort(key=sort_key, reverse=True)

        lines += [
            f"## Simulated hot StarRocks latency: {delay}ms",
            "",
            "| Rank | Stack | 4k target | Throughput | Success | p95 | p99 | Max stable tested rate |",
            "|---:|---|---|---:|---:|---:|---:|---:|",
        ]

        rank = 0
        for row in subset:
            result = row["result"]
            if result["status"] != "ok":
                continue
            rank += 1
            base = result["base"]
            lines.append(
                f"| {rank} | {row['name']} | "
                f"{'PASS' if result['passes_4000_qps'] else 'FAIL'} | "
                f"{base['throughput']:,.0f} | "
                f"{base['success'] * 100:.3f}% | "
                f"{base['p95_ms']:.2f}ms | "
                f"{base['p99_ms']:.2f}ms | "
                f"{highest_headroom(result):,} QPS |"
            )

        failed = [
            x for x in subset
            if x["result"]["status"] != "ok"
        ]
        if failed:
            lines += [
                "",
                "Failed/incompatible: "
                + "; ".join(
                    f"{x['name']} "
                    f"({x['result'].get('error', 'unknown')})"
                    for x in failed
                ),
            ]
        lines.append("")

    complete = {}
    for row in rows:
        result = row["result"]
        if result["status"] == "ok":
            complete.setdefault(
                row["name"],
                [],
            ).append(result)

    scored = []
    for name, values in complete.items():
        if len(values) != len(DELAYS_MS):
            continue
        pass_count = sum(
            x["passes_4000_qps"] for x in values
        )
        min_headroom = min(
            highest_headroom(x) for x in values
        )
        mean_p99 = statistics.mean(
            x["base"]["p99_ms"] for x in values
        )
        mean_p95 = statistics.mean(
            x["base"]["p95_ms"] for x in values
        )
        scored.append(
            (
                pass_count,
                min_headroom,
                -mean_p99,
                name,
                mean_p95,
                mean_p99,
            )
        )

    scored.sort(reverse=True)

    lines += [
        "## Overall",
        "",
        (
            "Ranking priority: first sustain the required 4,000 QPS "
            "in all latency scenarios, then maximize tested headroom, "
            "then minimize p99."
        ),
        "",
        "| Rank | Stack | 4k scenarios passed | Minimum tested headroom | Mean p95 | Mean p99 |",
        "|---:|---|---:|---:|---:|---:|",
    ]

    for rank, item in enumerate(scored, 1):
        (
            pass_count,
            min_headroom,
            _,
            name,
            mean_p95,
            mean_p99,
        ) = item
        lines.append(
            f"| {rank} | {name} | "
            f"{pass_count}/{len(DELAYS_MS)} | "
            f"{min_headroom:,} QPS | "
            f"{mean_p95:.2f}ms | "
            f"{mean_p99:.2f}ms |"
        )

    if scored:
        lines += [
            "",
            f"Measured winner on this CI workload: **{scored[0][3]}**.",
            "",
            (
                "Use this result to choose the framework. Absolute "
                "production capacity must still be verified on the "
                "actual 16-core API host against the real StarRocks "
                "4.1.1 FE/LB."
            ),
        ]

    (ROOT / "DASHBOARD_BENCHMARK.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main():
    VENVS.mkdir(exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(exist_ok=True)

    target_files = {}
    for rate, seconds in [
        (BASE_RATE, BASE_SECONDS),
        *[(rate, HEADROOM_SECONDS) for rate in HEADROOM_RATES],
    ]:
        path = RESULTS / f"targets_{rate}.txt"
        make_targets(path, rate * seconds)
        target_files[rate] = path

    pythons = {}
    for case in CASES:
        print(f"install {case['name']}", flush=True)
        try:
            pythons[case["slug"]] = install_case(case)
        except Exception as exc:
            print(
                f"install failed {case['name']}: {exc}",
                flush=True,
            )
            pythons[case["slug"]] = None

    rows = []
    for delay in DELAYS_MS:
        print(
            f"\n=== mock StarRocks latency {delay}ms ===",
            flush=True,
        )
        mock, mock_log = start_mock(delay)
        try:
            for case in CASES:
                py = pythons[case["slug"]]
                print(
                    f"--- {case['name']} ---",
                    flush=True,
                )

                if py is None:
                    result = {
                        "status": "failed",
                        "error": "install failed",
                    }
                else:
                    try:
                        result = benchmark_case(
                            case,
                            py,
                            delay,
                            target_files,
                        )
                    except Exception as exc:
                        result = {
                            "status": "failed",
                            "error": repr(exc),
                        }

                row = {
                    "name": case["name"],
                    "slug": case["slug"],
                    "delay_ms": delay,
                    "result": result,
                }
                rows.append(row)
                print(
                    json.dumps(row, indent=2),
                    flush=True,
                )
        finally:
            stop_process(mock)
            mock_log.close()

    write_results(rows)


if __name__ == "__main__":
    main()
