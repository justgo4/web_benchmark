#!/usr/bin/env python3
"""One-command, real-StarRocks comparison of six Python API stacks."""
import argparse
import getpass
import importlib.metadata
import json
import os
import random
import signal
import socket
import statistics
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FRAMEWORKS = ["bustapi", "granian", "sanic", "litestar", "jero", "robyn"]
MODULE = "realtime_gateway.local_benchmark.bench:app"


def command(python, framework, workers, port):
    base = [str(python)]
    if framework in ("sanic", "bustapi", "robyn"):
        return base + [str(HERE / "bench.py"), "serve", "--log-level", "WARNING"]
    return base + ["-m", "granian", "--interface", "rsgi" if framework == "granian" else "asgi",
                   "--loop", "uvloop", "--workers", str(workers), "--runtime-threads", "1",
                   "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning", MODULE]


def setup_python():
    packages = ["aiomysql", "orjson", "aiohttp", "uvloop", "granian", "sanic",
                "bustapi", "litestar", "jero", "robyn"]
    missing = []
    for package in packages:
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            missing.append(package)
    if missing:
        raise RuntimeError("缺少 Python 包：" + ", ".join(missing)
                           + "。请先用当前解释器 pip install -r realtime_gateway/local_benchmark/requirements.txt")
    return Path(sys.executable)


def setup_config(env):
    saved_file = HERE / "local.toml"
    saved = tomllib.loads(saved_file.read_text()) if saved_file.exists() else {}
    values = {}
    for key, label, default in [
        ("SR_HOST", "StarRocks FE 地址", "127.0.0.1"),
        ("SR_PORT", "MySQL 端口", "9030"),
        ("SR_DATABASE", "数据库", "dashboard"),
        ("SR_USER", "只读用户名", "dashboard_readonly"),
    ]:
        value = env.get(key) or saved.get(key)
        if value is None:
            value = input(f"{label} [{default}]: ").strip() or default
        env[key] = values[key] = str(value)
    saved_file.write_text("\n".join(f"{key} = {json.dumps(value)}" for key, value in values.items()) + "\n")
    if "SR_PASSWORD" not in env:
        env["SR_PASSWORD"] = getpass.getpass("StarRocks 密码（不保存）: ")
    queries = Path(env.get("BENCH_QUERIES", str(HERE / "queries.toml"))).resolve()
    if not queries.exists():
        print("配置实际接口 SQL。已有查询配置时请放在 queries.toml。", flush=True)
        metrics = []
        while True:
            name = input("指标 id（例如 orders；全部录完后留空）: ").strip()
            if not name:
                break
            print("输入该指标 SELECT，可多行；单独输入 . 结束：")
            lines = []
            while True:
                line = input()
                if line == ".":
                    break
                lines.append(line)
            metrics.append((name, "\n".join(lines)))
        if not metrics:
            raise ValueError("至少需要一个实际指标 SQL")
        queries.parent.mkdir(parents=True, exist_ok=True)
        queries.write_text("\n".join("[[metrics]]\nid = " + json.dumps(name)
                          + "\nsql = " + json.dumps(sql) + "\n" for name, sql in metrics))
    env["BENCH_QUERIES"] = str(queries)
    return queries


def stop_process(process):
    # Terminate the entire group, including child framework workers.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def wait_ready(process, port):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("框架进程提前退出，请看对应 server.log")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                if response.status == 200 and json.load(response).get("ok"):
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise RuntimeError("框架 30 秒内未就绪，请看对应 server.log")


