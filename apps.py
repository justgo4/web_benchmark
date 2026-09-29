import os

KIND = os.environ["BENCH_APP"]
PAYLOAD = {"message": "hello", "value": 123}
PAYLOAD_BYTES = b'{"message":"hello","value":123}'
PAYLOAD_TEXT = '{"message":"hello","value":123}'


if KIND == "bustapi":
    from bustapi import BustAPI

    app = BustAPI()

    @app.route("/json")
    def json_endpoint():
        return PAYLOAD

    if __name__ == "__main__":
        app.run(host="127.0.0.1", port=8000, workers=1, debug=False)


elif KIND == "turboapi":
    from turboapi import TurboAPI

    app = TurboAPI()

    @app.get("/json")
    def json_endpoint():
        return PAYLOAD

    if __name__ == "__main__":
        app.run()


elif KIND == "granian_rsgi":
    async def app(scope, proto):
        if scope.path == "/json":
            proto.response_bytes(
                status=200,
                headers=[("content-type", "application/json")],
                body=PAYLOAD_BYTES,
            )
        else:
            proto.response_bytes(status=404, headers=[], body=b"")


elif KIND == "raw_asgi":
    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        status = 200 if scope["path"] == "/json" else 404
        body = PAYLOAD_BYTES if status == 200 else b""
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})


elif KIND == "falcon_granian":
    import falcon.asgi

    class JsonResource:
        async def on_get(self, req, resp):
            resp.media = PAYLOAD

    app = falcon.asgi.App()
    app.add_route("/json", JsonResource())


elif KIND == "emmett_granian":
    from emmett import App
    from emmett.tools import service

    app = App(__name__)

    @app.route("/json", methods="get")
    @service.json
    async def json_endpoint():
        return PAYLOAD


elif KIND == "blacksheep_granian":
    from blacksheep import Application, json

    app = Application()

    @app.router.get("/json")
    async def json_endpoint():
        return json(PAYLOAD)


elif KIND == "starlette_granian":
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def json_endpoint(request):
        return JSONResponse(PAYLOAD)

    app = Starlette(routes=[Route("/json", json_endpoint)])


elif KIND == "litestar_granian":
    from litestar import Litestar, get

    @get("/json", sync_to_thread=False)
    async def json_endpoint() -> dict[str, object]:
        return PAYLOAD

    app = Litestar(route_handlers=[json_endpoint])


elif KIND == "fastapi_granian":
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/json")
    async def json_endpoint():
        return PAYLOAD


elif KIND == "jero_granian":
    from msgspec import Struct
    from jero import BaseApp, Resource

    class Payload(Struct):
        message: str
        value: int

    class JsonResource(Resource, path="/json"):
        async def read_many(self) -> Payload:
            return Payload(message="hello", value=123)

    class App(BaseApp):
        async def wire(self) -> None:
            self._include_resource(JsonResource())

    app = App()


elif KIND == "des":
    from des import Application, get

    app = Application()

    @get("/json")
    def json_endpoint():
        return PAYLOAD


elif KIND == "robyn":
    from robyn import Robyn

    app = Robyn(__file__)

    @app.get("/json")
    async def json_endpoint(request):
        return PAYLOAD_TEXT

    if __name__ == "__main__":
        app.start(url="127.0.0.1", port=8000)


elif KIND == "sanic":
    from sanic import Sanic
    from sanic.response import json

    app = Sanic("bench")

    @app.get("/json")
    async def json_endpoint(request):
        return json(PAYLOAD)

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

    async def json_endpoint(request):
        return web.json_response(PAYLOAD)

    app = web.Application()
    app.router.add_get("/json", json_endpoint)

    if __name__ == "__main__":
        web.run_app(app, host="127.0.0.1", port=8000, access_log=None)


elif KIND == "fastpysgi":
    import fastpysgi

    def app(environ, start_response):
        if environ.get("PATH_INFO") == "/json":
            start_response(
                "200 OK",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(PAYLOAD_BYTES))),
                ],
            )
            return [PAYLOAD_BYTES]
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]

    if __name__ == "__main__":
        fastpysgi.run(app, host="127.0.0.1", port=8000)


else:
    raise RuntimeError(f"unknown BENCH_APP={KIND}")
