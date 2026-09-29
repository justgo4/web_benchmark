#!/usr/bin/env python3
import asyncio
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
URL = "http://127.0.0.1:8000/json"
ROUNDS = int(os.getenv("CLIENT_BENCH_ROUNDS", "3"))
DURATION = float(os.getenv("CLIENT_BENCH_DURATION", "6"))
CONCURRENCY = int(os.getenv("CLIENT_BENCH_CONCURRENCY", "128"))
SAMPLE_EVERY = int(os.getenv("CLIENT_BENCH_SAMPLE_EVERY", "64"))


def wait_ready(proc, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"upstream exited with {proc.returncode}")
        try:
            with urllib.request.urlopen(URL, timeout=1) as r:
                if json.loads(r.read()) == {"message": "hello", "value": 123}:
                    return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("upstream did not become ready")


def percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    idx = max(0, min(len(values) - 1, round((pct / 100) * (len(values) - 1))))
    return values[idx]


async def run_load(request_once, seconds, concurrency):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds

    async def worker():
        count = 0
        errors = 0
        samples = []
        while loop.time() < deadline:
            sample = count % SAMPLE_EVERY == 0
            start = time.perf_counter_ns() if sample else 0
            try:
                await request_once()
                count += 1
                if sample:
                    samples.append((time.perf_counter_ns() - start) / 1_000_000)
            except Exception:
                errors += 1
        return count, errors, samples

    start = time.perf_counter()
    rows = await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed = time.perf_counter() - start
    count = sum(r[0] for r in rows)
    errors = sum(r[1] for r in rows)
    samples = [x for r in rows for x in r[2]]
    return {
        "rps": count / elapsed,
        "requests": count,
        "errors": errors,
        "p50_ms": percentile(samples, 50),
        "p90_ms": percentile(samples, 90),
        "p99_ms": percentile(samples, 99),
    }


async def bench_aiohttp():
    import aiohttp

    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY,
        limit_per_host=CONCURRENCY,
        keepalive_timeout=60,
    )
    async with aiohttp.ClientSession(connector=connector) as client:
        async def request_once():
            async with client.get(URL) as response:
                if response.status != 200:
                    raise RuntimeError(response.status)
                await response.read()

        await run_load(request_once, 1.0, min(32, CONCURRENCY))
        return [await run_load(request_once, DURATION, CONCURRENCY) for _ in range(ROUNDS)]


async def bench_httpx():
    import httpx

    limits = httpx.Limits(
        max_connections=CONCURRENCY,
        max_keepalive_connections=CONCURRENCY,
        keepalive_expiry=60,
    )
    async with httpx.AsyncClient(
        http1=True,
        http2=False,
        limits=limits,
        timeout=5.0,
        trust_env=False,
    ) as client:
        async def request_once():
            response = await client.get(URL)
            if response.status_code != 200:
                raise RuntimeError(response.status_code)
            _ = response.content

        await run_load(request_once, 1.0, min(32, CONCURRENCY))
        return [await run_load(request_once, DURATION, CONCURRENCY) for _ in range(ROUNDS)]


async def bench_pyreqwest():
    from pyreqwest.client import ClientBuilder

    client = ClientBuilder().pool_max_idle_per_host(CONCURRENCY).build()
    async with client:
        async def request_once():
            response = await client.get(URL).build().send()
            if response.status != 200:
                raise RuntimeError(response.status)
            await response.bytes()

        await run_load(request_once, 1.0, min(32, CONCURRENCY))
        return [await run_load(request_once, DURATION, CONCURRENCY) for _ in range(ROUNDS)]


async def bench_pyqwest():
    from pyqwest import Client, HTTPTransport

    async with HTTPTransport(pool_max_idle_per_host=CONCURRENCY) as transport:
        client = Client(transport)

        async def request_once():
            response = await client.get(URL)
            if response.status != 200:
                raise RuntimeError(response.status)
            _ = response.content

        await run_load(request_once, 1.0, min(32, CONCURRENCY))
        return [await run_load(request_once, DURATION, CONCURRENCY) for _ in range(ROUNDS)]


