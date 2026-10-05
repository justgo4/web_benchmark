import hashlib
import hmac
import json
import os
import threading
import time

KIND = os.environ["SNAPSHOT_APP"]

USERS = {
    "u0": (b"secret-0-0123456789abcdef", sum(1 << i for i in range(0, 25))),
    "u1": (b"secret-1-0123456789abcdef", sum(1 << i for i in range(25, 50))),
    "u2": (b"secret-2-0123456789abcdef", sum(1 << i for i in range(50, 75))),
    "u3": (b"secret-3-0123456789abcdef", sum(1 << i for i in range(75, 100))),
}
WINDOW_S = 60
JSON_HEADERS = [("content-type", "application/json"), ("cache-control", "no-store")]
EMPTY = b""


def build_snapshot(generation):
    updated_ms = int(time.time() * 1000)
    metrics = tuple(
        json.dumps(
            {
                "code": 0,
                "metric": i,
                "value": generation * 1000 + i,
                "updated_ms": updated_ms,
            },
            separators=(",", ":"),
        ).encode()
        for i in range(100)
    )
    batches = {}
    for key, (_secret, mask) in USERS.items():
        rows = []
        for i in range(100):
            if mask & (1 << i):
                rows.append(
                    {
                        "metric": i,
                        "value": generation * 1000 + i,
                    }
                )
        batches[key] = json.dumps(
            {
                "code": 0,
                "updated_ms": updated_ms,
                "data": rows,
            },
            separators=(",", ":"),
        ).encode()
    return metrics, batches


METRICS, BATCHES = build_snapshot(1)


def refresh_loop():
    global METRICS, BATCHES
    generation = 1
    while True:
        time.sleep(1.0)
        generation += 1
        METRICS, BATCHES = build_snapshot(generation)


threading.Thread(target=refresh_loop, daemon=True).start()


def metric_from_path(path):
    if not path.startswith("/api/"):
        return -1
    tail = path[5:]
    if not tail.isdigit():
        return -1
    metric = int(tail)
    if metric < 0 or metric >= 100:
        return -1
    return metric


def verify(key, ts, signature, path, metric):
    if not key or not ts or not signature:
        return False
    user = USERS.get(key)
    if user is None:
        return False
    try:
        ts_i = int(ts)
    except Exception:
        return False
    if abs(int(time.time()) - ts_i) > WINDOW_S:
        return False
    secret, mask = user
    if metric >= 0 and not (mask & (1 << metric)):
        return False
    expected = hmac.digest(
        secret,
        ("GET\n" + path + "\n" + ts).encode(),
        "sha256",
    ).hex()
    return hmac.compare_digest(expected, signature)


def response_for(path, key, ts, signature):
    if path == "/snapshot":
        if not verify(key, ts, signature, path, -1):
            return 403, EMPTY
        return 200, BATCHES[key]

    metric = metric_from_path(path)
    if metric < 0:
        return 404, EMPTY
    if not verify(key, ts, signature, path, metric):
        return 403, EMPTY
    return 200, METRICS[metric]


if KIND == "fastpysgi":
    import fastpysgi

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        status, body = response_for(
            path,
            environ.get("HTTP_X_API_KEY"),
            environ.get("HTTP_X_TIMESTAMP"),
            environ.get("HTTP_X_SIGNATURE"),
        )
        reason = "OK" if status == 200 else ("Forbidden" if status == 403 else "Not Found")
        start_response(
            f"{status} {reason}",
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [body]

    if __name__ == "__main__":
        fastpysgi.run(app, host="127.0.0.1", port=8000)


elif KIND == "granian_rsgi":
    async def app(scope, proto):
        status, body = response_for(
            scope.path,
            scope.headers.get("x-api-key"),
            scope.headers.get("x-timestamp"),
            scope.headers.get("x-signature"),
        )
        proto.response_bytes(
            status=status,
            headers=JSON_HEADERS,
            body=body,
        )


elif KIND == "granian_asgi":
    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        headers = {}
        for key, value in scope["headers"]:
            headers[key] = value
        path = scope["path"]
        status, body = response_for(
            path,
            headers.get(b"x-api-key", b"").decode(),
            headers.get(b"x-timestamp", b"").decode(),
            headers.get(b"x-signature", b"").decode(),
        )
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


elif KIND == "sanic":
    from sanic import Sanic
    from sanic.response import raw

    app = Sanic("snapshot_gateway")

    @app.get("/api/<metric:int>")
    async def metric_endpoint(request, metric):
        path = f"/api/{metric}"
        status, body = response_for(
            path,
            request.headers.get("x-api-key"),
            request.headers.get("x-timestamp"),
            request.headers.get("x-signature"),
        )
        return raw(
            body,
            status=status,
            content_type="application/json",
            headers={"cache-control": "no-store"},
        )

    @app.get("/snapshot")
    async def snapshot_endpoint(request):
        status, body = response_for(
            "/snapshot",
            request.headers.get("x-api-key"),
            request.headers.get("x-timestamp"),
            request.headers.get("x-signature"),
        )
        return raw(
            body,
            status=status,
            content_type="application/json",
            headers={"cache-control": "no-store"},
        )

    if __name__ == "__main__":
        app.run(
            host="127.0.0.1",
            port=8000,
            single_process=True,
            access_log=False,
            motd=False,
        )


else:
    raise RuntimeError(f"unknown SNAPSHOT_APP={KIND}")
