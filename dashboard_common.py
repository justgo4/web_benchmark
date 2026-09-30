import json
import os

from pyreqwest.client import ClientBuilder, SyncClientBuilder

MOCK_URL = os.getenv("DASHBOARD_STARROCKS_URL", "http://127.0.0.1:18030/sql")
ROWS = int(os.getenv("DASHBOARD_ROWS", "10"))

_async_client = (
    ClientBuilder()
    .pool_max_idle_per_host(512)
    .error_for_status(True)
    .build()
)

_sync_client = (
    SyncClientBuilder()
    .pool_max_idle_per_host(512)
    .error_for_status(True)
    .build()
)


def parse_ndjson(text):
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
    return rows


async def query_async(endpoint_id):
    response = await (
        _async_client
        .post(f"{MOCK_URL}?endpoint={endpoint_id}&rows={ROWS}")
        .body_json({
            "query": f"select id, date from test where dashboard_id = {endpoint_id};"
        })
        .build()
        .send()
    )
    rows = parse_ndjson(await response.text())
    return {"code": 0, "data": rows, "count": len(rows)}


def query_sync(endpoint_id):
    response = (
        _sync_client
        .post(f"{MOCK_URL}?endpoint={endpoint_id}&rows={ROWS}")
        .body_json({
            "query": f"select id, date from test where dashboard_id = {endpoint_id};"
        })
        .build()
        .send()
    )
    rows = parse_ndjson(response.text())
    return {"code": 0, "data": rows, "count": len(rows)}
