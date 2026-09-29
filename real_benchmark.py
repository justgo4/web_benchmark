#!/usr/bin/env python3
import json
import os
import pathlib
import re
import signal
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
VENVS = ROOT / ".venvs"
RESULTS_DIR = ROOT / "results"
LOGS = RESULTS_DIR / "real_logs"
URL = "http://127.0.0.1:8000/test"

ROUNDS = int(os.getenv("REAL_BENCH_ROUNDS", "2"))
DURATION = int(os.getenv("REAL_BENCH_DURATION", "4"))
CONNECTIONS = int(os.getenv("REAL_BENCH_CONNECTIONS", "128"))
THREADS = int(os.getenv("REAL_BENCH_THREADS", "2"))

SCENARIOS = [
    {"name": "0ms / 100 rows", "delay_ms": 0, "rows": 100},
    {"name": "5ms / 100 rows", "delay_ms": 5, "rows": 100},
    {"name": "20ms / 100 rows", "delay_ms": 20, "rows": 100},
    {"name": "5ms / 1000 rows", "delay_ms": 5, "rows": 1000},
]

CASES = [
    {"name": "TurboAPI", "slug": "turboapi", "kind": "turboapi", "runner": "direct"},
    {"name": "FastPySGI", "slug": "fastpysgi", "kind": "fastpysgi", "runner": "direct"},
    {"name": "Dreaming Electric Sheep", "slug": "des", "kind": "des", "runner": "des"},
    {"name": "Granian raw RSGI", "slug": "granian_rsgi", "kind": "granian_rsgi", "interface": "rsgi"},
    {"name": "Uvicorn raw ASGI", "slug": "uvicorn_raw", "kind": "raw_asgi", "runner": "uvicorn"},
    {"name": "Jero + Granian", "slug": "jero_granian", "kind": "jero_granian", "interface": "asgi"},
    {"name": "Sanic", "slug": "sanic", "kind": "sanic", "runner": "direct"},
    {"name": "BustAPI", "slug": "bustapi", "kind": "bustapi", "runner": "direct"},
    {"name": "BlackSheep + Granian", "slug": "blacksheep_granian", "kind": "blacksheep_granian", "interface": "asgi"},
    {"name": "Starlette + Granian", "slug": "starlette_granian", "kind": "starlette_granian", "interface": "asgi"},
    {"name": "aiohttp", "slug": "aiohttp", "kind": "aiohttp", "runner": "direct"},
    {"name": "Emmett + Granian", "slug": "emmett_granian", "kind": "emmett_granian", "interface": "rsgi"},
    {"name": "Falcon + Granian", "slug": "falcon_granian", "kind": "falcon_granian", "interface": "asgi"},
    {"name": "Robyn", "slug": "robyn", "kind": "robyn", "runner": "direct"},
    {"name": "Litestar + Granian", "slug": "litestar_granian", "kind": "litestar_granian", "interface": "asgi"},
    {"name": "FastAPI + Granian", "slug": "fastapi_granian", "kind": "fastapi_granian", "interface": "asgi"},
]


def run(cmd, *, env=None, timeout=None, check=True):
    return subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=check,
    )


def stop(proc):
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


def wait_url(url, proc, *, expected_count=None, timeout=20):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"process exited with {proc.returncode}"
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                body = response.read()
                if expected_count is None:
                    return True, ""
                parsed = json.loads(body)
                if parsed.get("code") == 0 and parsed.get("count") == expected_count:
                    return True, ""
                last = body[:500].decode("utf-8", "replace")
        except Exception as exc:
            last = repr(exc)
        time.sleep(0.2)
    return False, last


def install_pyreqwest(py):
    return run(
        ["uv", "pip", "install", "--python", str(py), "--upgrade", "pyreqwest"],
        timeout=300,
    ).stdout


def server_command(case, py):
    bin_dir = py.parent
    runner = case.get("runner")
    if runner == "direct":
        return [str(py), str(ROOT / "real_apps.py")]
    if runner == "uvicorn":
        return [
            str(bin_dir / "uvicorn"),
            "real_apps:app",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--workers", "1",
            "--loop", "uvloop",
            "--no-access-log",
        ]
    if runner == "des":
        return [str(bin_dir / "des"), "run", "real_apps:app", "--workers", "1"]
    return [
        str(bin_dir / "granian"),
        "--interface", case["interface"],
        "--host", "127.0.0.1",
        "--port", "8000",
        "--workers", "1",
        "--runtime-threads", "1",
        "--log-level", "warning",
        "real_apps:app",
    ]


