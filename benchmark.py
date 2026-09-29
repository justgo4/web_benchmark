#!/usr/bin/env python3
import json
import os
import pathlib
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
VENVS = ROOT / ".venvs"
LOGS = ROOT / "results" / "logs"
RESULTS_DIR = ROOT / "results"
URL = "http://127.0.0.1:8000/json"
ROUNDS = int(os.getenv("BENCH_ROUNDS", "3"))
DURATION = int(os.getenv("BENCH_DURATION", "6"))
CONNECTIONS = int(os.getenv("BENCH_CONNECTIONS", "128"))
THREADS = int(os.getenv("BENCH_THREADS", "2"))

CASES = [
    {
        "name": "Granian raw RSGI",
        "slug": "granian_rsgi",
        "kind": "granian_rsgi",
        "packages": ["granian"],
        "version_package": "granian",
        "category": "server ceiling",
        "interface": "rsgi",
    },
    {
        "name": "Uvicorn raw ASGI",
        "slug": "uvicorn_raw",
        "kind": "raw_asgi",
        "packages": ["uvicorn[standard]"],
        "version_package": "uvicorn",
        "category": "server ceiling",
        "runner": "uvicorn",
    },
    {
        "name": "FastPySGI WSGI",
        "slug": "fastpysgi",
        "kind": "fastpysgi",
        "packages": ["fastpysgi"],
        "version_package": "fastpysgi",
        "category": "server ceiling",
        "runner": "direct",
    },
    {
        "name": "BustAPI",
        "slug": "bustapi",
        "kind": "bustapi",
        "packages": ["bustapi"],
        "version_package": "bustapi",
        "category": "framework",
        "runner": "direct",
    },
    {
        "name": "Falcon + Granian",
        "slug": "falcon_granian",
        "kind": "falcon_granian",
        "packages": ["falcon", "granian"],
        "version_package": "falcon",
        "category": "framework",
        "interface": "asgi",
    },
    {
        "name": "Emmett + Granian",
        "slug": "emmett_granian",
        "kind": "emmett_granian",
        "packages": ["emmett", "granian"],
        "version_package": "emmett",
        "category": "framework",
        "interface": "rsgi",
    },
    {
        "name": "BlackSheep + Granian",
        "slug": "blacksheep_granian",
        "kind": "blacksheep_granian",
        "packages": ["blacksheep", "granian"],
        "version_package": "blacksheep",
        "category": "framework",
        "interface": "asgi",
    },
    {
        "name": "Starlette + Granian",
        "slug": "starlette_granian",
        "kind": "starlette_granian",
        "packages": ["starlette", "granian"],
        "version_package": "starlette",
        "category": "framework",
        "interface": "asgi",
    },
    {
        "name": "Litestar + Granian",
        "slug": "litestar_granian",
        "kind": "litestar_granian",
        "packages": ["litestar", "granian"],
        "version_package": "litestar",
        "category": "framework",
        "interface": "asgi",
    },
    {
        "name": "FastAPI + Granian",
        "slug": "fastapi_granian",
        "kind": "fastapi_granian",
        "packages": ["fastapi", "granian"],
        "version_package": "fastapi",
        "category": "framework",
        "interface": "asgi",
    },
    {
        "name": "Jero + Granian",
        "slug": "jero_granian",
        "kind": "jero_granian",
        "packages": ["jero", "granian", "msgspec"],
        "version_package": "jero",
        "category": "framework",
        "interface": "asgi",
    },
    {
        "name": "Dreaming Electric Sheep",
        "slug": "des",
        "kind": "des",
        "packages": ["dreaming-electric-sheep[standard]"],
        "version_package": "dreaming-electric-sheep",
        "category": "framework",
        "runner": "des",
    },
    {
        "name": "Robyn",
        "slug": "robyn",
        "kind": "robyn",
        "packages": ["robyn"],
        "version_package": "robyn",
        "category": "framework",
        "runner": "direct",
    },
    {
        "name": "Sanic",
        "slug": "sanic",
        "kind": "sanic",
        "packages": ["sanic"],
        "version_package": "sanic",
        "category": "framework",
        "runner": "direct",
    },
    {
        "name": "aiohttp",
        "slug": "aiohttp",
        "kind": "aiohttp",
        "packages": ["aiohttp"],
        "version_package": "aiohttp",
        "category": "framework",
        "runner": "direct",
    },
    {
        "name": "TurboAPI (Python 3.14t)",
        "slug": "turboapi",
        "kind": "turboapi",
        "packages": ["turboapi"],
        "version_package": "turboapi",
        "category": "framework-special-runtime",
        "runner": "direct",
        "python": "3.14t",
    },
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


def make_venv(case):
    path = VENVS / case["slug"]
    if path.exists():
        shutil.rmtree(path)
    python_spec = case.get("python")
    if python_spec:
        r = run(["uv", "venv", "--python", python_spec, "--seed", str(path)], timeout=300)
    else:
        r = run([sys.executable, "-m", "venv", str(path)], timeout=180)
    py = path / "bin" / "python"
    install = ["uv", "pip", "install", "--python", str(py), "--upgrade"] + case["packages"]
    r2 = run(install, timeout=600)
    return py, r.stdout + "\n" + r2.stdout


def package_version(py, package):
    try:
        code = "import importlib.metadata as m;" + f"print(m.version({package!r}))"
        return run([str(py), "-c", code], timeout=20).stdout.strip()
    except Exception:
        return "unknown"


def server_command(case, py):
    vbin = py.parent
    runner = case.get("runner")
    if runner == "direct":
        return [str(py), str(ROOT / "apps.py")]
    if runner == "uvicorn":
        return [
            str(vbin / "uvicorn"),
            "apps:app",
            "--host", "127.0.0.1",
            "--port", "8000",
            "--workers", "1",
            "--loop", "uvloop",
            "--no-access-log",
        ]
    if runner == "des":
        return [str(vbin / "des"), "run", "apps:app", "--workers", "1"]
    interface = case["interface"]
    return [
        str(vbin / "granian"),
        "--interface", interface,
        "--host", "127.0.0.1",
        "--port", "8000",
        "--workers", "1",
        "--runtime-threads", "1",
        "--log-level", "warning",
        "apps:app",
    ]


def wait_ready(proc, timeout=20):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"server exited with {proc.returncode}"
        try:
            with urllib.request.urlopen(URL, timeout=1.0) as r:
                body = r.read()
                last = body.decode("utf-8", "replace")
                data = json.loads(body)
                if data == {"message": "hello", "value": 123}:
                    return True, last
        except Exception as e:
            last = repr(e)
        time.sleep(0.2)
    return False, f"not ready: {last}"


def stop_server(proc):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass


def parse_latency(text, percentile):
    m = re.search(rf"^\s*{percentile}%\s+(\S+)", text, re.MULTILINE)
    return m.group(1) if m else ""


def run_wrk():
    cmd = [
        "wrk",
        f"-t{THREADS}",
        f"-c{CONNECTIONS}",
        f"-d{DURATION}s",
        "--latency",
        URL,
    ]
    r = run(cmd, timeout=DURATION + 15)
    m = re.search(r"Requests/sec:\s+([\d.]+)", r.stdout)
    if not m:
        raise RuntimeError("wrk did not report Requests/sec")
    return {
        "rps": float(m.group(1)),
        "p50": parse_latency(r.stdout, 50),
        "p90": parse_latency(r.stdout, 90),
        "p99": parse_latency(r.stdout, 99),
        "raw": r.stdout,
    }


def benchmark_case(case):
    out = {
        "name": case["name"],
        "slug": case["slug"],
        "category": case["category"],
        "python": case.get("python", f"{sys.version_info.major}.{sys.version_info.minor}"),
        "status": "failed",
        "version": "",
        "rounds": [],
    }
    log_path = LOGS / f"{case['slug']}.log"
    install_path = LOGS / f"{case['slug']}.install.log"

    try:
        py, install_log = make_venv(case)
        install_path.write_text(install_log, encoding="utf-8")
        out["version"] = package_version(py, case["version_package"])
    except Exception as e:
        out["error"] = f"install failed: {e}"
        return out

    env = os.environ.copy()
    env["BENCH_APP"] = case["kind"]
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = f"{py.parent}:{env.get('PATH', '')}"
    if case["slug"] == "turboapi":
        env["TURBO_DISABLE_CACHE"] = "1"
    cmd = server_command(case, py)

    with log_path.open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except Exception as e:
            out["error"] = f"start failed: {e}"
            return out

        try:
            ok, msg = wait_ready(proc)
            if not ok:
                time.sleep(0.5)
                out["error"] = msg
                return out

            run(["wrk", "-t1", "-c32", "-d2s", URL], timeout=10)

            for idx in range(ROUNDS):
                rr = run_wrk()
                raw_path = LOGS / f"{case['slug']}.wrk.{idx + 1}.txt"
                raw_path.write_text(rr.pop("raw"), encoding="utf-8")
                out["rounds"].append(rr)

            rps_values = [r["rps"] for r in out["rounds"]]
            out["median_rps"] = statistics.median(rps_values)
            out["min_rps"] = min(rps_values)
            out["max_rps"] = max(rps_values)
            median_round = min(
                out["rounds"],
                key=lambda r: abs(r["rps"] - out["median_rps"]),
            )
            out["p50"] = median_round["p50"]
            out["p90"] = median_round["p90"]
            out["p99"] = median_round["p99"]
            out["status"] = "ok"
            return out
        except Exception as e:
            out["error"] = f"benchmark failed: {e}"
            return out
        finally:
            stop_server(proc)


def cpu_model():
    try:
        text = run(["lscpu"], timeout=10).stdout
        m = re.search(r"Model name:\s*(.+)", text)
        return m.group(1).strip() if m else "unknown"
    except Exception:
        return "unknown"


def write_results(results):
    successful = sorted(
        [r for r in results if r["status"] == "ok"],
        key=lambda r: r["median_rps"],
        reverse=True,
    )
    common_frameworks = [r for r in successful if r["category"] == "framework"]
    failed = [r for r in results if r["status"] != "ok"]
    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "cpu_model": cpu_model(),
        "logical_cpus": os.cpu_count(),
        "github_runner": os.getenv("RUNNER_NAME", ""),
        "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
        "github_sha": os.getenv("GITHUB_SHA", ""),
        "rounds": ROUNDS,
        "duration_seconds": DURATION,
        "connections": CONNECTIONS,
        "threads": THREADS,
    }
    payload = {"meta": meta, "results": results}
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# Benchmark Results",
        "",
        f"Generated: {meta['timestamp_utc']}",
        "",
        "## Method",
        "",
        f"- Runner CPU: `{meta['cpu_model']}`; logical CPUs visible: `{meta['logical_cpus']}`.",
        f"- Main runtime: CPython `{sys.version_info.major}.{sys.version_info.minor}`. TurboAPI uses its required `3.14t` runtime and is not strictly runtime-identical.",
        '- Endpoint: `GET /json` returning exactly `{"message":"hello","value":123}`.',
        "- One process / one configured worker where the server exposes that control.",
        f"- Load: `wrk`, {THREADS} threads, {CONNECTIONS} keep-alive connections, {DURATION}s × {ROUNDS} measured rounds after warmup.",
        "- Ranking uses median requests/second across measured rounds.",
        "- Native servers may internally use different thread/runtime designs; the table measures the stack as users actually deploy it, not a normalized CPU-cycle cost.",
        "",
        "## Results",
        "",
        "| Rank | Stack | Type | Version | Python | Median RPS | Range | p50 | p90 | p99 |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(successful, 1):
        lines.append(
            f"| {i} | {r['name']} | {r['category']} | {r['version']} | {r['python']} | "
            f"{r['median_rps']:,.0f} | {r['min_rps']:,.0f}–{r['max_rps']:,.0f} | "
            f"{r['p50']} | {r['p90']} | {r['p99']} |"
        )

    lines += ["", "## Automated observations", ""]
    if common_frameworks:
        best = common_frameworks[0]
        lines.append(
            f"- Fastest successful **common-runtime framework** in this run: **{best['name']}** at "
            f"~{best['median_rps']:,.0f} median RPS."
        )
    special = [r for r in successful if r["category"] == "framework-special-runtime"]
    if special:
        s = special[0]
        lines.append(
            f"- Special-runtime result: **{s['name']}** reached ~{s['median_rps']:,.0f} median RPS; "
            "compare cautiously because it uses free-threaded Python 3.14t and a different native threading model."
        )
    ceilings = [r for r in successful if r["category"] == "server ceiling"]
    if ceilings:
        c = ceilings[0]
        lines.append(
            f"- Highest raw server ceiling measured: **{c['name']}** at ~{c['median_rps']:,.0f} median RPS."
        )
    lines.append(
        "- For the StarRocks gateway decision, this JSON hot-path test is a ceiling test. "
        "A proxy workload with connection pooling and an upstream HTTP hop is more representative and should be considered before migrating frameworks."
    )

    if failed:
        lines += ["", "## Failed / incompatible cases", "", "| Stack | Error |", "|---|---|"]
        for r in failed:
            err = str(r.get("error", "unknown")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {r['name']} | {err} |")

    lines += [
        "",
        "## Reproduction",
        "",
        "Run the GitHub Actions workflow `Python HTTP benchmark`, or locally on Linux:",
        "",
        "```bash",
        "sudo apt-get install -y wrk",
        "python -m pip install uv",
        "python benchmark.py",
        "```",
        "",
        "Raw `wrk` outputs and server/install logs are retained under `results/logs/` in the workflow artifact; "
        "`results/latest.json` contains the machine-readable summary.",
        "",
    ]
    (ROOT / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    VENVS.mkdir(exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(exist_ok=True)
    results = []
    for case in CASES:
        print(f"\n=== {case['name']} ===", flush=True)
        result = benchmark_case(case)
        results.append(result)
        print(json.dumps(result, indent=2), flush=True)
    write_results(results)
    if not any(r["status"] == "ok" for r in results):
        raise SystemExit("No benchmark case succeeded")


if __name__ == "__main__":
    main()
