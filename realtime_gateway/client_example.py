import hmac
import os
import time
import urllib.request

BASE = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")
KEY = os.environ["API_KEY"]
SECRET = os.environ["API_SECRET"].encode()

def get(path):
    ts = str(int(time.time()))
    signature = hmac.digest(
        SECRET,
        ("GET\n" + path + "\n" + ts).encode(),
        "sha256",
    ).hex()
    req = urllib.request.Request(
        BASE + path,
        headers={
            "X-Api-Key": KEY,
            "X-Timestamp": ts,
            "X-Signature": signature,
        },
    )
    with urllib.request.urlopen(req, timeout=2) as response:
        print(response.status, response.read().decode())

get("/api/m000")
get("/snapshot")
