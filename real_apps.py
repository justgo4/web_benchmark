import asyncio
import json
import os
import time

from pyreqwest.client import ClientBuilder, SyncClientBuilder

KIND = os.environ["REAL_APP"]
ROWS = os.getenv("REAL_ROWS", "100")
DELAY_MS = float(os.getenv("REAL_DELAY_MS", "5"))
UPSTREAM = f"http://127.0.0.1:18030/sql?rows={ROWS}"
SQL = "select id, date from test;"

_async_client = (
    ClientBuilder()
    .pool_max_idle_per_host(256)
    .error_for_status(True)
    .build()
)
_sync_client = (
    SyncClientBuilder()
    .pool_max_idle_per_host(256)
    .error_for_status(True)
    .build()
)


def parse_starrocks(text):
    columns = None
    rows = []
    for line in text.splitlines():
        if not line:
            continue
        item = json.loads(line)
        if "meta" in item:
            columns = [x["name"] for x in item["meta"]]
        elif "data" in item:
            rows.append(dict(zip(columns, item["data"])))
    return {"code": 0, "data": rows, "count": len(rows)}


async def query_async():
    response = await (
        _async_client
        .post(UPSTREAM)
        .body_json({"query": SQL})
        .build()
        .send()
    )
    text = await response.text()
    if DELAY_MS:
        await asyncio.sleep(DELAY_MS / 1000)
    return parse_starrocks(text)


def query_sync():
    response = (
        _sync_client
        .post(UPSTREAM)
        .body_json({"query": SQL})
        .build()
        .send()
    )
    text = response.text()
    if DELAY_MS:
        time.sleep(DELAY_MS / 1000)
    return parse_starrocks(text)


def encoded(result):
    return json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


if KIND == "bustapi":
    from bustapi import BustAPI

    app = BustAPI()

    @app.route("/test")
    async def test():
        return await query_async()

    if __name__ == "__main__":
        app.run(host="127.0.0.1", port=8000, workers=1, debug=False)


elif KIND == "turboapi":
    from turboapi import TurboAPI

    app = TurboAPI()

    @app.get("/test")
    async def test():
        return await query_async()

    if __name__ == "__main__":
        app.run()


elif KIND == "granian_rsgi":
    async def app(scope, proto):
        if scope.path != "/test":
            proto.response_bytes(404, [("content-length", "0")], b"")
            return
        body = encoded(await query_async())
        proto.response_bytes(
            200,
            [
                ("content-type", "application/json; charset=utf-8"),
                ("content-length", str(len(body))),
            ],
            body,
        )


elif KIND == "raw_asgi":
    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        if scope["path"] != "/test":
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        body = encoded(await query_async())
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})


elif KIND == "falcon_granian":
    import falcon.asgi

    class TestResource:
        async def on_get(self, req, resp):
            resp.media = await query_async()

    app = falcon.asgi.App()
    app.add_route("/test", TestResource())


elif KIND == "emmett_granian":
    from emmett import App
    from emmett.tools import service

    app = App(__name__)

    @app.route("/test", methods="get")
    @service.json
    async def test():
        return await query_async()


elif KIND == "blacksheep_granian":
    from blacksheep import Application, json as bs_json

    app = Application()

    @app.router.get("/test")
    async def test():
        return bs_json(await query_async())


elif KIND == "starlette_granian":
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def test(request):
        return JSONResponse(await query_async())

    app = Starlette(routes=[Route("/test", test)])


elif KIND == "litestar_granian":
    from litestar import Litestar, get

    @get("/test", sync_to_thread=False)
    async def test() -> dict[str, object]:
        return await query_async()

    app = Litestar(route_handlers=[test])


elif KIND == "fastapi_granian":
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/test")
    async def test():
        return await query_async()


elif KIND == "jero_granian":
    from msgspec import Struct
    from jero import BaseApp, Resource

    class Result(Struct):
        code: int
        data: list[dict]
        count: int

    class TestResource(Resource, path="/test"):
        async def read_many(self) -> Result:
            value = await query_async()
            return Result(
                code=value["code"],
                data=value["data"],
                count=value["count"],
            )

    class App(BaseApp):
        async def wire(self) -> None:
            self._include_resource(TestResource())

    app = App()


elif KIND == "des":
    from des import Application, get

    app = Application()

    @get("/test")
    def test():
        return query_sync()


elif KIND == "robyn":
    from robyn import Robyn

    app = Robyn(__file__)

    @app.get("/test")
    async def test(request):
        return json.dumps(await query_async(), separators=(",", ":"))

    if __name__ == "__main__":
        app.start(host="127.0.0.1", port=8000)


elif KIND == "sanic":
    from sanic import Sanic
    from sanic.response import json as sanic_json

    app = Sanic("real_bench")

    @app.get("/test")
    async def test(request):
        return sanic_json(await query_async())

    if __name__ == "__main__":
        app.run(
            host="127.0.0.1",
            port=8000,
            single_process=True,
            access_log=False,
            motd=False,
        )


elif KIND == "aiohttp":
    from aiohttp import web

    async def test(request):
        return web.json_response(await query_async())

    app = web.Application()
    app.router.add_get("/test", test)

    if __name__ == "__main__":
        web.run_app(app, host="127.0.0.1", port=8000, access_log=None)


elif KIND == "fastpysgi":
    import fastpysgi

    def app(environ, start_response):
        if environ.get("PATH_INFO") != "/test":
            start_response("404 Not Found", [("Content-Length", "0")])
            return [b""]
        body = encoded(query_sync())
        start_response(
            "200 OK",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    if __name__ == "__main__":
        fastpysgi.run(app, host="127.0.0.1", port=8000)


else:
    raise RuntimeError(f"unknown REAL_APP={KIND}")
