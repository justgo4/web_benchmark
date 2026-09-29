# StarRocks API examples

These examples all expose the same logical endpoint:

```
GET /test
    -> StarRocks HTTP SQL API
    -> select id, date from test;
    -> {"code":0,"data":[{"id":1,"date":"2026-09-30"}],"count":1}
```

StarRocks HTTP SQL returns NDJSON records such as `connectionId`, `meta`, one or more `data` records, and `statistics`.  
`starrocks_common.py` converts the `meta` column names plus each `data` array into dictionaries.

Environment:

```bash
export STARROCKS_URL='http://fe:8030/api/v1/catalogs/default_catalog/databases/test/sql'
export STARROCKS_USER='api_user'
export STARROCKS_PASSWORD='secret'
```

The examples intentionally reuse one long-lived HTTP client/pool instead of creating a client for every request.

---

## 1. BustAPI + pyreqwest

```python
from bustapi import BustAPI

from starrocks_common import query_test_async

app = BustAPI()


@app.route("/test")
async def test():
    return await query_test_async()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
```

This is the closest version to the current production direction if BustAPI is retained.

---

## 2. TurboAPI + pyreqwest

```python
from turboapi import TurboAPI

from starrocks_common import query_test_async

app = TurboAPI()


@app.get("/test")
async def test():
    return await query_test_async()


if __name__ == "__main__":
    app.run()
```

The application code is extremely small. The current benchmark showed the highest inbound RPS, but one previous GitHub runner exited with SIGILL, so production CPU/runtime compatibility still needs verification.

---

## 3. Dreaming Electric Sheep + pyreqwest

The benchmarked DES route style is synchronous, so this minimal example uses the synchronous pooled pyreqwest client:

```python
from des import Application, get

from starrocks_common import query_test_sync

app = Application()


@get("/test")
def test():
    return query_test_sync()
```

For a gateway dominated by remote StarRocks I/O, verify DES concurrency under blocking upstream calls before choosing this form for production.

---

## 4. Granian raw RSGI + pyreqwest

This removes a normal web framework layer.

```python
from starrocks_common import json_bytes, query_test_async


async def app(scope, proto):
    if scope.path != "/test":
        proto.response_bytes(
            status=404,
            headers=[("content-length", "0")],
            body=b"",
        )
        return

    result = await query_test_async()
    body = json_bytes(result)

    proto.response_bytes(
        status=200,
        headers=[
            ("content-type", "application/json; charset=utf-8"),
            ("content-length", str(len(body))),
        ],
        body=body,
    )
```

Run:

```bash
granian --interface rsgi --host 0.0.0.0 --port 8000 app:app
```

For a deliberately thin authentication/query gateway, this is one of the most interesting designs because there is very little Python framework machinery between the client and StarRocks.

---

## 5. Jero + Granian + pyreqwest

```python
from jero import BaseApp, Resource
from msgspec import Struct

from starrocks_common import query_test_async


class Row(Struct):
    id: int
    date: str


class Result(Struct):
    code: int
    data: list[Row]
    count: int


class TestResource(Resource, path="/test"):
    async def read_many(self) -> Result:
        result = await query_test_async()
        rows = [Row(id=row["id"], date=row["date"]) for row in result["data"]]
        return Result(code=0, data=rows, count=len(rows))


class App(BaseApp):
    async def wire(self) -> None:
        self._include_resource(TestResource())


app = App()
```

Run with Granian using the same deployment pattern as the benchmark.

---

## 6. Sanic + pyreqwest

```python
from sanic import Sanic
from sanic.response import json

from starrocks_common import query_test_async

app = Sanic("starrocks_gateway")


@app.get("/test")
async def test(request):
    return json(await query_test_async())


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
        single_process=True,
        access_log=False,
        motd=False,
    )
```

---

## 7. FastPySGI + pyreqwest

FastPySGI is a WSGI-style server, so this example uses the synchronous pool.

```python
import fastpysgi

from starrocks_common import json_bytes, query_test_sync


def app(environ, start_response):
    if environ.get("PATH_INFO") != "/test":
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]

    body = json_bytes(query_test_sync())

    start_response(
        "200 OK",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


if __name__ == "__main__":
    fastpysgi.run(app, host="0.0.0.0", port=8000)
```

The raw JSON benchmark showed an extremely high server ceiling, but synchronous upstream I/O changes the effective concurrency model substantially.

---

## 8. FastAPI + Granian + pyreqwest

Included as a familiar reference point.

```python
from fastapi import FastAPI

from starrocks_common import query_test_async

app = FastAPI()


@app.get("/test")
async def test():
    return await query_test_async()
```

Run:

```bash
granian --interface asgi --host 0.0.0.0 --port 8000 app:app
```

---

# Outbound-client-only comparison

The web framework is only the inbound half. These four snippets show the same StarRocks request using each tested HTTP client.

## pyreqwest

```python
from pyreqwest.client import ClientBuilder

client = ClientBuilder().pool_max_idle_per_host(256).build()

response = await (
    client
    .post(STARROCKS_URL)
    .basic_auth(USER, PASSWORD)
    .body_json({"query": "select id, date from test;"})
    .build()
    .send()
)

text = await response.text()
```

Latest benchmark: fastest of the four outbound clients tested.

## aiohttp

```python
import aiohttp

connector = aiohttp.TCPConnector(
    limit=256,
    limit_per_host=256,
    keepalive_timeout=60,
)
session = aiohttp.ClientSession(connector=connector)

async with session.post(
    STARROCKS_URL,
    auth=aiohttp.BasicAuth(USER, PASSWORD),
    json={"query": "select id, date from test;"},
) as response:
    response.raise_for_status()
    text = await response.text()
```

## pyqwest

```python
from pyqwest import Client, HTTPTransport

transport = HTTPTransport(pool_max_idle_per_host=256)
client = Client(transport)

response = await client.post(
    STARROCKS_URL,
    headers={"Authorization": BASIC_AUTH},
    content=b'{"query":"select id, date from test;"}',
)
text = response.text
```

Check the exact response/body convenience API against the installed pyqwest version before using this snippet unchanged; the benchmark code in this repository is the authoritative tested usage for version 0.11.0.

## httpx

```python
import httpx

client = httpx.AsyncClient(
    limits=httpx.Limits(
        max_connections=256,
        max_keepalive_connections=256,
    ),
    timeout=5.0,
)

response = await client.post(
    STARROCKS_URL,
    auth=(USER, PASSWORD),
    json={"query": "select id, date from test;"},
)
response.raise_for_status()
text = response.text
```

In the local high-concurrency proxy microbenchmark, HTTPX was dramatically slower than the other three clients.

---

# What should be benchmarked next

The next benchmark should no longer return a constant JSON object. It should run this exact path:

```
wrk/client
  -> framework route
  -> optional auth
  -> optional local cache
  -> optional singleflight
  -> pyreqwest/aiohttp connection pool
  -> real StarRocks 4.1.1 FE HTTP SQL API
  -> select id, date from test
  -> parse NDJSON
  -> serialize API JSON
  -> client
```

That benchmark will tell us much more than the current hello-JSON ceiling test about which framework is actually best for the production gateway.