def parse_latency(text, percentile):
    match = re.search(rf"^\s*{percentile}%\s+(\S+)", text, re.MULTILINE)
    return match.group(1) if match else ""


def wrk_round():
    result = run(
        [
            "wrk",
            f"-t{THREADS}",
            f"-c{CONNECTIONS}",
            f"-d{DURATION}s",
            "--latency",
            URL,
        ],
        timeout=DURATION + 15,
    )
    match = re.search(r"Requests/sec:\s+([\d.]+)", result.stdout)
    if not match:
        raise RuntimeError("wrk did not report Requests/sec")
    non2xx = re.search(r"Non-2xx or 3xx responses:\s+(\d+)", result.stdout)
    return {
        "rps": float(match.group(1)),
        "p50": parse_latency(result.stdout, 50),
        "p90": parse_latency(result.stdout, 90),
        "p99": parse_latency(result.stdout, 99),
        "non_2xx": int(non2xx.group(1)) if non2xx else 0,
        "raw": result.stdout,
    }


def benchmark_one(case, scenario):
    row = {
        "name": case["name"],
        "slug": case["slug"],
        "scenario": scenario["name"],
        "delay_ms": scenario["delay_ms"],
        "rows": scenario["rows"],
        "status": "failed",
        "rounds": [],
    }

    py = VENVS / case["slug"] / "bin" / "python"
    if not py.exists():
        row["error"] = "framework venv missing; run benchmark.py first"
        return row

    try:
        install_log = install_pyreqwest(py)
        (LOGS / f"{case['slug']}.pyreqwest.install.log").write_text(
            install_log, encoding="utf-8"
        )
    except Exception as exc:
        row["error"] = f"pyreqwest install failed: {exc}"
        return row

    env = os.environ.copy()
    env["REAL_APP"] = case["kind"]
    env["REAL_ROWS"] = str(scenario["rows"])
    env["REAL_DELAY_MS"] = str(scenario["delay_ms"])
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = f"{py.parent}:{env.get('PATH', '')}"
    if case["slug"] == "turboapi":
        env["TURBO_DISABLE_CACHE"] = "1"

    log_path = LOGS / (
        f"{case['slug']}.{scenario['delay_ms']}ms.{scenario['rows']}rows.log"
    )
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            server_command(case, py),
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            ok, detail = wait_url(URL, proc, expected_count=scenario["rows"])
            if not ok:
                row["error"] = f"server not ready: {detail}"
                return row

            run(["wrk", "-t1", "-c32", "-d1s", URL], timeout=8)

            for idx in range(ROUNDS):
                measured = wrk_round()
                raw = measured.pop("raw")
                raw_path = LOGS / (
                    f"{case['slug']}.{scenario['delay_ms']}ms."
                    f"{scenario['rows']}rows.wrk.{idx + 1}.txt"
                )
                raw_path.write_text(raw, encoding="utf-8")
                row["rounds"].append(measured)

            rps = [x["rps"] for x in row["rounds"]]
            row["median_rps"] = statistics.median(rps)
            row["min_rps"] = min(rps)
            row["max_rps"] = max(rps)
            representative = min(
                row["rounds"],
                key=lambda x: abs(x["rps"] - row["median_rps"]),
            )
            row["p50"] = representative["p50"]
            row["p90"] = representative["p90"]
            row["p99"] = representative["p99"]
            row["non_2xx"] = sum(x["non_2xx"] for x in row["rounds"])
            row["status"] = "ok"
            return row
        except Exception as exc:
            row["error"] = repr(exc)
            return row
        finally:
            stop(proc)


def cpu_model():
    try:
        text_value = run(["lscpu"], timeout=10).stdout
        match = re.search(r"Model name:\s*(.+)", text_value)
        return match.group(1).strip() if match else "unknown"
    except Exception:
        return "unknown"


