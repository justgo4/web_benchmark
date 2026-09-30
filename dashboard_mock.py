import asyncio
import json
import os

DELAY_MS = float(os.getenv("MOCK_QUERY_DELAY_MS", "2"))
ROWS = int(os.getenv("MOCK_ROWS", "10"))

parts = [
    '{"connectionId":1}\n',
    '{"meta":[{"name":"id","type":"BIGINT"},{"name":"date","type":"DATE"}]}\n',
]
for i in range(ROWS):
    parts.append(json.dumps(
        {"data": [i + 1, f"2026-09-{(i % 28) + 1:02d}"]},
        separators=(",", ":"),
    ) + "\n")
parts.append(json.dumps(
    {"statistics": {"returnRows": ROWS}},
    separators=(",", ":"),
) + "\n")
BODY = "".join(parts).encode()


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    if scope["path"] != "/sql":
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})
        return

    if DELAY_MS:
        await asyncio.sleep(DELAY_MS / 1000)

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/x-ndjson"),
            (b"content-length", str(len(BODY)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": BODY})
