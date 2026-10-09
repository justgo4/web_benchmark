# 本地真实 StarRocks API 压测

## 一条命令测试全部框架（推荐）

在 Linux、Python 3.14 环境，提前安装一次依赖：
```bash
python3.14 -m pip install -r realtime_gateway/local_benchmark/requirements.txt
```

然后运行：
```bash
python3.14 realtime_gateway/local_benchmark/run_all.py
```

第一次询问 StarRocks 地址、数据库、只读用户名和密码；已有 SR_* 环境变量会直接使用。
已有 queries.toml 会直接使用，否则交互录入指标和实际 SELECT；每段 SQL 用单独一行 . 结束。
连接地址和用户名保存在 local.toml；密码不保存，下次输入或使用 SR_PASSWORD 环境变量。
脚本直接使用当前解释器及已安装依赖，不创建 venv、不安装 Python 包、不下载系统库。
缺少依赖会在测试前提示；所有框架使用同一个 Python 3.14 环境。

之后自动检查 SQL、依次启动六种框架、发压、关闭全部子进程、保存结果并输出结论。
默认 1 进程，100/1000/4000 总 QPS，各 20 秒、3 轮，随机交错测试顺序，总发压约 18 分钟加启动时间。
某框架失败会记录日志并继续，不能将失败框架当成胜者。
结果在 results/local_all_时间戳/SUMMARY.md，以及各轮 JSON、服务日志和发压日志。

只测 4000 QPS 或测 4 进程：
```bash
python3.14 realtime_gateway/local_benchmark/run_all.py --qps 4000 --seconds 60 --rounds 3 --workers 4
```

总控默认在 API 服务器本机发压，适合方便复现；发压与服务争抢 CPU 时应另机复测。
自动结论只比较满足成功率/吞吐条件的方案在本次目标 QPS 下的 p99，不声称测出了绝对吞吐极限。

以下是手动运行说明，使用总控脚本无需逐一执行。

Python 3.14，Linux。所有框架使用同一 aiomysql MySQL 协议客户端、同一 SQL、相同连接池上限和 orjson 输出。
测试阵容：BustAPI、Granian RSGI、Sanic、Litestar、Jero + Granian、Robyn。
每个成功指标请求执行一次 SELECT。无 API 缓存、后台快照、singleflight 或鉴权。
StarRocks 自身 Query Cache 保持开启。SELECT 检查不是 SQL 安全沙箱，务必使用只能 SELECT 的账户。
不要直接运行旧 starrocks_protocol_benchmark.py / starrocks_async_benchmark.py：它们是隔离环境测试，包含建库及数据初始化。

## 安装
```bash
git clone https://github.com/justgo4/web_benchmark.git
cd web_benchmark
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r realtime_gateway/local_benchmark/requirements.txt
python -m pip freeze > server-packages.txt
cp realtime_gateway/local_benchmark/queries.example.toml realtime_gateway/local_benchmark/queries.toml
```

编辑 queries.toml，把示例替换成实际大屏 SELECT。一项对应一个 /api/{id}；
20 个接口就填 20 项，100 个就填 100 项。每个框架测试同一份文件。
保留业务实际 SQL；不要为了压测全部改成 SELECT 1。

```bash
export SR_HOST=192.168.1.10
export SR_PORT=9030
export SR_DATABASE=dashboard
export SR_USER=dashboard_readonly
read -rsp 'StarRocks password: ' SR_PASSWORD
echo
export SR_PASSWORD
export SR_POOL_SIZE=32
export SR_MAX_ROWS=1000
export SR_TIMEOUT=5
export BENCH_WORKERS=1
python realtime_gateway/local_benchmark/bench.py check
```

check 打印实际版本、Query Cache 变量和每个查询行数，失败则停止。
预检查直接显示原始异常原因；返回超过默认 1000 行会提示 SR_MAX_ROWS 和实际读取行数。
如果业务确实需要超过 1000 行，可设置 SR_MAX_ROWS；否则建议 SQL 限定实际所需结果。
整个 local_benchmark 文件夹也可单独复制运行，总控会使用同目录的 bench.py。
运行时接口错误返回 502 和异常类型，不把 SQL/密码写入结果。

## 启动 API：每次只运行一种
Granian RSGI：
```bash
BENCH_FRAMEWORK=granian granian --interface rsgi --loop uvloop --workers 1 --runtime-threads 1 --host 0.0.0.0 --port 33335 realtime_gateway.local_benchmark.bench:app
```

Sanic：
```bash
BENCH_FRAMEWORK=sanic python realtime_gateway/local_benchmark/bench.py serve
```

BustAPI 基线：
```bash
BENCH_FRAMEWORK=bustapi python realtime_gateway/local_benchmark/bench.py serve
```

Litestar：
```bash
BENCH_FRAMEWORK=litestar granian --interface asgi --loop uvloop --workers 1 --runtime-threads 1 --host 0.0.0.0 --port 33335 realtime_gateway.local_benchmark.bench:app
```

Jero + Granian（Python >= 3.13，支持这里使用 Python 3.14）：
```bash
BENCH_FRAMEWORK=jero granian --interface asgi --loop uvloop --workers 1 --runtime-threads 1 --host 0.0.0.0 --port 33335 realtime_gateway.local_benchmark.bench:app
```

