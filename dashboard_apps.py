import json
import os

from dashboard_common import query_async, query_sync

KIND = os.environ["DASHBOARD_APP"]
WORKERS = int(os.getenv("DASHBOARD_WORKERS", "4"))


def endpoint_id_from_path(path):
    try:
        value = int(path.rsplit("/", 1)[-1])
    except Exception:
        return None
    return value if 1 <= value <= 20 else None


if KIND == "flask":
    from flask import Flask

    app = Flask(__name__)

    def make_view(endpoint_id):
        def view():
            return query_sync(endpoint_id)
        view.__name__ = f"api_{endpoint_id}"
        return view

    for i in range(1, 21):
        app.add_url_rule(
            f"/api/{i}",
            endpoint=f"api_{i}",
            view_func=make_view(i),
            methods=["GET"],
        )


elif KIND == "quart":
    from quart import Quart

    app = Quart(__name__)

    def make_view(endpoint_id):
        async def view():
            return await query_async(endpoint_id)
        view.__name__ = f"api_{endpoint_id}"
        return view

    for i in range(1, 21):
        app.add_url_rule(
            f"/api/{i}",
            endpoint=f"api_{i}",
            view_func=make_view(i),
            methods=["GET"],
        )


elif KIND == "sanic":
    from sanic import Sanic
    from sanic.response import json as sanic_json

    app = Sanic("dashboard_benchmark")

    def make_view(endpoint_id):
        async def view(request):
            return sanic_json(await query_async(endpoint_id))
        return view

    for i in range(1, 21):
        app.add_route(
            make_view(i),
            f"/api/{i}",
            methods=["GET"],
            name=f"api_{i}",
        )

    if __name__ == "__main__":
        app.run(
            host="127.0.0.1",
            port=8000,
            workers=WORKERS,
            access_log=False,
            motd=False,
        )


elif KIND == "bustapi":
    from bustapi import BustAPI

    app = BustAPI()

    def register(endpoint_id):
        @app.route(f"/api/{endpoint_id}")
        async def view():
            return await query_async(endpoint_id)
        view.__name__ = f"api_{endpoint_id}"

    for i in range(1, 21):
        register(i)

    if __name__ == "__main__":
        app.run(
            host="127.0.0.1",
            port=8000,
            workers=WORKERS,
            debug=False,
        )


elif KIND == "granian_rsgi":
    async def app(scope, proto):
        endpoint_id = endpoint_id_from_path(scope.path)
        if endpoint_id is None:
            proto.response_bytes(
                status=404,
                headers=[("content-length", "0")],
                body=b"",
            )
            return

        result = await query_async(endpoint_id)
        body = json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()

        proto.response_bytes(
            status=200,
            headers=[
                ("content-type", "application/json; charset=utf-8"),
                ("content-length", str(len(body))),
            ],
            body=body,
        )


elif KIND == "jero":
    from jero import BaseApp, Resource
    from msgspec import Struct

    class Result(Struct):
        code: int
        data: list[dict]
        count: int

    resources = []

    def make_resource(endpoint_id):
        class DashboardResource(Resource, path=f"/api/{endpoint_id}"):
            async def read_many(self) -> Result:
                value = await query_async(endpoint_id)
                return Result(
                    code=value["code"],
                    data=value["data"],
                    count=value["count"],
                )
        DashboardResource.__name__ = f"DashboardResource{endpoint_id}"
        return DashboardResource

    for i in range(1, 21):
        resources.append(make_resource(i))

    class App(BaseApp):
        async def wire(self) -> None:
            for resource in resources:
                self._include_resource(resource())

    app = App()


elif KIND == "litestar":
    from litestar import Litestar, get

    handlers = []

    def make_handler(endpoint_id):
        @get(f"/api/{endpoint_id}", sync_to_thread=False)
        async def handler() -> dict[str, object]:
            return await query_async(endpoint_id)
        handler.__name__ = f"api_{endpoint_id}"
        return handler

    for i in range(1, 21):
        handlers.append(make_handler(i))

    app = Litestar(route_handlers=handlers)


elif KIND == "fastapi":
    from fastapi import FastAPI

    app = FastAPI()

    def register(endpoint_id):
        @app.get(f"/api/{endpoint_id}")
        async def view():
            return await query_async(endpoint_id)

    for i in range(1, 21):
        register(i)


else:
    raise RuntimeError(f"unknown DASHBOARD_APP={KIND}")
