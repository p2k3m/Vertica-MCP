from fastapi import FastAPI, Request, HTTPException
from .tools import mcp
from .config import settings


app = FastAPI()


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.middleware("http")
async def bearer(request: Request, call_next):
    token = settings.http_token
    if token and request.url.path not in ("/healthz", "/api/info", "/sse"):
        if request.headers.get("authorization") != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)


app.mount("/api", mcp.streamable_http_app())
app.mount("/sse", mcp.sse_app())