def write_results(rows):
    RESULTS_DIR.mkdir(exist_ok=True)
    payload = {
        "meta": {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "cpu_model": cpu_model(),
            "logical_cpus": os.cpu_count(),
            "connections": CONNECTIONS,
            "threads": THREADS,
            "rounds": ROUNDS,
            "duration_seconds": DURATION,
            "query": "select id, date from test;",
            "outbound_client": "pyreqwest",
            "mock": (
                "FastPySGI NDJSON upstream on loopback; query delay simulated "
                "uniformly in gateway handler"
            ),
        },
        "results": rows,
    }
    (RESULTS_DIR / "starrocks_latest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# Realistic StarRocks Gateway Benchmark",
        "",
        "Complete path:",
        "wrk -> framework/server -> pyreqwest keep-alive -> StarRocks-style NDJSON -> parse -> JSON API response",
        "",
        "SQL shape: select id, date from test;",
        "",
        (
            "The mock upstream is FastPySGI and returns prebuilt StarRocks-style "
            "NDJSON. The configured 5ms/20ms query delay is applied identically "
            "inside every gateway handler, so the mock itself does not become "
            "the sleeping bottleneck."
        ),
        "",
    ]

    by_scenario = {}
    for row in rows:
        by_scenario.setdefault(row["scenario"], []).append(row)

    for scenario in SCENARIOS:
        name = scenario["name"]
        success = sorted(
            [x for x in by_scenario.get(name, []) if x["status"] == "ok"],
            key=lambda x: x["median_rps"],
            reverse=True,
        )
        lines += [
            f"## {name}",
            "",
            "| Rank | Stack | Median RPS | Range | p50 | p90 | p99 | non-2xx |",
            "|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
        for rank, row in enumerate(success, 1):
            lines.append(
                f"| {rank} | {row['name']} | {row['median_rps']:,.0f} | "
                f"{row['min_rps']:,.0f}-{row['max_rps']:,.0f} | "
                f"{row['p50']} | {row['p90']} | {row['p99']} | "
                f"{row['non_2xx']} |"
            )
        failed = [
            x for x in by_scenario.get(name, []) if x["status"] != "ok"
        ]
        if failed:
            lines.append("")
            lines.append(
                "Failed/incompatible: "
                + "; ".join(
                    f"{x['name']} ({x.get('error', 'unknown')})"
                    for x in failed
                )
            )
        lines.append("")

    score = {}
    for row in rows:
        if row["status"] == "ok":
            score.setdefault(row["name"], []).append(row["median_rps"])
    complete = [
        (name, values)
        for name, values in score.items()
        if len(values) == len(SCENARIOS)
    ]
    complete.sort(
        key=lambda item: statistics.geometric_mean(item[1]),
        reverse=True,
    )

    lines += [
        "## Overall",
        "",
        (
            "Overall score = geometric mean of median RPS across all four "
            "scenarios. Only stacks completing all scenarios are ranked."
        ),
        "",
        "| Rank | Stack | Geometric-mean RPS |",
        "|---:|---|---:|",
    ]
    for rank, (name, values) in enumerate(complete, 1):
        lines.append(
            f"| {rank} | {name} | "
            f"{statistics.geometric_mean(values):,.0f} |"
        )

    if complete:
        lines += [
            "",
            f"Overall winner in this run: {complete[0][0]}.",
            "",
            (
                "Final production verification should still run on the actual "
                "16C/64G API host against the real StarRocks 4.1.1 FE, because "
                "network latency, FE scheduling, Query Cache, result size and "
                "CPU model can change the ordering."
            ),
        ]

    failures = [row for row in rows if row["status"] != "ok"]
    if failures:
        lines += [
            "",
            "## Failures",
            "",
            "| Stack | Scenario | Error |",
            "|---|---|---|",
        ]
        for row in failures:
            err = (
                str(row.get("error", "unknown"))
                .replace("|", "\\|")
                .replace("\n", " ")
            )
            lines.append(
                f"| {row['name']} | {row['scenario']} | {err} |"
            )

    (ROOT / "STARROCKS_BENCHMARK.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main():
    LOGS.mkdir(parents=True, exist_ok=True)

    mock_log_path = LOGS / "mock_starrocks.log"
    with mock_log_path.open("w", encoding="utf-8") as log:
        mock = subprocess.Popen(
            [sys.executable, str(ROOT / "mock_starrocks.py")],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            ok, detail = wait_url(
                "http://127.0.0.1:18030/sql?rows=10",
                mock,
            )
            if not ok:
                raise RuntimeError(
                    f"mock StarRocks failed: {detail}"
                )

            results = []
            for scenario in SCENARIOS:
                for case in CASES:
                    print(
                        f"\n=== {scenario['name']} :: {case['name']} ===",
                        flush=True,
                    )
                    row = benchmark_one(case, scenario)
                    print(json.dumps(row, indent=2), flush=True)
                    results.append(row)

            write_results(results)
        finally:
            stop(mock)


if __name__ == "__main__":
    main()
