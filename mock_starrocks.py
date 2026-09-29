import json
import os
from urllib.parse import parse_qs

import fastpysgi


def build_payload(rows):
    parts = [
        '{"connectionId":1}\n',
        '{"meta":[{"name":"id","type":"BIGINT"},{"name":"date","type":"DATE"}]}\n',
    ]
    for i in range(rows):
        day = (i % 28) + 1
        parts.append(json.dumps({"data": [i + 1, f"2026-09-{day:02d}"]}, separators=(",", ":")) + "\n")
    parts.append(json.dumps({"statistics": {"returnRows": rows}}, separators=(",", ":")) + "\n")
    return "".join(parts).encode("utf-8")


PAYLOADS = {
    "10": build_payload(10),
    "100": build_payload(100),
    "1000": build_payload(1000),
}


def app(environ, start_response):
    if environ.get("PATH_INFO") != "/sql":
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]

    query = parse_qs(environ.get("QUERY_STRING", ""))
    rows = query.get("rows", ["100"])[0]
    body = PAYLOADS.get(rows, PAYLOADS["100"])

    start_response(
        "200 OK",
        [
            ("Content-Type", "application/x-ndjson"),
            ("Content-Length", str(len(body))),
            ("Connection", "keep-alive"),
        ],
    )
    return [body]


if __name__ == "__main__":
    fastpysgi.run(app, host="127.0.0.1", port=18030)
