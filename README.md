# web_benchmark

Reproducible benchmark suite for high-performance Python HTTP/API stacks.

## Scope

The suite compares the frameworks/servers discussed in the design review for a StarRocks-facing API gateway:

- BustAPI
- TurboAPI
- Granian raw RSGI
- Falcon + Granian
- Emmett + Granian
- BlackSheep + Granian
- Starlette + Granian
- Litestar + Granian
- FastAPI + Granian
- Jero + Granian
- Robyn
- Sanic
- aiohttp
- FastPySGI
- Dreaming Electric Sheep
- Uvicorn raw ASGI baseline

The benchmark uses the same JSON response and records throughput and latency on one GitHub-hosted runner. TurboAPI is tested separately on its required free-threaded Python runtime and is explicitly marked as such.

See `RESULTS.md` after the workflow completes.