def build_summary(cases, rates, rounds):
    lines = ["# 真实 StarRocks API 对比", "",
             "六种框架共用 SQL、aiomysql、连接池上限和 orjson；每次指标调用执行 SELECT。",
             "发压端与 API 同机，结果包含资源竞争；不代表完整生产部署的最大吞吐。",
             "资格：每轮成功率至少 99.9%、吞吐至少目标的 99%、发压端没有丢弃请求，且完成全部轮次。", ""]
    conclusions = []
    for rate in rates:
        lines += [f"## 总负载 {rate} QPS", "",
                  "| 框架 | 完成轮次 | 最低成功率 | 中位吞吐 QPS | 中位 p99 ms | 判定 |",
                  "|---|---:|---:|---:|---:|---|"]
        eligible = []
        for framework in FRAMEWORKS:
            group = [case for case in cases if case["framework"] == framework and case["rate"] == rate]
            results = [case["result"] for case in group if "result" in case]
            if not results:
                lines.append(f"| {framework} | 0/{rounds} | — | — | — | 失败，见日志 |")
                continue
            success = min(r["success_rate"] for r in results)
            throughput = statistics.median(r["achieved_qps_including_drain"] for r in results)
            latencies = [r["response_p99_ms"] for r in results if r["response_p99_ms"] is not None]
            p99 = statistics.median(latencies) if latencies else None
            passed = p99 is not None and len(results) == rounds and all(
                r["success_rate"] >= .999 and r["achieved_qps_including_drain"] >= rate * .99
                and not r["errors"].get("load_generator_concurrency_limit", 0)
                for r in results)
            p99_text = f"{p99:.2f}" if p99 is not None else "—"
            lines.append(f"| {framework} | {len(results)}/{rounds} | {success:.3%} | {throughput:.1f} | {p99_text} | {'通过' if passed else '未通过'} |")
            if passed:
                eligible.append((p99, framework))
        lines.append("")
        if eligible:
            p99, best = min(eligible)
            conclusions.append(f"{rate} QPS：在满足资格的方案中，{best} 的中位 p99 最低（{p99:.2f} ms）。")
        else:
            conclusions.append(f"{rate} QPS：没有方案满足全部资格，无法给出合格胜者。")
    lines += ["## 本次结论", ""] + conclusions
    lines += ["", "这里只比较本次目标负载下的延迟，不据此宣称某框架在所有场景最快。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qps", default="100,1000,4000", help="逗号分隔的总 QPS 档位")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=512)
    args = parser.parse_args()
    rates = sorted(set(int(value) for value in args.qps.split(",")))
    if not rates or min(rates + [args.seconds, args.rounds, args.workers, args.concurrency]) <= 0:
        parser.error("参数必须为正数")
    if sys.version_info < (3, 13) or sys.platform != "linux":
        parser.error("请用 Linux 的 Python 3.13 或更新版本运行")
    os.chdir(ROOT)
    env = dict(os.environ, BENCH_FRAMEWORK="granian", BENCH_BIND="127.0.0.1", BENCH_WORKERS=str(args.workers))
    python = setup_python()
    queries = setup_config(env)
    count = len(tomllib.loads(queries.read_text())["metrics"])
    output = ROOT / "results" / ("local_all_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    output.mkdir(parents=True)
    (output / "server-packages.txt").write_text("\n".join(sorted(
        f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions()
        if dist.metadata.get("Name"))) + "\n")
    print(f"先检查 StarRocks 和 {count} 个实际 SQL…", flush=True)
    with (output / "database-check.log").open("w") as log:
        checked = subprocess.run([str(python), str(HERE / "bench.py"), "check"], env=env,
                                 stdout=log, stderr=log, timeout=max(60, count * 10))
    if checked.returncode:
        raise RuntimeError(f"数据库或 SQL 检查失败，见 {output / 'database-check.log'}")
    cases = []
    plan = [(framework, rate, repeat) for repeat in range(1, args.rounds + 1)
            for rate in rates for framework in FRAMEWORKS]
    random.Random(20261009).shuffle(plan)
    try:
        for index, (framework, rate, repeat) in enumerate(plan, 1):
            label = f"{framework}-{args.workers}w-{rate}qps-r{repeat}"
            print(f"[{index}/{len(plan)}] {label}（每指标约 {rate/count:.1f} QPS）", flush=True)
            # Refuse to interfere with existing services; obtain an unused loopback port.
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            service_env = dict(env, BENCH_FRAMEWORK=framework, BENCH_PORT=str(port))
            case = {"framework": framework, "rate": rate, "round": repeat}
            process = None
            with (output / (label + "-server.log")).open("w") as log:
                try:
                    process = subprocess.Popen(command(python, framework, args.workers, port), env=service_env,
                                               stdout=log, stderr=log, start_new_session=True)
                    wait_ready(process, port)
                    result_file = output / (label + ".json")
                    with (output / (label + "-load.log")).open("w") as load_log:
                        loaded = subprocess.run([str(python), str(HERE / "bench.py"), "load",
                                                 "--url", f"http://127.0.0.1:{port}", "--qps", str(rate),
                                                 "--seconds", str(args.seconds), "--concurrency", str(args.concurrency),
                                                 "--label", label, "--output", str(result_file)],
                                                env=env, stdout=load_log, stderr=load_log,
                                                timeout=args.seconds + 60 + count * 10)
                    if loaded.returncode:
                        raise RuntimeError("接口预检查或发压失败，见 load.log")
                    case["result"] = json.loads(result_file.read_text())
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                    case["error"] = str(error)
                    print("  失败：", error, flush=True)
                finally:
                    if process is not None:
                        stop_process(process)
            cases.append(case)
            (output / "all-results.json").write_text(json.dumps({
                "python": sys.version, "executable": sys.executable,
                "workers": args.workers, "pool_per_process": int(env.get("SR_POOL_SIZE", "32")),
                "metrics": count, "rates": rates, "rounds": args.rounds, "seconds": args.seconds,
                "same_host_load_generator": True, "cases": cases,
            }, ensure_ascii=False, indent=2))
            (output / "SUMMARY.md").write_text(build_summary(cases, rates, args.rounds))
    except KeyboardInterrupt:
        print("已中止，完成的结果已保存。", flush=True)
        return 130
    print("\n" + build_summary(cases, rates, args.rounds), flush=True)
    print(f"完整结果：{output / 'SUMMARY.md'}", flush=True)
    return 0 if all("result" in case for case in cases) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("无法完成测试：", error, file=sys.stderr)
        sys.exit(1)
