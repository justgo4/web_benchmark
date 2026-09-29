import json
import os

from pyreqwest.client import ClientBuilder, SyncClientBuilder

STARROCKS_URL = os.getenv(
    "STARROCKS_URL",
    "http://127.0.0.1:8030/api/v1/catalogs/default_catalog/databases/test/sql",
)
STARROCKS_USER = os.getenv("STARROCKS_USER", "api_user")
STARROCKS_PASSWORD = os.getenv("STARROCKS_PASSWORD", "")
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


def parse_starrocks_ndjson(text):
    columns = None
    rows = []

    for line in text.splitlines():
        if not line:
            continue

        item = json.loads(line)

        if "meta" in item:
            columns = [column["name"] for column in item["meta"]]
            continue

        if "data" in item:
            if columns is None:
                raise RuntimeError("StarRocks returned data before meta")
            rows.append(dict(zip(columns, item["data"])))

    return {
        "code": 0,
        "data": rows,
        "count": len(rows),
    }


async def query_test_async():
    response = await (
        _async_client
        .post(STARROCKS_URL)
        .basic_auth(STARROCKS_USER, STARROCKS_PASSWORD)
        .body_json({"query": SQL})
        .build()
        .send()
    )
    return parse_starrocks_ndjson(await response.text())


def query_test_sync():
    response = (
        _sync_client
        .post(STARROCKS_URL)
        .basic_auth(STARROCKS_USER, STARROCKS_PASSWORD)
        .body_json({"query": SQL})
        .build()
        .send()
    )
    return parse_starrocks_ndjson(response.text())


def json_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