CASES = [
    ("aiohttp", "aiohttp", bench_aiohttp),
    ("httpx", "httpx", bench_httpx),
    ("pyreqwest", "pyreqwest", bench_pyreqwest),
    ("pyqwest", "pyqwest", bench_pyqwest),
]


def package_version(package):
    import importlib.metadata as metadata

    try:
        return metadata.version(package)
    except Exception:
        return "unknown"


async def main_async():
    results = []
    for name, package, fn in CASES:
        print(f"\n=== {name} ===", flush=True)
        row = {
            "name": name,
            "version": package_version(package),
            "status": "failed",
            "rounds": [],
        }
        try:
            rounds = await fn()
            row["rounds"] = rounds
            rps = [r["rps"] for r in rounds]
            row["median_rps"] = statistics.median(rps)
            row["min_rps"] = min(rps)
            row["max_rps"] = max(rps)
            middle = min(rounds, key=lambda r: abs(r["rps"] - row["median_rps"]))
            row["p50_ms"] = middle["p50_ms"]
            row["p90_ms"] = middle["p90_ms"]
            row["p99_ms"] = middle["p99_ms"]
            row["errors"] = sum(r["errors"] for r in rounds)
            row["status"] = "ok"
        except Exception as exc:
            row["error"] = repr(exc)
        print(json.dumps(row, indent=2), flush=True)
        results.append(row)
    return results


def write_results(results):
    RESULTS_DIR.mkdir(exist_ok=True)
    good = sorted(
        (r for r in results if r["status"] == "ok"),
        key=lambda r: r["median_rps"],
        reverse=True,
    )
    payload = {
        "meta": {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "python": sys.version,
            "duration_seconds": DURATION,
            "rounds": ROUNDS,
            "concurrency": CONCURRENCY,
            "protocol": "HTTP/1.1 keep-alive",
            "upstream": "FastPySGI local loopback endpoint",
        },
        "results": results,
    }
    (RESULTS_DIR / "client_latest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# Outbound HTTP Client Benchmark",
        "",
        "This benchmark targets the StarRocks-gateway use case: a Python API process making pooled HTTP/1.1 requests to an upstream service.",
        "",
        "## Method",
        "",
        f"- Upstream: local FastPySGI endpoint returning the same small JSON body.",
        f"- Concurrency: {CONCURRENCY} concurrent async workers.",
        f"- Measurement: {ROUNDS} rounds × {DURATION:.0f}s after warmup.",
        "- One long-lived client/pool per library; keep-alive enabled.",
        "- Latency sampling is 1 request per worker per 64 completed requests to reduce measurement overhead.",
        "- Because client and upstream share the same GitHub runner, this is a comparative local proxy benchmark, not an absolute network benchmark.",
        "",
        "## Results",
        "",
        "| Rank | Client | Version | Median RPS | Range | p50 | p90 | p99 | Errors |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for i, r in enumerate(good, 1):
        lines.append(
            f"| {i} | {r['name']} | {r['version']} | {r['median_rps']:,.0f} | "
            f"{r['min_rps']:,.0f}–{r['max_rps']:,.0f} | "
            f"{r['p50_ms']:.3f}ms | {r['p90_ms']:.3f}ms | {r['p99_ms']:.3f}ms | {r['errors']} |"
        )

    failed = [r for r in results if r["status"] != "ok"]
    if failed:
        lines += ["", "## Failed cases", "", "| Client | Error |", "|---|---|"]
        for r in failed:
            lines.append(f"| {r['name']} | {r.get('error', 'unknown').replace('|', '\\|')} |")

    if good:
        lines += [
            "",
            "## Automated observation",
            "",
            f"- Fastest client in this run: **{good[0]['name']}** at ~{good[0]['median_rps']:,.0f} median RPS.",
            "- For the actual StarRocks API gateway, upstream SQL latency will usually dominate this microbenchmark; the main value here is identifying avoidable HTTP-client overhead and connection-pool behavior.",
        ]

    (ROOT / "CLIENT_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    env = os.environ.copy()
    env["BENCH_APP"] = "fastpysgi"
    upstream_log = (RESULTS_DIR / "client_upstream.log")
    RESULTS_DIR.mkdir(exist_ok=True)
    with upstream_log.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "apps.py")],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            wait_ready(proc)
            results = asyncio.run(main_async())
            write_results(results)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