Robyn：
```bash
BENCH_FRAMEWORK=robyn python realtime_gateway/local_benchmark/bench.py serve --log-level WARNING
```

先测 1 worker，再全部改成 4 worker 重测。Sanic/BustAPI/Robyn 使用 BENCH_WORKERS=4，
Granian CLI 使用 --workers 4。Robyn 映射为 4 processes、每进程 1 worker；
不要用 1 process × 4 threads 冒充 4 进程。总池上限是进程数 × SR_POOL_SIZE；相同轮次所有框架保持一致。
Jero 使用 BytesResponse 和统一 orjson 输出，避免把不同 JSON 编码器速度混入框架排名。
新增框架固定在本次验证版本：jero 0.1.3、robyn 0.88.0。
不要同时运行不同框架争抢同一端口或资源。
框架不支持共享 asyncio 池时会返回 502，预检查会停止，而不是把错误算成高性能。

## 发压
建议第二台服务器作为发压端，同样安装依赖、复制 SQL 配置。load 不需要 StarRocks 密码，
只访问 API。负载脚本应保持 BENCH_FRAMEWORK=granian 默认，不需要随服务端框架修改。
例如 20 接口 × 200 QPS = 4000 总 QPS：

```bash
python realtime_gateway/local_benchmark/bench.py load --url http://API_SERVER:33335 --qps 4000 --seconds 60 --concurrency 512 --label sanic-1w --output results/sanic-1w-4000.json
```

--qps 是所有接口的合计值，轮询均匀分配。先 100、500、1000，再 4000；
每个框架每档重复至少 3 次，随机交换框架测试顺序。更高负载按实际需求增加。
100 指标各 1 次/秒，应设 --qps 100。

程序首先实际调用每个接口检查 HTTP、code、metric 和 data，预热后才计时。
输出成功率、吞吐、响应 p50/p95/p99、包含发压延迟的 scheduled_e2e_p99、
每接口成功/失败/丢弃数量、错误类别。
发压达到 concurrency 上限会记 dropped，不无限积压任务；此时需要检查发压端是否成为瓶颈。
延迟统计包含失败请求，不能只看 p99 忽略成功率。
结果吞吐包含末尾排空时间，成功率分母包括所有计划请求。
versions_on_load_host 是发压机器版本；服务端版本以 server-packages.txt 为准。

胜出标准：同样总 QPS 下达到业务成功率要求（建议至少 99.9%），再比较 p99、
CPU、RSS、StarRocks FE/BE CPU 和 SQL 延迟；最终在实际鉴权/权限代码接入后复测。
本脚本是框架和数据库链路基线，不是完整生产 API。
此工作环境没有用户 StarRocks 连接，不能声称已做真实集群压测。
适配验证环境：CPython 3.13.16。六种方案分别通过 200/200 HTTP 请求及模拟连接池路径检查；
这仅验证路由、异步任务、返回格式和发压计数，不是性能排名，也不验证真实 SQL 延迟。



### 快速诊断失败

先用当前 Python 环境运行：

```bash
python3.14 run_all.py --diagnose
```

这会以总负载 10 QPS、5 秒、1 轮运行六个框架；仍然连接真实 StarRocks，每次请求执行 SELECT。
启动时立即打印日志绝对路径。独立复制 `local_benchmark` 时，结果在其上级的 `results/local_all_时间戳/`。
保留自己的 `local.toml`、`queries.toml`，更新整个测试文件夹的代码，避免新旧脚本混用。

`database-check.log` 包含逐指标查询耗时和 JSON 字节数。502 的错误统计保留错误类型和阶段；
`pool_init` 表示建池，`pool_wait` 表示等待连接，`execute_fetch` 表示执行 SQL 和读取结果。
每个指标的同类错误最多打印三次到 `server.log`，用于诊断，不打印 SQL 或数据库密码。
汇总 p99 只统计成功请求，完整 JSON 仍保留所有已发送请求的延迟和失败数量。
负载按 QPS 从低到高运行，每个档位内打乱框架顺序。

排错时打包结果目录即可，不需要附带连接配置。诊断通过后再运行 `python3.14 run_all.py` 做正式比较。


### 数据库直连基线

`run_all.py` 在每个负载档位、每轮先运行 `database`，再运行六个框架，无需安装新包。
直连基线共用 SQL、aiomysql、单个连接池上限、SR_TIMEOUT 和发压调度，只执行并读取查询，
不经过 HTTP，不序列化每次查询结果，不参与框架胜者排名。默认单 worker 时 API 也使用一个池；
使用多个 worker 时 API 有多个池，不能把两者等同比较。

当前排查请先运行一次 100 QPS：

```bash
python3.14 run_all.py --qps 100 --seconds 20 --rounds 1
```

结果汇总增加 `database` 一行，详细错误在 `database-1w-100qps-r1-load.log` 和对应 JSON。
若直连也失败，检查数据库、驱动、网络和发压进程；若直连正常而 HTTP 失败，重点检查 API 路径。
该对比用于定位，不能单独证明数据库或框架是唯一瓶颈。
